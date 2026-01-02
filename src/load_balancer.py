import argparse
import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, urlsplit

Backend = Tuple[str, int]


def parse_backends(value: str) -> List[Backend]:
    """
    Parse a comma-separated list of backends of the form 'host:port'.
    Example: '127.0.0.1:8881,127.0.0.1:8882'
    """
    backends: List[Backend] = []
    raw_items = [item.strip() for item in value.split(",") if item.strip()]
    if not raw_items:
        raise argparse.ArgumentTypeError("backends must contain at least one host:port entry")

    for item in raw_items:
        if ":" not in item:
            raise argparse.ArgumentTypeError(f"invalid backend {item!r}; expected host:port")
        host, port_str = item.rsplit(":", 1)
        host = host.strip()
        if not host:
            raise argparse.ArgumentTypeError(f"invalid backend {item!r}; empty host")
        try:
            port = int(port_str)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid backend {item!r}; port must be an integer") from exc
        if not (1 <= port <= 65535):
            raise argparse.ArgumentTypeError(f"invalid backend {item!r}; port out of range")
        backends.append((host, port))

    return backends


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@dataclass(frozen=True)
class LoadBalancerConfig:
    host: str
    port: int
    backends: Sequence[Backend]
    algorithm: str
    health_check_interval: float
    wait_for_backend_timeout: float
    health_check_timeout: float
    sticky_key: str
    http_host: str
    http_port: int
    backend_status_port_offset: int
    web_client_idle_timeout: float
    web_client_read_timeout: float


@dataclass
class WebClientSession:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    created_at: float
    last_activity: float
    lock: asyncio.Lock


