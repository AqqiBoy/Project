const elements = {
  statusDot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  metricActive: document.getElementById("metric-active"),
  metricConnections: document.getElementById("metric-connections"),
  metricAlgorithm: document.getElementById("metric-algorithm"),
  metricUptime: document.getElementById("metric-uptime"),
  backendList: document.getElementById("backend-list"),
  backendSummary: document.getElementById("backend-summary"),
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
    meta.innerHTML = `<span>LB Connections</span><span>${backend.connections}</span>`;

    const stats = document.createElement("div");
    stats.className = "backend-stats";
    const details = backend.details || {};
    const uptime = Number.isFinite(details.uptime_seconds)
      ? formatUptime(details.uptime_seconds)
      : "n/a";
    const messages = Number.isFinite(details.message_count) ? details.message_count : "n/a";
    stats.innerHTML = `<span>Uptime</span><span>${uptime}</span><span>Messages</span><span>${messages}</span>`;

    card.appendChild(title);
    card.appendChild(meta);
    card.appendChild(stats);
    elements.backendList.appendChild(card);
  });
}

function renderStatus(payload) {
  const totalConnections = payload.backends.reduce(
    (sum, backend) => sum + (backend.connections || 0),
    0
  );

  elements.metricActive.textContent = `${payload.active_backends}/${payload.total_backends}`;
  elements.metricConnections.textContent = totalConnections;
  elements.metricAlgorithm.textContent = payload.algorithm;
  elements.metricUptime.textContent = formatUptime(payload.uptime_seconds);

  elements.backendSummary.textContent = `${payload.total_backends} total`;
  renderBackends(payload.backends);
  setStatus(payload.active_backends, payload.total_backends);

  const now = new Date();
  elements.updatedAt.textContent = `Last updated at ${now.toLocaleTimeString()}`;
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
