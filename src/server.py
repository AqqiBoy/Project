
import asyncio
import argparse

async def handle_connection(reader, writer, server_name):
    """
    Handles a single client connection.
    Responds with the server's name.
    """
    addr = writer.get_extra_info('peername')
    print(f"[{server_name}] Received connection from {addr}")

    # Read client message (optional, but good practice)
    data = await reader.read(100)
    message = data.decode()
    print(f"[{server_name}] Received message: {message!r} from {addr}")

    # Respond with a unique identifier
    response = f"Hello from {server_name}\n"
    print(f"[{server_name}] Sending: {response!r}")
    writer.write(response.encode())
    await writer.drain()

    print(f"[{server_name}] Closing connection with {addr}")
    writer.close()
    await writer.wait_closed()

async def main(name, host, port):
    """
    Starts the backend TCP server.
    """
    loop = asyncio.get_running_loop()
    
    # Pass server_name directly to the handler
    async def server_handler(reader, writer):
        await handle_connection(reader, writer, name)

    server = await asyncio.start_server(
        server_handler, host, port)

    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    print(f"Backend server '{name}' listening on {addrs}")

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AsyncIO Backend Server")
    parser.add_argument("--name", required=True, help="Name of the server (e.g., B1)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (use 0.0.0.0 for LAN)")
    parser.add_argument("--port", type=int, required=True, help="Port to listen on")
    
    args = parser.parse_args()

    try:
        asyncio.run(main(args.name, args.host, args.port))
    except KeyboardInterrupt:
        print(f"\nShutting down server '{args.name}'...")