class LoadBalancer:
    def __init__(self, config: LoadBalancerConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger

        self._static_dir = Path(__file__).resolve().parent / "web"
        self._start_time = time.monotonic()
        self._events: Deque[Dict[str, str]] = deque(maxlen=200)
        self._events_lock = asyncio.Lock()
        self._backend_details: Dict[Backend, Dict[str, object]] = {}
        self._backend_details_lock = asyncio.Lock()
        self._web_clients: Dict[str, WebClientSession] = {}
        self._web_clients_lock = asyncio.Lock()

        self._server_pool: List[Backend] = list(config.backends)
        self._active_servers: List[Backend] = []
        self._active_servers_lock = asyncio.Lock()

        self._connection_count: Dict[Backend, int] = {server: 0 for server in self._server_pool}

        self._session_map: Dict[str, Backend] = {}
        self._session_map_lock = asyncio.Lock()

        self._round_robin_index = 0

    async def _record_event(self, level: str, message: str) -> None:
        event = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "level": level,
            "message": message,
        }
        async with self._events_lock:
            self._events.append(event)

    async def check_server_health(self, server: Backend) -> bool:
        host, port = server
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self._config.health_check_timeout,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError):
            return False
        except Exception:
            self._logger.exception("Health check failed for %s:%s", host, port)
            return False

    async def refresh_active_servers(self) -> None:
        results = await asyncio.gather(
            *(self.check_server_health(server) for server in self._server_pool),
            return_exceptions=False,
        )

        healthy: List[Backend] = []
        for server, is_healthy in zip(self._server_pool, results):
            if is_healthy:
                healthy.append(server)
                self._connection_count.setdefault(server, 0)
            else:
                self._connection_count[server] = 0

        async with self._active_servers_lock:
            previous = list(self._active_servers)
            self._active_servers = healthy

        self._logger.info("Active backends: %s", healthy)
        if previous != healthy:
            await self._record_event("INFO", f"Active backends updated: {healthy}")
        await self.refresh_backend_details()

    async def _fetch_backend_status(self, server: Backend) -> Optional[Dict[str, object]]:
        host, port = server
        status_port = port + self._config.backend_status_port_offset
        request = (
            f"GET /status HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8")

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, status_port),
                timeout=self._config.health_check_timeout,
            )
            writer.write(request)
            await writer.drain()
            header_data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=self._config.health_check_timeout)
            header_text = header_data.decode("iso-8859-1")
            lines = header_text.split("\r\n")
            status_line = lines[0]
            if "200" not in status_line:
                writer.close()
                await writer.wait_closed()
                return None

            headers = {}
            for line in lines[1:]:
                if not line:
                    continue
                key, _, value = line.partition(":")
                headers[key.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", "0"))
            body = await asyncio.wait_for(reader.readexactly(content_length), timeout=self._config.health_check_timeout)
            writer.close()
            await writer.wait_closed()
            return json.loads(body.decode("utf-8"))
        except (asyncio.TimeoutError, ConnectionRefusedError, json.JSONDecodeError, ValueError):
            return None
        except Exception:
            self._logger.debug("Status fetch failed for %s:%s", host, status_port, exc_info=True)
            return None

    async def refresh_backend_details(self) -> None:
        results = await asyncio.gather(
            *(self._fetch_backend_status(server) for server in self._server_pool),
            return_exceptions=False,
        )

        details: Dict[Backend, Dict[str, object]] = {}
        for server, payload in zip(self._server_pool, results):
            if payload:
                details[server] = payload

        async with self._backend_details_lock:
            self._backend_details = details

    async def perform_health_checks(self) -> None:
        while True:
            self._logger.debug("Running health checks")
            await self.refresh_active_servers()
            await asyncio.sleep(self._config.health_check_interval)

    @staticmethod
    async def pipe_data(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while not reader.at_eof():
                data = await reader.read(2048)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.getLogger("lb").exception("Pipe failed")

    def _choose_algorithm(self, candidates: Sequence[Backend]) -> str:
        if self._config.algorithm != "auto":
            return self._config.algorithm
        if len(candidates) <= 1:
            return "round-robin"
        counts = [self._connection_count.get(server, 0) for server in candidates]
        return "round-robin" if len(set(counts)) == 1 else "least-connections"

    async def select_backend(self, exclude: Optional[Set[Backend]] = None) -> Optional[Tuple[Backend, str]]:
        exclude = exclude or set()

        async with self._active_servers_lock:
            candidates = [server for server in self._active_servers if server not in exclude]
            if not candidates:
                return None

            algo = self._choose_algorithm(candidates)

            if algo == "least-connections":
                min_connections = min(self._connection_count.get(server, 0) for server in candidates)
                least_connected = [s for s in candidates if self._connection_count.get(s, 0) == min_connections]
                chosen = least_connected[self._round_robin_index % len(least_connected)]
            else:
                chosen = candidates[self._round_robin_index % len(candidates)]

            self._round_robin_index += 1
            return chosen, algo

    async def wait_for_backend(
        self, timeout: float, exclude: Optional[Set[Backend]] = None
    ) -> Optional[Tuple[Backend, str]]:
        start = asyncio.get_running_loop().time()
        while True:
            selection = await self.select_backend(exclude)
            if selection:
                return selection
            elapsed = asyncio.get_running_loop().time() - start
            if elapsed >= timeout:
                return None
            await asyncio.sleep(min(self._config.health_check_interval, timeout - elapsed))

    def _client_key(self, client_addr: object) -> str:
        if not isinstance(client_addr, tuple) or len(client_addr) < 2:
            return "unknown"

        client_ip = str(client_addr[0])
        client_port = str(client_addr[1])

        if self._config.sticky_key == "ip-port":
            return f"{client_ip}:{client_port}"
        return client_ip

    async def handle_client(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        client_addr = client_writer.get_extra_info("peername")
        client_key = self._client_key(client_addr)
        self._logger.info("Accepted client %s (key=%s)", client_addr, client_key)
        await self._record_event("INFO", f"Client connected: {client_addr}")

        tried_servers: Set[Backend] = set()
        selected_server: Optional[Backend] = None
        selected_algo: Optional[str] = None

        async with self._session_map_lock:
            sticky_target = self._session_map.get(client_key)

        if sticky_target:
            async with self._active_servers_lock:
                if sticky_target in self._active_servers:
                    selected_server = sticky_target
                    selected_algo = "sticky"
                    self._logger.info("Sticky route %s -> %s", client_key, selected_server)
                    await self._record_event("INFO", f"Sticky route: {client_key} -> {selected_server}")
                else:
                    self._logger.warning(
                        "Sticky backend %s is not active; falling back to scheduler", sticky_target
                    )
                    tried_servers.add(sticky_target)

        if not selected_server:
            selection = await self.select_backend(tried_servers)
            if not selection:
                self._logger.warning("No active backends; waiting up to %ss", self._config.wait_for_backend_timeout)
                selection = await self.wait_for_backend(self._config.wait_for_backend_timeout, tried_servers)
                if not selection:
                    self._logger.error("No backend recovered before timeout; closing client %s", client_addr)
                    await self._record_event("ERROR", f"No backend available for client {client_addr}")
                    client_writer.close()
                    await client_writer.wait_closed()
                    async with self._session_map_lock:
                        self._session_map.pop(client_key, None)
                    return

            selected_server, selected_algo = selection

        backend_reader: Optional[asyncio.StreamReader] = None
        backend_writer: Optional[asyncio.StreamWriter] = None
        connected_backend: Optional[Backend] = None

        while selected_server:
            backend_host, backend_port = selected_server
            self._logger.info(
                "Routing client %s -> %s:%s (%s)", client_addr, backend_host, backend_port, selected_algo
            )
            await self._record_event(
                "INFO",
                f"Routing {client_addr} -> {backend_host}:{backend_port} ({selected_algo})",
            )

            async with self._session_map_lock:
                self._session_map[client_key] = selected_server

            try:
                backend_reader, backend_writer = await asyncio.open_connection(backend_host, backend_port)
                connected_backend = (backend_host, backend_port)
                async with self._active_servers_lock:
                    self._connection_count[connected_backend] = self._connection_count.get(connected_backend, 0) + 1
                    current = self._connection_count[connected_backend]
                self._logger.debug("Backend %s:%s connections=%s", backend_host, backend_port, current)
            except ConnectionRefusedError:
                self._logger.warning("Backend refused connection %s:%s; trying next", backend_host, backend_port)
                await self._record_event("WARNING", f"Backend refused: {backend_host}:{backend_port}")
                backend_reader, backend_writer = None, None
            except Exception:
                self._logger.exception("Failed connecting to backend %s:%s; trying next", backend_host, backend_port)
                await self._record_event("ERROR", f"Backend connect failed: {backend_host}:{backend_port}")
                backend_reader, backend_writer = None, None

            if backend_reader is None or backend_writer is None:
                tried_servers.add(selected_server)
                selection = await self.select_backend(tried_servers)
                if not selection:
                    self._logger.warning(
                        "No alternative backend available; waiting up to %ss", self._config.wait_for_backend_timeout
                    )
                    selection = await self.wait_for_backend(self._config.wait_for_backend_timeout, tried_servers)
                if not selection:
                    self._logger.error("Timeout waiting for backend; closing client %s", client_addr)
                    await self._record_event("ERROR", f"Backend timeout for client {client_addr}")
                    break
                selected_server, selected_algo = selection
                continue

            client_to_backend = asyncio.create_task(self.pipe_data(client_reader, backend_writer))
            backend_to_client = asyncio.create_task(self.pipe_data(backend_reader, client_writer))

            done, _pending = await asyncio.wait(
                {client_to_backend, backend_to_client},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if client_to_backend in done:
                backend_to_client.cancel()
                await asyncio.gather(backend_to_client, return_exceptions=True)
                break

            client_to_backend.cancel()
            await asyncio.gather(client_to_backend, return_exceptions=True)
            self._logger.warning(
                "Backend %s:%s closed for client %s; attempting failover", backend_host, backend_port, client_addr
            )
            await self._record_event(
                "WARNING",
                f"Backend closed {backend_host}:{backend_port}; failover for client {client_addr}",
            )

            if backend_writer:
                backend_writer.close()
                await backend_writer.wait_closed()

            async with self._active_servers_lock:
                if connected_backend and self._connection_count.get(connected_backend, 0) > 0:
                    self._connection_count[connected_backend] -= 1

            connected_backend = None
            backend_reader, backend_writer = None, None

            tried_servers.add(selected_server)
            selection = await self.select_backend(tried_servers)
            if not selection:
                self._logger.warning(
                    "No alternative backend immediately available; waiting up to %ss",
                    self._config.wait_for_backend_timeout,
                )
                selection = await self.wait_for_backend(self._config.wait_for_backend_timeout, tried_servers)
            if not selection:
                self._logger.error("Timeout waiting for backend during failover; closing client %s", client_addr)
                await self._record_event("ERROR", f"Failover timeout for client {client_addr}")
                selected_server = None
            else:
                selected_server, selected_algo = selection

        final_backend = connected_backend
        if backend_writer:
            backend_writer.close()
            await backend_writer.wait_closed()

        async with self._active_servers_lock:
            if final_backend and self._connection_count.get(final_backend, 0) > 0:
                self._connection_count[final_backend] -= 1

        client_writer.close()
        await client_writer.wait_closed()
        self._logger.info("Closed client %s (sticky session retained for key=%s)", client_addr, client_key)
        await self._record_event("INFO", f"Client closed: {client_addr}")

    async def _status_payload(self) -> Dict[str, object]:
        async with self._active_servers_lock:
            active_servers = list(self._active_servers)
        async with self._session_map_lock:
            session_count = len(self._session_map)
        async with self._backend_details_lock:
            details = dict(self._backend_details)
        async with self._events_lock:
            events = list(self._events)

        active_set = set(active_servers)
        backends = []
        for host, port in self._server_pool:
            backends.append(
                {
                    "host": host,
                    "port": port,
                    "active": (host, port) in active_set,
                    "connections": self._connection_count.get((host, port), 0),
                    "details": details.get((host, port)),
                }
            )

        return {
            "algorithm": self._config.algorithm,
            "sticky_key": self._config.sticky_key,
            "total_backends": len(self._server_pool),
            "active_backends": len(active_servers),
            "backends": backends,
            "session_count": session_count,
            "uptime_seconds": int(time.monotonic() - self._start_time),
            "events": events,
        }

    def _lb_connect_host(self) -> str:
        if self._config.host in ("0.0.0.0", "::", ""):
            return "127.0.0.1"
        return self._config.host

    async def _close_web_client_session(self, client_id: str, reason: str) -> None:
        async with self._web_clients_lock:
            session = self._web_clients.pop(client_id, None)
        if not session:
            return
        if not session.writer.is_closing():
            session.writer.close()
            await session.writer.wait_closed()
        await self._record_event("INFO", f"Web client {client_id} disconnected ({reason})")

    async def _get_web_client_session(self, client_id: str) -> Optional[WebClientSession]:
        async with self._web_clients_lock:
            session = self._web_clients.get(client_id)
        if not session:
            return None
        if session.writer.is_closing() or session.reader.at_eof():
            await self._close_web_client_session(client_id, "connection closed")
            return None
        return session

    async def _open_web_client_session(self, client_id: str) -> Tuple[bool, str]:
        existing = await self._get_web_client_session(client_id)
        if existing:
            existing.last_activity = time.monotonic()
            return True, "Already connected."

        host = self._lb_connect_host()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, self._config.port),
                timeout=self._config.health_check_timeout,
            )
        except asyncio.TimeoutError:
            return False, "Timed out connecting to the load balancer."
        except Exception as exc:
            return False, f"Failed to connect to the load balancer: {exc}"

        now = time.monotonic()
        session = WebClientSession(
            reader=reader,
            writer=writer,
            created_at=now,
            last_activity=now,
            lock=asyncio.Lock(),
        )
        async with self._web_clients_lock:
            if client_id in self._web_clients:
                session.writer.close()
                await session.writer.wait_closed()
                return True, "Already connected."
            self._web_clients[client_id] = session
        await self._record_event("INFO", f"Web client {client_id} connected")
        return True, "Connected."

    async def _send_via_web_client(self, client_id: str, message: str) -> Tuple[bool, str, int]:
        session = await self._get_web_client_session(client_id)
        if not session:
            return False, "Web client is not connected.", 0

        start = time.monotonic()
        async with session.lock:
            if session.writer.is_closing() or session.reader.at_eof():
                await self._close_web_client_session(client_id, "connection closed")
                return False, "Web client connection closed.", 0

            session.last_activity = time.monotonic()
            try:
                session.writer.write(message.encode("utf-8") + b"\n")
                await session.writer.drain()
                data = await asyncio.wait_for(
                    session.reader.readuntil(b"\n"),
                    timeout=self._config.web_client_read_timeout,
                )
            except asyncio.LimitOverrunError:
                data = await asyncio.wait_for(
                    session.reader.read(200),
                    timeout=self._config.web_client_read_timeout,
                )
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                await self._close_web_client_session(client_id, "response timeout")
                return False, "Timed out waiting for backend response.", int((time.monotonic() - start) * 1000)
            except Exception as exc:
                await self._close_web_client_session(client_id, "send error")
                return False, f"Failed to send message: {exc}", int((time.monotonic() - start) * 1000)

        response = data.decode("utf-8", errors="replace").strip()
        latency_ms = int((time.monotonic() - start) * 1000)
        if not response:
            return False, "Empty response from backend.", latency_ms
        return True, response, latency_ms

    async def _reap_idle_web_clients(self) -> None:
        while True:
            await asyncio.sleep(5)
            if self._config.web_client_idle_timeout <= 0:
                continue
            now = time.monotonic()
            async with self._web_clients_lock:
                stale = [
                    client_id
                    for client_id, session in self._web_clients.items()
                    if session.writer.is_closing()
                    or now - session.last_activity > self._config.web_client_idle_timeout
                ]
            for client_id in stale:
                await self._close_web_client_session(client_id, "idle timeout")

    async def _send_response(
        self, writer: asyncio.StreamWriter, status: int, reason: str, body: bytes, content_type: str
    ) -> None:
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

    async def handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2.0)
        except asyncio.TimeoutError:
            writer.close()
            await writer.wait_closed()
            return
        except asyncio.IncompleteReadError:
            writer.close()
            await writer.wait_closed()
            return
        except asyncio.LimitOverrunError:
            await self._send_response(
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
            await self._send_response(
                writer, 400, "Bad Request", b"Invalid request line.", "text/plain; charset=utf-8"
            )
            return

        if method.upper() != "GET":
            await self._send_response(
                writer, 405, "Method Not Allowed", b"Only GET is supported.", "text/plain; charset=utf-8"
            )
            return

        parsed = urlsplit(target)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/status":
            payload = await self._status_payload()
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            await self._send_response(writer, 200, "OK", body, "application/json; charset=utf-8")
            return
        if path == "/api/connect":
            client_id = query.get("client_id", [""])[0].strip()
            if not client_id:
                payload = {"ok": False, "error": "client_id is required."}
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                await self._send_response(writer, 400, "Bad Request", body, "application/json; charset=utf-8")
                return
            ok, message = await self._open_web_client_session(client_id)
            status = 200 if ok else 502
            payload = {"ok": ok, "message": message}
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            await self._send_response(writer, status, "OK" if ok else "Bad Gateway", body, "application/json; charset=utf-8")
            return
        if path == "/api/disconnect":
            client_id = query.get("client_id", [""])[0].strip()
            if not client_id:
                payload = {"ok": False, "error": "client_id is required."}
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                await self._send_response(writer, 400, "Bad Request", body, "application/json; charset=utf-8")
                return
            await self._close_web_client_session(client_id, "manual disconnect")
            payload = {"ok": True, "message": "Disconnected."}
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            await self._send_response(writer, 200, "OK", body, "application/json; charset=utf-8")
            return
        if path == "/api/send":
            message = query.get("message", [""])[0]
            client_id = query.get("client_id", [""])[0].strip()
            message = message.strip()
            if not client_id:
                payload = {"ok": False, "error": "client_id is required."}
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                await self._send_response(writer, 400, "Bad Request", body, "application/json; charset=utf-8")
                return
            if not message:
                payload = {"ok": False, "error": "Message is required."}
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                await self._send_response(writer, 400, "Bad Request", body, "application/json; charset=utf-8")
                return
            if len(message) > 256:
                payload = {"ok": False, "error": "Message is too long (max 256 characters)."}
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                await self._send_response(writer, 413, "Payload Too Large", body, "application/json; charset=utf-8")
                return

            ok, response_text, latency_ms = await self._send_via_web_client(client_id, message)
            if ok:
                payload = {"ok": True, "response": response_text, "latency_ms": latency_ms}
                await self._record_event("INFO", f"Web client {client_id} -> {response_text}")
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                await self._send_response(writer, 200, "OK", body, "application/json; charset=utf-8")
            else:
                payload = {"ok": False, "error": response_text, "latency_ms": latency_ms}
                await self._record_event("ERROR", f"Web client {client_id} failed: {response_text}")
                status = 409 if response_text.startswith("Web client is not connected") else 502
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                await self._send_response(writer, status, "Bad Gateway", body, "application/json; charset=utf-8")
            return

        static_map = {
            "/": "index.html",
            "/app.js": "app.js",
            "/server.html": "server.html",
            "/server.js": "server.js",
            "/client.html": "client.html",
            "/client.js": "client.js",
            "/styles.css": "styles.css",
        }
        filename = static_map.get(path)
        if not filename:
            await self._send_response(writer, 404, "Not Found", b"Not Found.", "text/plain; charset=utf-8")
            return

        file_path = self._static_dir / filename
        try:
            body = file_path.read_bytes()
        except FileNotFoundError:
            await self._send_response(writer, 404, "Not Found", b"Not Found.", "text/plain; charset=utf-8")
            return

        content_type = "text/plain; charset=utf-8"
        if filename.endswith(".html"):
            content_type = "text/html; charset=utf-8"
        elif filename.endswith(".css"):
            content_type = "text/css; charset=utf-8"
        elif filename.endswith(".js"):
            content_type = "application/javascript; charset=utf-8"

        await self._send_response(writer, 200, "OK", body, content_type)

    async def serve(self) -> None:
        await self.refresh_active_servers()

        server = await asyncio.start_server(self.handle_client, self._config.host, self._config.port)
        sockets = server.sockets or []
        listen_addrs = ", ".join(str(sock.getsockname()) for sock in sockets)
        self._logger.info("Load balancer listening on %s", listen_addrs)

        http_server: Optional[asyncio.base_events.Server] = None
        if self._config.http_port > 0:
            http_server = await asyncio.start_server(
                self.handle_http, self._config.http_host, self._config.http_port
            )
            http_sockets = http_server.sockets or []
            http_listen = ", ".join(str(sock.getsockname()) for sock in http_sockets)
            self._logger.info("Dashboard listening on %s", http_listen)
            await self._record_event("INFO", f"Dashboard online at {http_listen}")

        health_task = asyncio.create_task(self.perform_health_checks())
        reap_task = asyncio.create_task(self._reap_idle_web_clients())
        server_task = asyncio.create_task(server.serve_forever())
        http_task = asyncio.create_task(http_server.serve_forever()) if http_server else None
        try:
            tasks = [server_task]
            if http_task:
                tasks.append(http_task)
            await asyncio.gather(*tasks)
        finally:
            health_task.cancel()
            await asyncio.gather(health_task, return_exceptions=True)
            reap_task.cancel()
            await asyncio.gather(reap_task, return_exceptions=True)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Distributed AsyncIO Load Balancer Simulator")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the load balancer to")
    parser.add_argument("--port", type=int, default=8080, help="Port for the load balancer to listen on")
    parser.add_argument(
        "--backends",
        type=parse_backends,
        default=parse_backends("127.0.0.1:8881,127.0.0.1:8882"),
        help="Comma-separated list of host:port backends",
    )
    parser.add_argument(
        "--algorithm",
        choices=["auto", "round-robin", "least-connections"],
        default="auto",
        help="Scheduling algorithm to use (sticky sessions are applied first when available)",
    )
    parser.add_argument(
        "--sticky-key",
        choices=["ip", "ip-port"],
        default="ip",
        help="Sticky session key derivation",
    )
    parser.add_argument(
        "--health-check-interval",
        type=float,
        default=5.0,
        help="Seconds between health checks",
    )
    parser.add_argument(
        "--health-check-timeout",
        type=float,
        default=1.0,
        help="Per-backend health check connect timeout in seconds",
    )
    parser.add_argument(
        "--wait-for-backend-timeout",
        type=float,
        default=30.0,
        help="How long to wait for any backend to recover before closing the client",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity",
    )
    parser.add_argument(
        "--http-host",
        default="0.0.0.0",
        help="Host to bind the dashboard HTTP server to (set --http-port 0 to disable)",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=8081,
        help="Port for the dashboard HTTP server (0 to disable)",
    )
    parser.add_argument(
        "--backend-status-port-offset",
        type=int,
        default=1000,
        help="Offset to add to backend port for status HTTP port",
    )
    parser.add_argument(
        "--web-client-idle-timeout",
        type=float,
        default=120.0,
        help="Seconds before an idle web client connection is closed",
    )
    parser.add_argument(
        "--web-client-read-timeout",
        type=float,
        default=3.0,
        help="Seconds to wait for backend response for web client",
    )

    args = parser.parse_args()
    configure_logging(args.log_level)
    logger = logging.getLogger("lb")

    config = LoadBalancerConfig(
        host=args.host,
        port=args.port,
        backends=args.backends,
        algorithm=args.algorithm,
        health_check_interval=args.health_check_interval,
        wait_for_backend_timeout=args.wait_for_backend_timeout,
        health_check_timeout=args.health_check_timeout,
        sticky_key=args.sticky_key,
        http_host=args.http_host,
        http_port=args.http_port,
        backend_status_port_offset=args.backend_status_port_offset,
        web_client_idle_timeout=args.web_client_idle_timeout,
        web_client_read_timeout=args.web_client_read_timeout,
    )

    logger.info(
        "Starting load balancer (algorithm=%s, sticky_key=%s, backends=%s)",
        config.algorithm,
        config.sticky_key,
        list(config.backends),
    )

    asyncio.run(LoadBalancer(config, logger).serve())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down Load Balancer...")
