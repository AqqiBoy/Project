# CODEX Notes: Phase 1 & Phase 2 Deliverables

## Phase 1 (Core System) - Implemented
- Async backend echo servers per host/port responding with server name; run via `src/server.py`.
- Interactive asyncio client for manual testing against the load balancer; supports continuous input (`src/client.py`).
- Core load balancer wiring requests to backends with round-robin scheduling across `SERVER_POOL` (`src/load_balancer.py`).
- Baseline project scaffolding and Phase 1 run instructions captured in `README.md`.

## Phase 2 (Advanced Scheduling & Health) - Implemented
- Automated health checks updating `ACTIVE_SERVERS` and resetting stale counts; runs periodically via `perform_health_checks`.
- Connection count tracking in `CONNECTION_COUNT` enabling least-connections scheduling and auto tie-breaking.
- Failover/failback handling that retries alternate backends on refused/failed connections and mid-stream closures, waiting up to `WAIT_FOR_BACKEND_TIMEOUT` for recovery.
- Configurable scheduling with `--algorithm` options (`auto`, `round-robin`, `least-connections`); auto chooses least-connections when counts diverge, otherwise round-robin.
- Time-based safeguards with `HEALTH_CHECK_INTERVAL` and backend wait loops to keep the balancer responsive during outages.
