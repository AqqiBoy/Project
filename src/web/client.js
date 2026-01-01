const elements = {
  statusDot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  clientId: document.getElementById("client-id"),
  form: document.getElementById("client-form"),
  input: document.getElementById("client-message"),
  sendButton: document.getElementById("client-send"),
  messageList: document.getElementById("message-list"),
  metricAlgorithm: document.getElementById("metric-algorithm"),
  metricSticky: document.getElementById("metric-sticky"),
  metricActive: document.getElementById("metric-active"),
  metricUptime: document.getElementById("metric-uptime"),
  updatedAt: document.getElementById("updated-at"),
};

const clientIdKey = "lb-client-id";
let clientId = localStorage.getItem(clientIdKey);
if (!clientId) {
  clientId = `lb-${Math.random().toString(36).slice(2, 9)}`;
  localStorage.setItem(clientIdKey, clientId);
}
elements.clientId.textContent = `Client: ${clientId}`;

function formatUptime(seconds) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  const parts = [];
  if (hrs) parts.push(`${hrs}h`);
  if (mins || hrs) parts.push(`${mins}m`);
  parts.push(`${secs}s`);
  return parts.join(" ");
}

function setStatus(activeCount, totalCount) {
  if (totalCount === 0) {
    elements.statusDot.style.background = "var(--warn)";
    elements.statusDot.style.boxShadow = "0 0 0 4px rgba(201, 114, 35, 0.2)";
    elements.statusText.textContent = "No backends configured";
    return;
  }

  if (activeCount === 0) {
    elements.statusDot.style.background = "var(--danger)";
    elements.statusDot.style.boxShadow = "0 0 0 4px rgba(181, 58, 58, 0.2)";
    elements.statusText.textContent = "All backends offline";
    return;
  }

  if (activeCount < totalCount) {
    elements.statusDot.style.background = "var(--warn)";
    elements.statusDot.style.boxShadow = "0 0 0 4px rgba(201, 114, 35, 0.2)";
    elements.statusText.textContent = "Degraded backend pool";
    return;
  }

  elements.statusDot.style.background = "var(--accent)";
  elements.statusDot.style.boxShadow = "0 0 0 4px rgba(27, 122, 110, 0.2)";
  elements.statusText.textContent = "All systems routing";
}

function renderStatus(payload) {
  elements.metricAlgorithm.textContent = payload.algorithm;
  elements.metricSticky.textContent = payload.sticky_key;
  elements.metricActive.textContent = `${payload.active_backends}/${payload.total_backends}`;
  elements.metricUptime.textContent = formatUptime(payload.uptime_seconds);
  setStatus(payload.active_backends, payload.total_backends);

  const now = new Date();
  elements.updatedAt.textContent = `Last updated at ${now.toLocaleTimeString()}`;
}

function addMessageCard(entry) {
  const card = document.createElement("div");
  card.className = "message-card";

  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = `${entry.time} | ${entry.status}`;

  const request = document.createElement("div");
  request.className = "message-request";
  request.textContent = `You: ${entry.message}`;

  const response = document.createElement("div");
  response.className = "message-response";
  response.textContent = entry.response;

  card.appendChild(meta);
  card.appendChild(request);
  card.appendChild(response);
  elements.messageList.prepend(card);
}

async function fetchStatus() {
  const response = await fetch("/api/status", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Status request failed: ${response.status}`);
  }
  return response.json();
}

async function refreshStatus() {
  try {
    const payload = await fetchStatus();
    renderStatus(payload);
  } catch (error) {
    elements.statusDot.style.background = "var(--warn)";
    elements.statusDot.style.boxShadow = "0 0 0 4px rgba(201, 114, 35, 0.2)";
    elements.statusText.textContent = "Dashboard offline";
    elements.updatedAt.textContent = "Waiting for connection...";
  }
}

async function sendMessage(message) {
  const url = `/api/send?message=${encodeURIComponent(message)}&client_id=${encodeURIComponent(clientId)}`;
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || "Send failed.");
  }
  return payload;
}

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = elements.input.value.trim();
  if (!message) {
    return;
  }

  elements.sendButton.disabled = true;
  elements.sendButton.textContent = "Sending...";

  const time = new Date().toLocaleTimeString();
  try {
    const payload = await sendMessage(message);
    const latency = payload.latency_ms ? ` (${payload.latency_ms}ms)` : "";
    addMessageCard({
      time,
      status: `OK${latency}`,
      message,
      response: payload.response || "-",
    });
    elements.input.value = "";
  } catch (error) {
    addMessageCard({
      time,
      status: "Error",
      message,
      response: error.message || "Request failed.",
    });
  } finally {
    elements.sendButton.disabled = false;
    elements.sendButton.textContent = "Send";
    elements.input.focus();
  }
});

refreshStatus();
setInterval(refreshStatus, 2000);
