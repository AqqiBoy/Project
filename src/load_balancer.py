# import argparse
# import asyncio

# # ============================================================ 
# # PHASE 1: CORE DATA STRUCTURES
# # ============================================================ 

# # Use 127.0.0.1 for local testing.
# # In a real LAN environment, replace with private IPs like:
# # ('192.168.1.11', 8888), ('192.168.1.12', 8888)
# SERVER_POOL = [
#     ('127.0.0.1', 8881),
#     ('127.0.0.1', 8882),
# ]

# HEALTH_CHECK_INTERVAL = 5  # seconds
# WAIT_FOR_BACKEND_TIMEOUT = 30  # seconds to wait for a backend to become healthy

# # ============================================================ 
# # PHASE 2 & 3: PLACEHOLDER DATA STRUCTURES
# # ============================================================ 

# # PHASE 2: ACTIVE_SERVERS will be managed by health checks
# # Example: ACTIVE_SERVERS = [('127.0.0.1', 8881)]
# ACTIVE_SERVERS = [] 
# active_servers_lock = asyncio.Lock()

# # PHASE 2: CONNECTION_COUNT for least-connections scheduling
# # Example: CONNECTION_COUNT = {('127.0.0.1', 8881): 5}
# CONNECTION_COUNT = {server: 0 for server in SERVER_POOL}

# # PHASE 3: SESSION_MAP for sticky sessions
# # Example: SESSION_MAP = {'<client_ip>:<client_port>': '<backend_addr>'}
# SESSION_MAP = {}
# session_map_lock = asyncio.Lock() # Added lock for SESSION_MAP

# # Scheduler selection
# SCHEDULING_ALGORITHM = "auto"  # "auto", "round-robin", or "least-connections"
# round_robin_index = 0  # shared index used for round-robin and tie-breaking


# async def check_server_health(server):
#     """
#     Attempt to connect to a backend to determine health.
#     """
#     host, port = server
#     try:
#         _, writer = await asyncio.wait_for(
#             asyncio.open_connection(host, port), timeout=1
#         )
#         writer.close()
#         await writer.wait_closed()
#         return True
#     except (asyncio.TimeoutError, ConnectionRefusedError):
#         return False
#     except Exception as e:
#         print(f"LB: Error checking health of {server}: {e}")
#         return False


# async def refresh_active_servers():
#     """
#     Run a full health check pass and update ACTIVE_SERVERS.
#     """
#     global ACTIVE_SERVERS
#     healthy_servers = []
#     for server in SERVER_POOL:
#         is_healthy = await check_server_health(server)
#         if is_healthy:
#             healthy_servers.append(server)
#             print(f"LB: Server {server} is healthy.")
#         else:
#             print(f"LB: Server {server} is unhealthy.")
#         # Reset connection counts for unhealthy servers to avoid stale skew.
#         if not is_healthy:
#             CONNECTION_COUNT[server] = 0
#         else:
#             CONNECTION_COUNT.setdefault(server, 0)

#     async with active_servers_lock:
#         ACTIVE_SERVERS = healthy_servers
#         print(f"LB: Active servers updated: {ACTIVE_SERVERS}")


# async def perform_health_checks():
#     """
#     Periodically refresh ACTIVE_SERVERS to reflect current backend health.
#     """
#     while True:
#         print("LB: Performing health checks...")
#         await refresh_active_servers()
#         await asyncio.sleep(HEALTH_CHECK_INTERVAL)

# async def pipe_data(reader, writer, peer_name, direction):
#     """
#     Reads data from a reader and writes it to a writer,
#     logging the data flow.
#     """
#     try:
#         while not reader.at_eof():
#             data = await reader.read(2048)
#             if not data:
#                 break
#             # print(f"[{direction}] {peer_name}: Forwarding data")
#             writer.write(data)
#             await writer.drain()
#     except asyncio.CancelledError:
#         # This is expected when one side closes the connection
#         pass
#     except Exception as e:
#         print(f"Error in pipe_data ({direction} from {peer_name}): {e}")
#     # Removed the finally block that closes the writer from here.
#     # The writers will be closed by handle_client.


# async def select_backend(exclude=None):
#     """
#     Select a backend server based on the configured scheduling algorithm.
#     exclude: set of servers already tried for this client (for failover).
#     Returns (server, algo) or None.
#     """
#     global round_robin_index
#     exclude = exclude or set()

