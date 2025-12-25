import argparse
import asyncio

# ============================================================ 
# PHASE 1: CORE DATA STRUCTURES
# ============================================================ 

# Define a broader range of potential servers (B1 to B10)
# The Load Balancer will check these ports to see who is alive.
SERVER_POOL = [('127.0.0.1', 8881 + i) for i in range(10)]

HEALTH_CHECK_INTERVAL = 5  # seconds
WAIT_FOR_BACKEND_TIMEOUT = 30  # seconds to wait for a backend to become healthy

# ============================================================ 
# PHASE 2 & 3: PLACEHOLDER DATA STRUCTURES
# ============================================================ 

# PHASE 2: ACTIVE_SERVERS will be managed by health checks
ACTIVE_SERVERS = [] 
active_servers_lock = asyncio.Lock()

# PHASE 2: CONNECTION_COUNT for least-connections scheduling
CONNECTION_COUNT = {server: 0 for server in SERVER_POOL}

# PHASE 3: SESSION_MAP for sticky sessions
SESSION_MAP = {}

# Scheduler selection
SCHEDULING_ALGORITHM = "auto"
round_robin_index = 0


async def check_server_health(server):
    """
    Attempt to connect to a backend to determine health.
    """
    host, port = server
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=1
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError):
        return False
    except Exception:
        return False


async def refresh_active_servers():
    """
    Run a full health check pass and update ACTIVE_SERVERS.
    """
    global ACTIVE_SERVERS
    healthy_servers = []
    
    # Check all potential servers
    for server in SERVER_POOL:
        is_healthy = await check_server_health(server)
        if is_healthy:
            healthy_servers.append(server)
            
        if not is_healthy:
            CONNECTION_COUNT[server] = 0
        else:
            CONNECTION_COUNT.setdefault(server, 0)

    # Logging Logic
    if not healthy_servers:
        print("LB: [WARNING] No backend servers are currently active/healthy.")
    else:
        print(f"LB: --- Health Check Passed ({len(healthy_servers)} active) ---")
        for server in healthy_servers:
            host, port = server
            print(f"LB: [ACTIVE] Server {host}:{port} is healthy.")

    async with active_servers_lock:
        ACTIVE_SERVERS = healthy_servers


async def perform_health_checks():
    """
    Periodically refresh ACTIVE_SERVERS to reflect current backend health.
    """
    while True:
        print("LB: Performing health checks...")
        await refresh_active_servers()
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


async def select_backend(exclude=None):
    """
    Select a backend server based on the configured scheduling algorithm.
    exclude: set of servers already tried for this client (for failover).
    """
    global round_robin_index
    exclude = exclude or set()

    async with active_servers_lock:
        candidates = [s for s in ACTIVE_SERVERS if s not in exclude]
        if not candidates:
            return None

        def choose_algorithm():
            if SCHEDULING_ALGORITHM != "auto":
                return SCHEDULING_ALGORITHM
            if len(candidates) <= 1:
                return "round-robin"
            counts = [CONNECTION_COUNT.get(s, 0) for s in candidates]
            return "round-robin" if len(set(counts)) == 1 else "least-connections"

        algo = choose_algorithm()

        if algo == "least-connections":
            min_connections = min(CONNECTION_COUNT.get(s, 0) for s in candidates)
            least_connected = [s for s in candidates if CONNECTION_COUNT.get(s, 0) == min_connections]
            chosen = least_connected[round_robin_index % len(least_connected)]
        else:  # round-robin
            chosen = candidates[round_robin_index % len(candidates)]

        round_robin_index += 1
        return chosen, algo


async def wait_for_backend(timeout, exclude=None):
    """
    Wait for up to `timeout` seconds for a backend to become available.
    Returns (server, algo) or None.
    """
    start = asyncio.get_running_loop().time()
    while True:
        selection = await select_backend(exclude)
        if selection:
            return selection
        elapsed = asyncio.get_running_loop().time() - start
        if elapsed >= timeout:
            return None
        await asyncio.sleep(min(HEALTH_CHECK_INTERVAL, timeout - elapsed))


