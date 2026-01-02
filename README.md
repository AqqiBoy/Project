# Distributed Load Balancer Simulator (Phases 1–3)

Python `asyncio` TCP load balancer simulator with backend echo servers and an interactive client.

## Features

- **Phase 1:** Backend servers, test client, and load balancer with **round-robin** scheduling.
- **Phase 2:** Automated **health checks**, `ACTIVE_SERVERS` management, **least-connections** scheduling, and failover/failback behavior.
- **Phase 3:** **Sticky sessions** via `SESSION_MAP`, improved logging, and CLI configuration for LAN/local runs.

## Project Structure

```
.
└─ src/
   ├─ load_balancer.py  # Load balancer
   ├─ server.py         # Backend server
   └─ client.py         # Interactive client for testing
```

## Requirements

- Python 3.9+ (uses `asyncio.to_thread`)

## Quick Start (Single Machine)

Open **four terminals**.

### Terminal 1: Backend B1

```sh
python src/server.py --name B1 --host 127.0.0.1 --port 8881
```

### Terminal 2: Backend B2

```sh
python src/server.py --name B2 --host 127.0.0.1 --port 8882
```

By default, each backend also exposes a status endpoint on `port + 1000`:

- `http://127.0.0.1:9881/status`
- `http://127.0.0.1:9882/status`

### Terminal 3: Load Balancer

```sh
python src/load_balancer.py --host 127.0.0.1 --port 8080 --backends 127.0.0.1:8881,127.0.0.1:8882 --algorithm auto --http-port 8081
```

### Terminal 4: Client

```sh
python src/client.py --host 127.0.0.1 --port 8080
```

### Dashboard (Browser)

Open: `http://127.0.0.1:8081`

Additional pages:

- Servers view: `http://127.0.0.1:8081/server.html`
- Web client: `http://127.0.0.1:8081/client.html`

The web client keeps a persistent connection once you press **Connect** (idle connections close after the timeout).

## LAN Setup

1. Start backend servers on their machines (bind to all interfaces):

```sh
python src/server.py --name B1 --host 0.0.0.0 --port 8881
python src/server.py --name B2 --host 0.0.0.0 --port 8882
```

2. Start the load balancer on its machine and point it at backend LAN IPs:

```sh
python src/load_balancer.py --host 0.0.0.0 --port 8080 --backends 192.168.1.11:8881,192.168.1.12:8882 --algorithm auto --http-port 8081
```

3. Run the client from any machine on the LAN and connect to the load balancer IP:

```sh
python src/client.py --host 192.168.1.10 --port 8080
```

4. Open the dashboard from any LAN machine:

```
http://192.168.1.10:8081
```

Server and client views:

```
http://192.168.1.10:8081/server.html
http://192.168.1.10:8081/client.html
```

Make sure firewalls allow TCP traffic to the backend ports (e.g. `8881`, `8882`) and the load balancer port (e.g. `8080`).

Also allow the dashboard HTTP port (default `8081`).

## Configuration

- `--algorithm`: `auto` | `round-robin` | `least-connections`
- `--backends`: comma-separated `host:port` list (e.g. `10.0.0.11:8881,10.0.0.12:8882`)
- `--sticky-key`: `ip` (default) or `ip-port`
- `--health-check-interval`, `--health-check-timeout`, `--wait-for-backend-timeout`
- `--log-level`: `DEBUG` | `INFO` | `WARNING` | `ERROR`
- `--http-host`, `--http-port` (set `--http-port 0` to disable the dashboard)
- `--backend-status-port-offset` (load balancer uses backend `port + offset` for status)
- `--web-client-idle-timeout`, `--web-client-read-timeout`

Backend status endpoint:

- Each backend exposes `GET /status` on `port + 1000` by default (override with `--http-port`).
- Backend flags: `--http-host`, `--http-port`, `--http-port-offset`

## Sticky Sessions

Sticky sessions are applied first when a mapping exists:

- Default behavior uses the client **IP address** as the key (`--sticky-key ip`).
- Use `--sticky-key ip-port` if you want stickiness per (IP, port) instead.