#     async with active_servers_lock:
#         candidates = [s for s in ACTIVE_SERVERS if s not in exclude]
#         if not candidates:
#             return None

#         def choose_algorithm():
#             if SCHEDULING_ALGORITHM != "auto":
#                 return SCHEDULING_ALGORITHM
#             if len(candidates) <= 1:
#                 return "round-robin"
#             counts = [CONNECTION_COUNT.get(s, 0) for s in candidates]
#             return "round-robin" if len(set(counts)) == 1 else "least-connections"

#         algo = choose_algorithm()

#         if algo == "least-connections":
#             min_connections = min(CONNECTION_COUNT.get(s, 0) for s in candidates)
#             least_connected = [s for s in candidates if CONNECTION_COUNT.get(s, 0) == min_connections]
#             chosen = least_connected[round_robin_index % len(least_connected)]
#         else:  # round-robin
#             chosen = candidates[round_robin_index % len(candidates)]

#         round_robin_index += 1
#         return chosen, algo


# async def wait_for_backend(timeout, exclude=None):
#     """
#     Wait for up to `timeout` seconds for a backend to become available.
#     Returns (server, algo) or None.
#     """
#     start = asyncio.get_running_loop().time()
#     while True:
#         selection = await select_backend(exclude)
#         if selection:
#             return selection
#         elapsed = asyncio.get_running_loop().time() - start
#         if elapsed >= timeout:
#             return None
#         await asyncio.sleep(min(HEALTH_CHECK_INTERVAL, timeout - elapsed))

# def get_client_key(client_addr):
#     """
#     Generates a unique key for the client for the SESSION_MAP.
#     """
#     return f"{client_addr[0]}:{client_addr[1]}"


# async def handle_client(client_reader, client_writer):
#     """
#     Handles a new client connection by forwarding it to a backend server, 
#     with support for Persistent Sticky Sessions.
#     """
#     client_addr = client_writer.get_extra_info('peername')
#     client_key = get_client_key(client_addr)
#     print(f"LB: Accepted connection from {client_addr}")

#     tried_servers = set()
#     selected_server = None
#     selected_algo = None
    
#     # 1. Check for Sticky Session
#     # No need to remove the entry if the client disconnects; we want it to persist.
#     async with session_map_lock:
#         sticky_target = SESSION_MAP.get(client_key)
        
#     if sticky_target:
#         # Check if the sticky server is currently healthy and active
#         async with active_servers_lock:
#             if sticky_target in ACTIVE_SERVERS:
#                 selected_server = sticky_target
#                 selected_algo = "sticky"
#                 print(f"LB: Sticky session found for {client_key} -> {selected_server}")
#             else:
#                 # Sticky server is down, force selection of a new one (failover)
#                 print(f"LB: Sticky server {sticky_target} is unhealthy. Falling back to scheduling.")
#                 tried_servers.add(sticky_target)
#                 # DO NOT delete sticky_target from SESSION_MAP here; we want it to stick 
#                 # to the NEW server chosen during failover below.

#     # 2. If no valid sticky session, use the scheduler
#     if not selected_server:
#         selection = await select_backend(tried_servers)

#         if not selection:
#             print("LB: No active backend servers available. Waiting for a backend to recover...")
#             selection = await wait_for_backend(WAIT_FOR_BACKEND_TIMEOUT, tried_servers)
#             if not selection:
#                 print("LB: Timeout waiting for backend. Closing client.")
#                 client_writer.close()
#                 await client_writer.wait_closed()
#                 # Remove sticky session only if we failed to route completely
#                 async with session_map_lock:
#                     SESSION_MAP.pop(client_key, None)
#                 return
        
#         selected_server, selected_algo = selection

#     backend_host, backend_port = None, None
#     backend_reader, backend_writer = None, None
#     connected_backend = None

#     # This loop handles initial connection attempt and mid-stream failover
#     while selected_server:
#         backend_host, backend_port = selected_server
#         print(f"LB: Forwarding {client_addr} to {backend_host}:{backend_port} ({selected_algo})")
        
#         # --- PHASE 3: Update SESSION_MAP (New or Overwrite) ---
#         # Any successful connection *permanently* updates the sticky target.
#         async with session_map_lock:
#             SESSION_MAP[client_key] = selected_server
#             print(f"LB: Set persistent sticky session for {client_key} -> {selected_server}")

