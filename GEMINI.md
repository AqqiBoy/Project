# Gemini Project Brief: Distributed Load Balancer Simulator

This document provides context for the AI assistant working on this project.

## 1. Project Overview

The goal is to build a Distributed Load Balancer Simulator in Python using the `asyncio` library. The entire system is designed to run on a Local Area Network (LAN) with fixed private IP addresses.

## 2. Core Architecture

- **Load Balancer (LB):** A Python `asyncio` application that listens for TCP connections and forwards them to backend servers based on a scheduling algorithm.
- **Backend Servers:** Simple Python `asyncio` TCP echo-style servers. Each server runs on a separate machine/port and returns a unique identifier (e.g., "Hello from B1").
- **Client:** A simple Python script to test the load balancer by sending messages and printing the backend's response.

## 3. Phased Development Plan

The project is divided into three distinct phases, with different team members assigned to each.

### 🔵 Phase 1: Core System (Completed)
- **Implementer:** Alquamah
- **Tasks:**
  - Create backend servers.
  - Create a simple test client.
  - Implement the core load balancer with basic **round-robin** scheduling.
  - Establish a stable project structure.

### 🟡 Phase 2: Advanced Scheduling & Health Checks (Next)
- **Implementer:** Waqas
- **Tasks:**
  - Implement automated health checks to monitor backend server status.
  - Manage a list of `ACTIVE_SERVERS`.
  - Implement failover and failback logic.
  - Add **Least-Connections** scheduling as an alternative algorithm.
  - Maintain a `CONNECTION_COUNT` data structure.

### 🟢 Phase 3: Sticky Sessions & Polish
- **Implementer:** Saboor
- **Tasks:**
  - Implement **Sticky Sessions** to ensure a client is consistently routed to the same backend.
  - Maintain a `SESSION_MAP` for client-to-backend mappings.
  - Improve logging and monitoring across the system.
  - Refactor and document the complete codebase.

## 4. Current Status

**Phase 1 is complete.** The current codebase includes the foundational server, client, and a round-robin load balancer. The next development steps should focus on implementing the features for **Phase 2**.
