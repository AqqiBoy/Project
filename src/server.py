import argparse
import asyncio
import json
import time

async def handle_connection(reader, writer, server_name, stats):
    """
    Handles a single client connection.
    Responds with the server's name.
    """
    addr = writer.get_extra_info('peername')
    print(f"[{server_name}] Accepted connection from {addr}")
    stats["active_connections"] += 1

    try:
        while True:
            # Read client message
            data = await reader.read(100) # Read up to 100 bytes
            if not data: # Client disconnected
                break
            
            message = data.decode().strip()
            print(f"[{server_name}] Received message: {message!r} from {addr}")
            stats["message_count"] += 1

            # Respond with a unique identifier
            response = f"Hello from {server_name}\n"
            print(f"[{server_name}] Sending: {response!r}")
            writer.write(response.encode())
            await writer.drain()

    except ConnectionResetError:
        print(f"[{server_name}] Client {addr} disconnected unexpectedly.")
    except Exception as e:
        print(f"[{server_name}] Error with client {addr}: {e}")
    finally:
        print(f"[{server_name}] Closing connection with {addr}")
        writer.close()
        await writer.wait_closed()
        stats["active_connections"] = max(stats["active_connections"] - 1, 0)

async def send_http_response(writer, status, reason, body, content_type):
    headers = [
        f"HTTP/1.1 {status} {reason}",
        f"Content-Length: {len(body)}",
        f"Content-Type: {content_type}",
        "Cache-Control: no-store",
        "Connection: close",
        "",
        "",
    ]
    writer.write("\r\n".join(headers).encode("utf-8") + body)
    await writer.drain()
    writer.close()
    await writer.wait_closed()

async def handle_http(reader, writer, server_name, stats):
    try:
        data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2.0)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError):
        writer.close()
        await writer.wait_closed()
        return
    except asyncio.LimitOverrunError:
        await send_http_response(
            writer,
            431,
            "Request Header Fields Too Large",
            b"Request header too large.",
            "text/plain; charset=utf-8",
        )
        return

    try:
        request_line = data.split(b"\r\n", 1)[0].decode("iso-8859-1")
        method, target, _version = request_line.split()
    except ValueError:
        await send_http_response(
            writer, 400, "Bad Request", b"Invalid request line.", "text/plain; charset=utf-8"
        )
        return

    if method.upper() != "GET":
        await send_http_response(
            writer, 405, "Method Not Allowed", b"Only GET is supported.", "text/plain; charset=utf-8"
        )
        return

    path = target.split("?", 1)[0]
    if path != "/status":
        await send_http_response(writer, 404, "Not Found", b"Not Found.", "text/plain; charset=utf-8")
        return

    uptime_seconds = int(time.monotonic() - stats["start_time"])
    payload = {
        "name": server_name,
        "uptime_seconds": uptime_seconds,
        "message_count": stats["message_count"],
        "active_connections": stats["active_connections"],
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    await send_http_response(writer, 200, "OK", body, "application/json; charset=utf-8")

async def main(name, host, port, http_host, http_port):
    """
    Starts the backend TCP server.
    """
    stats = {
        "start_time": time.monotonic(),
        "message_count": 0,
        "active_connections": 0,
    }
    # Pass server_name directly to the handler
    async def server_handler(reader, writer):
        await handle_connection(reader, writer, name, stats)

    server = await asyncio.start_server(
        server_handler, host, port)

    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    print(f"Backend server '{name}' listening on {addrs}")

    http_server = None
    if http_port:
        async def http_handler(reader, writer):
            await handle_http(reader, writer, name, stats)

        http_server = await asyncio.start_server(http_handler, http_host, http_port)
        http_addrs = ', '.join(str(sock.getsockname()) for sock in http_server.sockets)
        print(f"Status server '{name}' listening on {http_addrs}")

    server_task = asyncio.create_task(server.serve_forever())
    http_task = asyncio.create_task(http_server.serve_forever()) if http_server else None
    try:
        tasks = [server_task]
        if http_task:
            tasks.append(http_task)
        await asyncio.gather(*tasks)
    finally:
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)
        server.close()
        await server.wait_closed()
        if http_task:
            http_task.cancel()
            await asyncio.gather(http_task, return_exceptions=True)
        if http_server:
            http_server.close()
            await http_server.wait_closed()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AsyncIO Backend Server")
    parser.add_argument("--name", required=True, help="Name of the server (e.g., B1)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (use 0.0.0.0 for LAN)")
    parser.add_argument("--port", type=int, required=True, help="Port to listen on")
    parser.add_argument(
        "--http-host",
        default="0.0.0.0",
        help="Host to bind the status HTTP server to",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=None,
        help="Status HTTP port (default: backend port + offset; 0 to disable)",
    )
    parser.add_argument(
        "--http-port-offset",
        type=int,
        default=1000,
        help="Offset to add to backend port for status HTTP port",
    )
    
    args = parser.parse_args()
    if args.http_port is None:
        args.http_port = args.port + args.http_port_offset
    if args.http_port == 0:
        args.http_port = None

    try:
        asyncio.run(main(args.name, args.host, args.port, args.http_host, args.http_port))
    except KeyboardInterrupt:
        print(f"\nShutting down server '{args.name}'...")