#         try:
#             backend_reader, backend_writer = await asyncio.open_connection(backend_host, backend_port)
#             connected_backend = (backend_host, backend_port)
#             async with active_servers_lock:
#                 CONNECTION_COUNT[(backend_host, backend_port)] += 1
#             print(f"LB: Connection count for {backend_host}:{backend_port}: {CONNECTION_COUNT[(backend_host, backend_port)]}")
#         except ConnectionRefusedError:
#             print(f"LB: Connection refused by backend server {backend_host}:{backend_port}. Trying another.")
#             backend_reader, backend_writer = None, None
#         except Exception as e:
#             print(f"LB: Failed to connect to backend {backend_host}:{backend_port}: {e}. Trying another.")
#             backend_reader, backend_writer = None, None

#         if backend_reader is None or backend_writer is None:
#             # Connection failed, try a different server
#             tried_servers.add(selected_server)
#             selection = await select_backend(tried_servers)
#             if not selection:
#                 print("LB: No alternative backend immediately available. Waiting for backend to recover...")
#                 selection = await wait_for_backend(WAIT_FOR_BACKEND_TIMEOUT, tried_servers)
            
#             if not selection:
#                 print("LB: Timeout waiting for backend. Closing client.")
#                 break # Exit while loop and close client
            
#             selected_server, selected_algo = selection
            
#             # Since connection failed, we remove the failed server's sticky assignment 
#             # *only* if the connection fails immediately. The new server will be assigned next.
#             # This logic must be careful not to delete the new target before attempting connection.
#             # We rely on the next successful connection attempt in the 'while' loop to overwrite SESSION_MAP.
            
#             continue # Try connection again with the new selected_server

#         # Connected: start piping and monitor for mid-stream backend failure.
#         client_to_backend = asyncio.create_task(
#             pipe_data(client_reader, backend_writer, client_addr, "Client -> Backend")
#         )
#         backend_to_client = asyncio.create_task(
#             pipe_data(backend_reader, client_writer, (backend_host, backend_port), "Backend -> Client")
#         )

#         done, pending = await asyncio.wait(
#             {client_to_backend, backend_to_client},
#             return_when=asyncio.FIRST_COMPLETED,
#         )

#         # If client side finished first, break and close everything.
#         if client_to_backend in done:
#             backend_to_client.cancel()
#             await asyncio.gather(backend_to_client, return_exceptions=True)
#             break

#         # Backend finished first: attempt mid-stream failover.
#         client_to_backend.cancel()
#         await asyncio.gather(client_to_backend, return_exceptions=True)
#         print(f"LB: Backend {backend_host}:{backend_port} closed mid-stream for {client_addr}; attempting failover.")

#         # Clean up current backend and decrement count.
#         if backend_writer:
#             backend_writer.close()
#             await backend_writer.wait_closed()
        
#         async with active_servers_lock:
#             if connected_backend and connected_backend in CONNECTION_COUNT and CONNECTION_COUNT[connected_backend] > 0:
#                 CONNECTION_COUNT[connected_backend] -= 1
#         connected_backend = None
#         backend_reader, backend_writer = None, None
        
#         # Reset selected_algo to trigger proper selection next time
#         selected_algo = None 

#         tried_servers.add(selected_server)
#         selection = await select_backend(tried_servers)
#         if not selection:
#             print("LB: No alternative backend available immediately. Waiting for backend to recover...")
#             selection = await wait_for_backend(WAIT_FOR_BACKEND_TIMEOUT, tried_servers)
#         if not selection:
#             print("LB: Timeout waiting for backend during failover. Closing client.")
#             selected_server = None
#         else:
#             selected_server, selected_algo = selection

#     # Final cleanup and count decrement for the last backend used.
#     final_backend = connected_backend
#     if backend_writer:
#         backend_writer.close()
#         await backend_writer.wait_closed()
        
#     async with active_servers_lock:
#         if final_backend and final_backend in CONNECTION_COUNT and CONNECTION_COUNT[final_backend] > 0:
#             CONNECTION_COUNT[final_backend] -= 1

#     if client_writer:
#         client_writer.close()
#         await client_writer.wait_closed()

#     # --- PHASE 3: Clean up SESSION_MAP ---
#     # !!! PERSISTENCE CHANGE: REMOVED SESSION_MAP.pop(client_key, None) !!!
#     # The entry is deliberately kept so the client returns to the last server on reconnect.
    
#     print(f"LB: Closed connection for {client_addr}. Sticky session retained.")

# async def main(host, port, algorithm):
#     """
#     Starts the Load Balancer server.
#     """
#     global SCHEDULING_ALGORITHM
#     SCHEDULING_ALGORITHM = algorithm

