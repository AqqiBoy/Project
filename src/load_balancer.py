import asyncio
from itertools import cycle

# ============================================================ 
# PHASE 1: CORE DATA STRUCTURES
# ============================================================ 

# Use 127.0.0.1 for local testing.
# In a real LAN environment, replace with private IPs like:
# ('192.168.1.11', 8888), ('192.168.1.12', 8888)
SERVER_POOL = [
    ('127.0.0.1', 8881),
    ('127.0.0.1', 8882),
]

HEALTH_CHECK_INTERVAL = 5  # seconds

# Use itertools.cycle for simple round-robin
server_iterator = cycle(SERVER_POOL)


# ============================================================ 
# PHASE 2 & 3: PLACEHOLDER DATA STRUCTURES
# ============================================================ 

# PHASE 2: ACTIVE_SERVERS will be managed by health checks
# Example: ACTIVE_SERVERS = [('127.0.0.1', 8881)]
ACTIVE_SERVERS = [] 
active_servers_lock = asyncio.Lock()

# PHASE 2: CONNECTION_COUNT for least-connections scheduling
# Example: CONNECTION_COUNT = {('127.0.0.1', 8881): 5}
CONNECTION_COUNT = {server: 0 for server in SERVER_POOL}

# PHASE 3: SESSION_MAP for sticky sessions
# Example: SESSION_MAP = {'<client_ip>:<client_port>': '<backend_addr>'}
SESSION_MAP = {}


async def perform_health_checks():
    global ACTIVE_SERVERS
    while True:
        print("LB: Performing health checks...")
        healthy_servers = []
        for server in SERVER_POOL:
            host, port = server
            try:
                # Attempt to open a connection to the backend server
                # Set a timeout for the connection attempt
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=1
                )
                writer.close()
                await writer.wait_closed()
                healthy_servers.append(server)
                print(f"LB: Server {server} is healthy.")
            except (asyncio.TimeoutError, ConnectionRefusedError):
                print(f"LB: Server {server} is unhealthy.")
            except Exception as e:
                print(f"LB: Error checking health of {server}: {e}")
        
        async with active_servers_lock:
            ACTIVE_SERVERS = healthy_servers
            print(f"LB: Active servers: {ACTIVE_SERVERS}")
        
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)

async def pipe_data(reader, writer, peer_name, direction):
    """
    Reads data from a reader and writes it to a writer,
    logging the data flow.
    """
    try:
        while not reader.at_eof():
            data = await reader.read(2048)
            if not data:
                break
            # print(f"[{direction}] {peer_name}: Forwarding data")
            writer.write(data)
            await writer.drain()
    except asyncio.CancelledError:
        # This is expected when one side closes the connection
        pass
    except Exception as e:
        print(f"Error in pipe_data ({direction} from {peer_name}): {e}")
    # Removed the finally block that closes the writer from here.
    # The writers will be closed by handle_client.


async def handle_client(client_reader, client_writer):
    """
    Handles a new client connection by forwarding it to a backend server.
    """
    client_addr = client_writer.get_extra_info('peername')
    print(f"LB: Accepted connection from {client_addr}")

    # ============================================================ 
    # PHASE 2: Least-Connections Scheduling
    # ============================================================ 
    backend_host, backend_port = None, None
    async with active_servers_lock:
        if not ACTIVE_SERVERS:
            print("LB: No active backend servers available.")
            client_writer.close()
            await client_writer.wait_closed()
            return
        
        # Find the server(s) with the least connections among active servers
        min_connections = float('inf')
        least_connected_servers = []

        for server in ACTIVE_SERVERS:
            count = CONNECTION_COUNT.get(server, 0)
            if count < min_connections:
                min_connections = count
                least_connected_servers = [server]
            elif count == min_connections:
                least_connected_servers.append(server)
        
        # Use round-robin among the least connected servers
        # This creates a new iterator each time, ensuring fairness among them
        # (backend_host, backend_port) = next(cycle(least_connected_servers))
        # This is not ideal as cycle creates a new iterator each time and loses state.
        # For simplicity and given the small number of servers, picking the first is acceptable for now.
        # A more robust solution would require a dedicated iterator for least_connected_servers
        # or more complex state management.
        (backend_host, backend_port) = least_connected_servers[0] # Simplistic for now.

    print(f"LB: Forwarding {client_addr} to {backend_host}:{backend_port} (Least-Connections)")
    
    backend_reader, backend_writer = None, None
    try:
        # Establish connection to the selected backend server
        backend_reader, backend_writer = await asyncio.open_connection(backend_host, backend_port)
        async with active_servers_lock:
            CONNECTION_COUNT[(backend_host, backend_port)] += 1
        print(f"LB: Connection count for {backend_host}:{backend_port}: {CONNECTION_COUNT[(backend_host, backend_port)]}")

    except ConnectionRefusedError:
        print(f"LB: Connection refused by backend server {backend_host}:{backend_port}.")
        client_writer.close()
        await client_writer.wait_closed()
        return
    except Exception as e:
        print(f"LB: Failed to connect to backend {backend_host}:{backend_port}: {e}")
        client_writer.close()
        await client_writer.wait_closed()
        return

    try:
        # Create tasks for bidirectional data piping
        client_to_backend = asyncio.create_task(
            pipe_data(client_reader, backend_writer, client_addr, "Client -> Backend")
        )
        backend_to_client = asyncio.create_task(
            pipe_data(backend_reader, client_writer, (backend_host, backend_port), "Backend -> Client")
        )

        # Wait for both tasks to complete. This ensures that the connection remains open
        # as long as data is flowing in either direction.
        # Use return_when=asyncio.ALL_COMPLETED to wait for both pipes to finish naturally.
        # If the client or backend closes their side, that pipe_data will finish.
        # When both finish, then the overall connection can be closed.
        await asyncio.gather(client_to_backend, backend_to_client)

    except asyncio.CancelledError:
        # This can happen if the handle_client task itself is cancelled.
        pass
    except Exception as e:
        print(f"LB: Error during data piping for {client_addr}: {e}")
    finally:
        # Ensure both client and backend writers are closed
        if client_writer:
            client_writer.close()
            await client_writer.wait_closed()
        if backend_writer:
            backend_writer.close()
            await backend_writer.wait_closed()

        async with active_servers_lock:
            if (backend_host, backend_port) in CONNECTION_COUNT and CONNECTION_COUNT[(backend_host, backend_port)] > 0:
                CONNECTION_COUNT[(backend_host, backend_port)] -= 1
        print(f"LB: Connection count for {backend_host}:{backend_port}: {CONNECTION_COUNT.get((backend_host, backend_port), 0)}")
    
    print(f"LB: Closed connection for {client_addr}")


async def main(host, port):
    """
    Starts the Load Balancer server.
    """
    server = await asyncio.start_server(handle_client, host, port)

    addr = server.sockets[0].getsockname()
    print(f'Load Balancer listening on {addr}')

    # Start health checks in the background
    health_check_task = asyncio.create_task(perform_health_checks())

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    LB_HOST = "0.0.0.0"  # Listen on all interfaces for LAN access
    LB_PORT = 8080       # The single public-facing port

    try:
        asyncio.run(main(LB_HOST, LB_PORT))
    except KeyboardInterrupt:
        print("\nShutting down Load Balancer...")
