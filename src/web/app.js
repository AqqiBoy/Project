const state = {
  lastUpdate: null,
};

const elements = {
  statusDot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  metricAlgorithm: document.getElementById("metric-algorithm"),
  metricSticky: document.getElementById("metric-sticky"),
  metricActive: document.getElementById("metric-active"),
  metricSessions: document.getElementById("metric-sessions"),
  metricUptime: document.getElementById("metric-uptime"),
  backendList: document.getElementById("backend-list"),
  backendSummary: document.getElementById("backend-summary"),
  eventList: document.getElementById("event-list"),
  eventSummary: document.getElementById("event-summary"),
  updatedAt: document.getElementById("updated-at"),
};

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

function renderBackends(backends) {
  elements.backendList.innerHTML = "";
  backends.forEach((backend) => {
    const card = document.createElement("div");
    card.className = "backend-card";

    const title = document.createElement("div");
    title.className = "backend-title";
    title.textContent = `${backend.host}:${backend.port}`;

    const badge = document.createElement("span");
    badge.className = `badge ${backend.active ? "active" : "down"}`;
    badge.textContent = backend.active ? "Active" : "Down";
    title.appendChild(badge);

    const meta = document.createElement("div");
    meta.className = "backend-meta";
    meta.innerHTML = `<span>Connections</span><span>${backend.connections}</span>`;

    card.appendChild(title);
    card.appendChild(meta);
    elements.backendList.appendChild(card);
  });
}

function renderEvents(events) {
  elements.eventList.innerHTML = "";
  if (!events.length) {
    const empty = document.createElement("div");
    empty.className = "event-card";
    empty.textContent = "No events yet.";
    elements.eventList.appendChild(empty);
    return;
  }

  events.slice(-8).reverse().forEach((event) => {
    const card = document.createElement("div");
    card.className = "event-card";

    const title = document.createElement("div");
    title.className = "event-title";
    title.innerHTML = `<span>${event.time}</span>`;

    const level = document.createElement("span");
    const levelClass = event.level ? event.level.toLowerCase() : "info";
    level.className = `event-level ${levelClass}`;
    level.textContent = event.level || "INFO";
    title.appendChild(level);

    const message = document.createElement("div");
    message.className = "event-message";
    message.textContent = event.message || "-";

    card.appendChild(title);
    card.appendChild(message);
    elements.eventList.appendChild(card);
  });
}

function renderStatus(payload) {
  elements.metricAlgorithm.textContent = payload.algorithm;
  elements.metricSticky.textContent = payload.sticky_key;
  elements.metricActive.textContent = `${payload.active_backends}/${payload.total_backends}`;
  elements.metricSessions.textContent = payload.session_count;
  elements.metricUptime.textContent = formatUptime(payload.uptime_seconds);

  elements.backendSummary.textContent = `${payload.total_backends} total`;
  elements.eventSummary.textContent = `${payload.events.length} events`;

  renderBackends(payload.backends);
  renderEvents(payload.events);
  setStatus(payload.active_backends, payload.total_backends);

  state.lastUpdate = new Date();
  elements.updatedAt.textContent = `Last updated at ${state.lastUpdate.toLocaleTimeString()}`;
}

async function fetchStatus() {
  const response = await fetch("/api/status", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Status request failed: ${response.status}`);
  }
  return response.json();
}

async function refresh() {
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

refresh();
setInterval(refresh, 2000);
