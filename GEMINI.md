# Project Brief: Distributed Load Balancer Simulator

This document provides context for the project and summarizes the intended deliverables.

## 1. Project Overview

The goal is to build a Distributed Load Balancer Simulator in Python using `asyncio`. The system is designed to run on a Local Area Network (LAN) with fixed private IP addresses.

## 2. Core Architecture

- **Load Balancer (LB):** An `asyncio` TCP proxy that listens for client connections and forwards them to backend servers using a scheduling algorithm.
- **Backend Servers:** Simple `asyncio` TCP echo-style servers returning a unique identifier (e.g. `Hello from B1`).
- **Client:** A simple interactive TCP client to send messages through the load balancer and print responses.

## 3. Phased Development Plan

### Phase 1: Core System
- Create backend servers.
- Create a simple test client.
- Implement the core load balancer with basic **round-robin** scheduling.
- Establish a stable project structure.

### Phase 2: Advanced Scheduling & Health Checks
- Implement automated health checks to monitor backend server status.
- Manage a list of `ACTIVE_SERVERS`.
- Implement failover and failback logic.
- Add **Least-Connections** scheduling as an alternative algorithm.
- Maintain a `CONNECTION_COUNT` data structure.

### Phase 3: Sticky Sessions & Polish
- Implement **Sticky Sessions** to ensure a client is consistently routed to the same backend.
- Maintain a `SESSION_MAP` for client-to-backend mappings.
- Improve logging and monitoring across the system.
- Refactor and document the complete codebase.

## 4. Current Status

- **Phase 1:** Implemented (`src/server.py`, `src/client.py`, `src/load_balancer.py`).
- **Phase 2:** Implemented (health checks, `ACTIVE_SERVERS`, least-connections, failover/failback in `src/load_balancer.py`).
- **Phase 3:** Implemented (sticky sessions and polish: logging, refactor, updated docs).

Note: Sticky sessions are currently in-memory (lost on load balancer restart) by design for this simulator.