#     print(f"LB: Initializing with algorithm={SCHEDULING_ALGORITHM}")
#     await refresh_active_servers()

#     server = await asyncio.start_server(handle_client, host, port)

#     addr = server.sockets[0].getsockname()
#     print(f'Load Balancer listening on {addr}')

#     # Start health checks in the background
#     health_check_task = asyncio.create_task(perform_health_checks())

#     async with server:
#         await server.serve_forever()


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="AsyncIO Load Balancer")
#     parser.add_argument("--host", default="0.0.0.0", help="Host to bind the load balancer to (use 0.0.0.0 for LAN)")
#     parser.add_argument("--port", type=int, default=8080, help="Port for the load balancer to listen on")
#     parser.add_argument(
#         "--algorithm",
#         choices=["auto", "round-robin", "least-connections"],
#         default="auto",
#         help="Scheduling algorithm to use (auto picks round-robin when counts are even, least-connections when imbalanced)"
#     )

#     args = parser.parse_args()

#     try:
#         asyncio.run(main(args.host, args.port, args.algorithm))
#     except KeyboardInterrupt:
#         print("\nShutting down Load Balancer...")























import argparse
import asyncio

# ============================================================ 
# PHASE 1: CORE DATA STRUCTURES
# ============================================================ 

# Use 127.0.0.1 for local testing.
# In a real LAN environment, replace with private IPs like:
# ('192.168.1.11', 8888), ('192.168.1.12', 8888)
SERVER_POOL = [
    ('10.249.57.62', 8881),
    ('10.249.57.17', 8882),
]

HEALTH_CHECK_INTERVAL = 5
WAIT_FOR_BACKEND_TIMEOUT = 30

# ============================================================ 
# PHASE 2 & 3: PLACEHOLDER DATA STRUCTURES
# ============================================================ 

ACTIVE_SERVERS = [] 
active_servers_lock = asyncio.Lock()

CONNECTION_COUNT = {server: 0 for server in SERVER_POOL}

# SESSION_MAP key uses only the '<client_ip>' for robust persistence
SESSION_MAP = {}
session_map_lock = asyncio.Lock()

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
    except Exception as e:
        print(f"LB: Error checking health of {server}: {e}")
        return False


async def refresh_active_servers():
    """
    Run a full health check pass and update ACTIVE_SERVERS.
    """
    global ACTIVE_SERVERS
    healthy_servers = []
    for server in SERVER_POOL:
        is_healthy = await check_server_health(server)
        if is_healthy:
            healthy_servers.append(server)
            print(f"LB: Server {server} is healthy.")
        else:
            print(f"LB: Server {server} is unhealthy.")
        if not is_healthy:
            CONNECTION_COUNT[server] = 0
        else:
            CONNECTION_COUNT.setdefault(server, 0)

    async with active_servers_lock:
        ACTIVE_SERVERS = healthy_servers
        print(f"LB: Active servers updated: {ACTIVE_SERVERS}")


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
            writer.write(data)
            await writer.drain()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in pipe_data ({direction} from {peer_name}): {e}")


