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

# Use itertools.cycle for simple round-robin
server_iterator = cycle(SERVER_POOL)


# ============================================================ 
# PHASE 2 & 3: PLACEHOLDER DATA STRUCTURES
# ============================================================ 

# PHASE 2: ACTIVE_SERVERS will be managed by health checks
# Example: ACTIVE_SERVERS = [('127.0.0.1', 8881)]
ACTIVE_SERVERS = [] 

# PHASE 2: CONNECTION_COUNT for least-connections scheduling
# Example: CONNECTION_COUNT = {('127.0.0.1', 8881): 5}
CONNECTION_COUNT = {}

# PHASE 3: SESSION_MAP for sticky sessions
# Example: SESSION_MAP = {'<client_ip>:<client_port>': '<backend_addr>'}
SESSION_MAP = {}


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
    finally:
        writer.close()
        await writer.wait_closed()


async def handle_client(client_reader, client_writer):
    """
    Handles a new client connection by forwarding it to a backend server.
    """
    client_addr = client_writer.get_extra_info('peername')
    print(f"LB: Accepted connection from {client_addr}")

    # ============================================================ 
    # PHASE 1: Round-Robin Scheduling
    # ============================================================ 
    backend_host, backend_port = next(server_iterator)
    print(f"LB: Forwarding {client_addr} to {backend_host}:{backend_port} (Round-Robin)")

    # ============================================================ 
    # PHASE 2 & 3: Future Scheduling Logic (Placeholders)
    # ============================================================ 
    # PHASE 2: Implement Least-Connections logic here
    # PHASE 2: Use a list of active servers from health checks
    # PHASE 3: Implement Sticky Session logic here
    
    backend_reader, backend_writer = None, None
    try:
        # Establish connection to the selected backend server
        backend_reader, backend_writer = await asyncio.open_connection(backend_host, backend_port)
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

    # Create tasks for bidirectional data piping
    client_to_backend = asyncio.create_task(
        pipe_data(client_reader, backend_writer, client_addr, "Client -> Backend")
    )
    backend_to_client = asyncio.create_task(
        pipe_data(backend_reader, client_writer, (backend_host, backend_port), "Backend -> Client")
    )

    # Wait for either task to complete (which means one side closed)
    await asyncio.wait([client_to_backend, backend_to_client], return_when=asyncio.FIRST_COMPLETED)

    # Clean up by cancelling the other task
    client_to_backend.cancel()
    backend_to_client.cancel()
    
    print(f"LB: Closed connection for {client_addr}")


async def main(host, port):
    """
    Starts the Load Balancer server.
    """
    server = await asyncio.start_server(handle_client, host, port)

    addr = server.sockets[0].getsockname()
    print(f'Load Balancer listening on {addr}')

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    LB_HOST = "0.0.0.0"  # Listen on all interfaces for LAN access
    LB_PORT = 8080       # The single public-facing port

    try:
        asyncio.run(main(LB_HOST, LB_PORT))
    except KeyboardInterrupt:
        print("\nShutting down Load Balancer...")
