
# Distributed Load Balancer Simulator - Phase 1

This document contains the setup and running instructions for Phase 1 (Core System) of the Distributed Load Balancer Simulator.

## Project Structure

The project is organized as follows:

```
.
└── src/
    ├── load_balancer.py  # The main load balancer
    ├── server.py         # The backend server code
    └── client.py         # The client application for testing
```

## How to Run and Test (Phase 1)

Follow these steps to run the complete system. You will need **four separate terminal windows**.

**Important LAN Note:**
The code is currently configured to run on a single machine (`127.0.0.1`). When deploying on a real LAN, you must:
1.  Update the `SERVER_POOL` list in `src/load_balancer.py` with the actual private IP addresses of your backend server machines (e.g., `192.168.1.11`, `192.168.1.12`).
2.  The client will connect to the load balancer's LAN IP (e.g., `192.168.1.10`).
3.  Ensure your firewall allows traffic on the specified ports (8080, 8881, 8882).

---

### Step 1: Start Backend Server 1 (B1)

Open your **first terminal** and run:

```sh
python src/server.py --name B1 --port 8881
```

**Expected Output:**
```
Backend server 'B1' listening on ('0.0.0.0', 8881)
```

---

### Step 2: Start Backend Server 2 (B2)

Open your **second terminal** and run:

```sh
python src/server.py --name B2 --port 8882
```

**Expected Output:**
```
Backend server 'B2' listening on ('0.0.0.0', 8882)
```
> At this point, you have two backend servers ready to accept connections.

---

### Step 3: Start the Load Balancer

Open your **third terminal** and run the load balancer:

```sh
python src/load_balancer.py
```

**Expected Output:**
```
Load Balancer listening on ('0.0.0.0', 8080)
```
> The load balancer is now listening for client connections on port `8080`.

---

### Step 4: Run the Client to Test

Now, use the client to send requests. Each time you run the client, the load balancer will forward the connection to the next server in the round-robin sequence.

Open your **fourth terminal**.

**Run the client for the first time:**
```sh
python client.py --host 127.0.0.1 --port 8080
```

**Expected Output (Client - 1st run):**
```
Connecting to 127.0.0.1:8080...
Sending: 'Hello from Client'
Received: 'Hello from B1'
Closing the connection.
```
*You will see connection logs in the Load Balancer and B1 terminals.*


**Run the client for the second time:**
```sh
python src/client.py --host 127.0.0.1 --port 8080
```

**Expected Output (Client - 2nd run):**
```
Connecting to 127.0.0.1:8080...
Sending: 'Hello from Client'
Received: 'Hello from B2'
Closing the connection.
```
*You will see connection logs in the Load Balancer and B2 terminals.*

If you run the client a third time, it will connect to B1 again, confirming the round-robin scheduling is working.

---

This completes the setup and verification for Phase 1. The core system is now functional.
