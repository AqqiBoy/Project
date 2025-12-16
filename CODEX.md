# CODEX Notes: Phase Deliverables

## Phase 1 (Core System) — Implemented
- Async backend echo servers per host/port responding with server name (`src/server.py`).
- Interactive asyncio client for manual testing (`src/client.py`).
- Core load balancer wiring requests to backends with round-robin scheduling (`src/load_balancer.py`).
- Run instructions documented in `README.md`.

## Phase 2 (Advanced Scheduling & Health) — Implemented
- Automated health checks updating `ACTIVE_SERVERS` (`src/load_balancer.py`).
- Least-connections scheduling using `CONNECTION_COUNT` with tie-breaking.
- Failover/failback that retries alternate backends on connection failures and mid-stream closures, waiting up to `--wait-for-backend-timeout`.
- Configurable scheduling with `--algorithm` options (`auto`, `round-robin`, `least-connections`).

## Phase 3 (Sticky Sessions & Polish) — Implemented
- Sticky sessions via `SESSION_MAP` (sticky check applied before scheduler).
- Configurable stickiness key with `--sticky-key` (`ip` or `ip-port`).
- Improved structured logging with `--log-level`.
- Refactored load balancer into a single, clean implementation and updated documentation.
