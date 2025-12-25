from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
from typing import Dict, List
from .process_manager import manager, log_queue

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Data Models ---
class ServerConfig(BaseModel):
    name: str
    port: int

class ClientMessage(BaseModel):
    client_id: str
    message: str

# --- State Management ---
# Track registered servers
SERVER_REGISTRY: List[ServerConfig] = [
    ServerConfig(name="B1", port=8881),
    ServerConfig(name="B2", port=8882),
    ServerConfig(name="B3", port=8883),
]

# Track active client connections (TCP sockets)
class ClientSession:
    def __init__(self, reader, writer, client_id):
        self.reader = reader
        self.writer = writer
        self.client_id = client_id
        self.connected = True

    async def send(self, msg: str):
        if not self.connected:
            raise Exception("Client not connected")
        self.writer.write(msg.encode() + b'\n')
        await self.writer.drain()

    async def listen_loop(self):
        """Continuously reads from the socket until disconnected."""
        try:
            while self.connected:
                data = await self.reader.read(1024)
                if not data:
                    break # Connection closed
                response = data.decode().strip()
                await log_queue.put(f"[{self.client_id}] 📥 Received: {response}")
        except Exception as e:
            await log_queue.put(f"[{self.client_id}] Error reading: {e}")
        finally:
            self.connected = False
            await log_queue.put(f"[{self.client_id}] Disconnected.")

    async def close(self):
        self.connected = False
        self.writer.close()
        await self.writer.wait_closed()

ACTIVE_CLIENTS: Dict[str, ClientSession] = {}

# --- WebSocket Broadcaster ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

ws_manager = ConnectionManager()

async def log_broadcaster():
    while True:
        log = await log_queue.get()
        await ws_manager.broadcast(log)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(log_broadcaster())

# --- API Endpoints ---

@app.get("/api/state")
async def get_state():
    """Returns the full state of the simulation."""
    proc_status = manager.get_status()
    
    # Merge registry with running status
    servers = []
    for s in SERVER_REGISTRY:
        servers.append({
            "name": s.name,
            "port": s.port,
            "status": proc_status.get(s.name, "stopped")
        })

    clients = []
    for cid, session in ACTIVE_CLIENTS.items():
        clients.append({
            "id": cid,
            "connected": session.connected
        })

    lb_status = proc_status.get("LoadBalancer", "stopped")

    return {
        "load_balancer": lb_status,
        "servers": servers,
        "clients": clients
    }

# --- Load Balancer Control ---
@app.post("/api/lb/start")
async def start_lb():
    success = await manager.start_process("LoadBalancer", "load_balancer.py", ["--port", "8080"])
    return {"success": success}

@app.post("/api/lb/stop")
async def stop_lb():
    success = await manager.stop_process("LoadBalancer")
    return {"success": success}

# --- Server Control ---
@app.post("/api/server/add")
async def add_server():
    # Auto-generate name/port
    count = len(SERVER_REGISTRY) + 1
    # Find next available port starting from 8881
    used_ports = set(s.port for s in SERVER_REGISTRY)
    next_port = 8881
    while next_port in used_ports:
        next_port += 1
    
    # Find next available name B4, B5...
    used_names = set(s.name for s in SERVER_REGISTRY)
    next_idx = 4
    new_name = f"B{next_idx}"
    while new_name in used_names:
        next_idx += 1
        new_name = f"B{next_idx}"

    config = ServerConfig(name=new_name, port=next_port)
    SERVER_REGISTRY.append(config)
    await log_queue.put(f"[System] Added configuration for {new_name} on port {next_port}.")
    return {"success": True, "server": config}

@app.post("/api/server/{name}/start")
async def start_server(name: str):
    config = next((s for s in SERVER_REGISTRY if s.name == name), None)
    if not config:
        raise HTTPException(status_code=404, detail="Server not found")
    
    success = await manager.start_process(name, "server.py", ["--name", name, "--port", str(config.port)])
    return {"success": success}

@app.post("/api/server/{name}/stop")
async def stop_server(name: str):
    success = await manager.stop_process(name)
    return {"success": success}

@app.delete("/api/server/{name}")
async def remove_server(name: str):
    await manager.stop_process(name)
    global SERVER_REGISTRY
    SERVER_REGISTRY = [s for s in SERVER_REGISTRY if s.name != name]
    await log_queue.put(f"[System] Removed server {name}.")
    return {"success": True}

# --- Client Control ---
@app.post("/api/client/add")
async def add_client():
    client_id = f"Client-{len(ACTIVE_CLIENTS) + 1}"
    try:
        await log_queue.put(f"[System] {client_id} connecting to Load Balancer...")
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 8080), timeout=2.0
        )
        
        session = ClientSession(reader, writer, client_id)
        ACTIVE_CLIENTS[client_id] = session
        
        # Start listening for responses
        asyncio.create_task(session.listen_loop())
        
        await log_queue.put(f"[{client_id}] ✅ Connected to Load Balancer.")
        return {"success": True, "id": client_id}
    except Exception as e:
        await log_queue.put(f"[System] {client_id} failed to connect: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/client/send")
async def client_send(req: ClientMessage):
    if req.client_id not in ACTIVE_CLIENTS:
        raise HTTPException(status_code=404, detail="Client not found")
    
    session = ACTIVE_CLIENTS[req.client_id]
    try:
        await log_queue.put(f"[{req.client_id}] 📤 Sending: {req.message}")
        await session.send(req.message)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/client/{client_id}")
async def remove_client(client_id: str):
    if client_id in ACTIVE_CLIENTS:
        await ACTIVE_CLIENTS[client_id].close()
        del ACTIVE_CLIENTS[client_id]
        return {"success": True}
    return {"success": False}

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)