async def handle_client(client_reader, client_writer):
    """
    Handles a new client connection by forwarding it to a backend server.
    """
    client_addr = client_writer.get_extra_info('peername')
    print(f"LB: Accepted connection from {client_addr}")

    tried_servers = set()
    selection = await select_backend(tried_servers)

    if not selection:
        print("LB: No active backend servers available. Waiting for a backend to recover...")
        selection = await wait_for_backend(WAIT_FOR_BACKEND_TIMEOUT)
        if not selection:
            print("LB: Timeout waiting for backend. Closing client.")
            client_writer.close()
            await client_writer.wait_closed()
            return

    selected_server, selected_algo = selection
    backend_host, backend_port = None, None
    backend_reader, backend_writer = None, None
    connected_backend = None

    while selected_server:
        backend_host, backend_port = selected_server
        print(f"LB: Forwarding {client_addr} to {backend_host}:{backend_port} ({selected_algo})")
        try:
            backend_reader, backend_writer = await asyncio.open_connection(backend_host, backend_port)
            connected_backend = (backend_host, backend_port)
            async with active_servers_lock:
                CONNECTION_COUNT[(backend_host, backend_port)] += 1
            print(f"LB: Connection count for {backend_host}:{backend_port}: {CONNECTION_COUNT[(backend_host, backend_port)]}")
        except ConnectionRefusedError:
            print(f"LB: Connection refused by backend server {backend_host}:{backend_port}. Trying another.")
            backend_reader, backend_writer = None, None
        except Exception as e:
            print(f"LB: Failed to connect to backend {backend_host}:{backend_port}: {e}. Trying another.")
            backend_reader, backend_writer = None, None

        if backend_reader is None or backend_writer is None:
            tried_servers.add(selected_server)
            selection = await select_backend(tried_servers)
            if not selection:
                print("LB: No alternative backend immediately available. Waiting for backend to recover...")
                selection = await wait_for_backend(WAIT_FOR_BACKEND_TIMEOUT)
            if not selection:
                print("LB: Timeout waiting for backend. Closing client.")
                break
            selected_server, selected_algo = selection
            continue

        # Connected: start piping and monitor for mid-stream backend failure.
        client_to_backend = asyncio.create_task(
            pipe_data(client_reader, backend_writer, client_addr, "Client -> Backend")
        )
        backend_to_client = asyncio.create_task(
            pipe_data(backend_reader, client_writer, (backend_host, backend_port), "Backend -> Client")
        )

        done, pending = await asyncio.wait(
            {client_to_backend, backend_to_client},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # If client side finished first, break and close everything.
        if client_to_backend in done:
            backend_to_client.cancel()
            await asyncio.gather(backend_to_client, return_exceptions=True)
            break

        # Backend finished first: attempt mid-stream failover.
        client_to_backend.cancel()
        await asyncio.gather(client_to_backend, return_exceptions=True)
        print(f"LB: Backend {backend_host}:{backend_port} closed mid-stream for {client_addr}; attempting failover.")

        # Clean up current backend and decrement count.
        if backend_writer:
            backend_writer.close()
            await backend_writer.wait_closed()
        async with active_servers_lock:
            if connected_backend and connected_backend in CONNECTION_COUNT and CONNECTION_COUNT[connected_backend] > 0:
                CONNECTION_COUNT[connected_backend] -= 1
        connected_backend = None
        backend_reader, backend_writer = None, None

        tried_servers.add(selected_server)
        selection = await select_backend(tried_servers)
        if not selection:
            print("LB: No alternative backend available immediately. Waiting for backend to recover...")
            selection = await wait_for_backend(WAIT_FOR_BACKEND_TIMEOUT)
        if not selection:
            print("LB: Timeout waiting for backend during failover. Closing client.")
            selected_server = None
        else:
            selected_server, selected_algo = selection

    # Final cleanup and count decrement for the last backend used.
    if backend_writer:
        backend_writer.close()
        await backend_writer.wait_closed()
    async with active_servers_lock:
        if connected_backend and connected_backend in CONNECTION_COUNT and CONNECTION_COUNT[connected_backend] > 0:
            CONNECTION_COUNT[connected_backend] -= 1

    if client_writer:
        client_writer.close()
        await client_writer.wait_closed()

    print(f"LB: Closed connection for {client_addr}")


async def main(host, port, algorithm):
    """
    Starts the Load Balancer server.
    """
    global SCHEDULING_ALGORITHM
    SCHEDULING_ALGORITHM = algorithm

    print(f"LB: Initializing with algorithm={SCHEDULING_ALGORITHM}")
    print(f"LB: Load Balancer Started on {host}:{port}")
    await refresh_active_servers()

    server = await asyncio.start_server(handle_client, host, port)

    addr = server.sockets[0].getsockname()
    print(f'Load Balancer listening on {addr}')

    # Start health checks in the background
    health_check_task = asyncio.create_task(perform_health_checks())

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AsyncIO Load Balancer")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the load balancer to (use 0.0.0.0 for LAN)")
    parser.add_argument("--port", type=int, default=8080, help="Port for the load balancer to listen on")
    parser.add_argument(
        "--algorithm",
        choices=["auto", "round-robin", "least-connections"],
        default="auto",
        help="Scheduling algorithm to use (auto picks round-robin when counts are even, least-connections when imbalanced)"
    )

    args = parser.parse_args()

    try:
        asyncio.run(main(args.host, args.port, args.algorithm))
    except KeyboardInterrupt:
        print("\nShutting down Load Balancer...")