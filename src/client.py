import asyncio
import argparse
import sys

async def tcp_client(host, port):
    """
    Connects to the specified host and port, allows continuous real-time input,
    sends messages, and prints responses.
    """
    reader, writer = None, None # Initialize writer outside try for finally block access
    try:
        reader, writer = await asyncio.open_connection(host, port)
        
        print(f"Connecting to {host}:{port}...")
        print("Type your messages and press Enter. Press Ctrl+C or Ctrl+Z (then Enter) to exit.")

        while True:
            try:
                # Get real-time input from the user
                message = await asyncio.to_thread(input, "You: ")
                if not message:
                    continue # Don't send empty messages

                print(f"Sending: {message!r}")
                writer.write(message.encode() + b'\n') # Add newline for server to read a full line
                await writer.drain()

                data = await reader.read(100) # Read up to 100 bytes
                if not data:
                    print("Server closed the connection.")
                    break
                response = data.decode().strip()
                print(f"Received: {response!r}")

            except EOFError:
                print("\nEOF received. Closing client.")
                break
            except ConnectionResetError:
                print("Connection reset by peer. Server might have closed unexpectedly.")
                break
            except Exception as e:
                print(f"An error occurred during communication: {e}")
                break

    except ConnectionRefusedError:
        print(f"Connection failed: Connection refused at {host}:{port}.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if writer:
            print("Closing the connection.")
            writer.close()
            await writer.wait_closed()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AsyncIO Interactive TCP Client")
    parser.add_argument("--host", required=True, help="Host to connect to (Load Balancer IP)")
    parser.add_argument("--port", type=int, required=True, help="Port to connect to")
    
    args = parser.parse_args()

    try:
        asyncio.run(tcp_client(args.host, args.port))
    except KeyboardInterrupt:
        print("\nClient interrupted. Shutting down.")