async def select_backend(exclude=None):
    """
    Select a backend server based on the configured scheduling algorithm.
    exclude: set of servers already tried for this client (for failover).
    Returns (server, algo) or None.
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
        else:
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


def get_client_key(client_addr):
    """
    Generates a unique key for the client for the SESSION_MAP, 
    using ONLY the IP address (client_addr[0]). This ensures that 
    a client reconnecting from the same IP is treated as 'old'.
    """
    # IP address only for robust sticky sessions across disconnects
    return client_addr[0]


async def handle_client(client_reader, client_writer):
    """
    Handles a new client connection by forwarding it to a backend server, 
    with support for Persistent Sticky Sessions.
    """
    client_addr = client_writer.get_extra_info('peername')
    client_key = get_client_key(client_addr)
    print(f"LB: Accepted connection from {client_addr}")
    print(f"LB: DEBUG - client_key={client_key}, SESSION_MAP={SESSION_MAP}")

    tried_servers = set()
    selected_server = None
    selected_algo = None
    
    # 1. Check for Sticky Session (Priority Check)
    async with session_map_lock:
        sticky_target = SESSION_MAP.get(client_key)
        
    if sticky_target:
        async with active_servers_lock:
            if sticky_target in ACTIVE_SERVERS:
                selected_server = sticky_target
                selected_algo = "sticky"
                # This path treats it as an "old client" and bypasses the scheduler
                print(f"LB: Sticky session found for {client_key} -> {selected_server}")
            else:
                # Sticky server is unhealthy (failover)
                print(f"LB: Sticky server {sticky_target} is unhealthy. Falling back to scheduling.")
                tried_servers.add(sticky_target)

    # 2. If no valid sticky session (new client or sticky failover), use scheduler
    if not selected_server:
        # This path uses Round-Robin/Least-Connections
        selection = await select_backend(tried_servers)

        if not selection:
            print("LB: No active backend servers available. Waiting for a backend to recover...")
            selection = await wait_for_backend(WAIT_FOR_BACKEND_TIMEOUT, tried_servers)
            if not selection:
                print("LB: Timeout waiting for backend. Closing client.")
                client_writer.close()
                await client_writer.wait_closed()
                async with session_map_lock:
                    SESSION_MAP.pop(client_key, None)
                return
        
        selected_server, selected_algo = selection

    backend_host, backend_port = None, None
    backend_reader, backend_writer = None, None
    connected_backend = None

    while selected_server:
        backend_host, backend_port = selected_server
        print(f"LB: Forwarding {client_addr} to {backend_host}:{backend_port} ({selected_algo})")
        
        # Update the sticky session map upon selection (establishes new stickiness)
        async with session_map_lock:
            SESSION_MAP[client_key] = selected_server
            print(f"LB: Set persistent sticky session for {client_key} -> {selected_server}")

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
                selection = await wait_for_backend(WAIT_FOR_BACKEND_TIMEOUT, tried_servers)
            
            if not selection:
                print("LB: Timeout waiting for backend. Closing client.")
                break
            
            selected_server, selected_algo = selection
            continue

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

        if client_to_backend in done:
            backend_to_client.cancel()
            await asyncio.gather(backend_to_client, return_exceptions=True)
            break

        client_to_backend.cancel()
        await asyncio.gather(client_to_backend, return_exceptions=True)
        print(f"LB: Backend {backend_host}:{backend_port} closed mid-stream for {client_addr}; attempting failover.")

        if backend_writer:
            backend_writer.close()
            await backend_writer.wait_closed()
        
        async with active_servers_lock:
            if connected_backend and connected_backend in CONNECTION_COUNT and CONNECTION_COUNT[connected_backend] > 0:
                CONNECTION_COUNT[connected_backend] -= 1
        connected_backend = None
        backend_reader, backend_writer = None, None
        
        selected_algo = None 

        tried_servers.add(selected_server)
        selection = await select_backend(tried_servers)
        if not selection:
            print("LB: No alternative backend available immediately. Waiting for backend to recover...")
            selection = await wait_for_backend(WAIT_FOR_BACKEND_TIMEOUT, tried_servers)
        if not selection:
            print("LB: Timeout waiting for backend during failover. Closing client.")
            selected_server = None
        else:
            selected_server, selected_algo = selection

    final_backend = connected_backend
    if backend_writer:
        backend_writer.close()
        await backend_writer.wait_closed()
        
    async with active_servers_lock:
        if final_backend and final_backend in CONNECTION_COUNT and CONNECTION_COUNT[final_backend] > 0:
            CONNECTION_COUNT[final_backend] -= 1

    if client_writer:
        client_writer.close()
        await client_writer.wait_closed()

    print(f"LB: Closed connection for {client_addr}. Sticky session retained.")


async def main(host, port, algorithm):
    """
    Starts the Load Balancer server.
    """
    global SCHEDULING_ALGORITHM
    SCHEDULING_ALGORITHM = algorithm

    print(f"LB: Initializing with algorithm={SCHEDULING_ALGORITHM}")
    await refresh_active_servers()

    server = await asyncio.start_server(handle_client, host, port)

    addr = server.sockets[0].getsockname()
    print(f'Load Balancer listening on {addr}')

    health_check_task = asyncio.create_task(perform_health_checks())

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AsyncIO Load Balancer")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the load balancer to")
    parser.add_argument("--port", type=int, default=8080, help="Port for the load balancer to listen on")
    parser.add_argument(
        "--algorithm",
        choices=["auto", "round-robin", "least-connections"],
        default="auto",
        help="Scheduling algorithm to use"
    )

    args = parser.parse_args()

    try:
        asyncio.run(main(args.host, args.port, args.algorithm))
    except KeyboardInterrupt:
        print("\nShutting down Load Balancer...")