
import asyncio
import argparse

async def tcp_client(host, port, message):
    """
    Connects to the specified host and port, sends a message,
    and prints the response.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        
        print(f"Connecting to {host}:{port}...")
        
        print(f"Sending: {message!r}")
        writer.write(message.encode())
        await writer.drain()

        data = await reader.read(100)
        response = data.decode().strip()
        print(f"Received: {response!r}")

        print("Closing the connection.")
        writer.close()
        await writer.wait_closed()

    except ConnectionRefusedError:
        print(f"Connection failed: Connection refused at {host}:{port}.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AsyncIO TCP Client")
    parser.add_argument("--host", required=True, help="Host to connect to (Load Balancer IP)")
    parser.add_argument("--port", type=int, required=True, help="Port to connect to")
    parser.add_argument("--message", default="Hello from Client", help="Message to send")

    args = parser.parse_args()

    asyncio.run(tcp_client(args.host, args.port, args.message))
