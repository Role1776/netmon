/* Authenticated Netmon dashboard behaviour.
 *
 * Only browser-native APIs are used, so the interface remains available when
 * the WAN connection being measured is unavailable. Every mutating request
 * carries the CSRF token rendered into the authenticated page. The API key is
 * submitted once and is never requested back from the server.
 */

const refreshIntervalMs = 30_000;
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

const elements = {
  serviceState: document.querySelector("#service-state"),
  aiState: document.querySelector("#ai-state"),
  runNow: document.querySelector("#run-now"),
  download: document.querySelector("#download"),
  upload: document.querySelector("#upload"),
  ping: document.querySelector("#ping"),
  devices: document.querySelector("#devices"),
  latestTime: document.querySelector("#latest-time"),
  graph: document.querySelector("#history-graph"),
  graphPlaceholder: document.querySelector("#graph-placeholder"),
  reportFeed: document.querySelector("#report-feed"),
  deviceTable: document.querySelector("#device-table"),
  chatLog: document.querySelector("#chat-log"),
  chatForm: document.querySelector("#chat-form"),
  chatInput: document.querySelector("#chat-input"),
  aiKeyStatus: document.querySelector("#ai-key-status"),
  aiProvider: document.querySelector("#ai-provider"),
  aiModel: document.querySelector("#ai-model"),
  aiLastTest: document.querySelector("#ai-last-test"),
  aiMessage: document.querySelector("#ai-message"),
  aiKeyForm: document.querySelector("#ai-key-form"),
  aiApiKey: document.querySelector("#ai-api-key"),
  aiEnabled: document.querySelector("#ai-enabled"),
  aiTest: document.querySelector("#ai-test"),
  aiRemove: document.querySelector("#ai-remove"),
};

function formatTime(value) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function setText(element, value) {
  if (element) element.textContent = value;
}

function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.method && options.method.toUpperCase() !== "GET") {
    headers.set("X-CSRF-Token", csrfToken);
  }
  return fetch(url, { ...options, headers, cache: "no-store" });
}

async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 428) {
    window.location.assign(response.status === 428 ? "/setup" : "/login");
    throw new Error("Authentication required");
  }
  if (!response.ok) {
    throw new Error(data.error || `Request returned ${response.status}`);
  }
  return data;
}

function renderLatest(latest) {
  if (!latest) {
    ["download", "upload", "ping", "devices"].forEach((key) => {
      setText(elements[key], "—");
    });
    setText(elements.latestTime, "No samples yet");
    elements.graph.hidden = true;
    elements.graphPlaceholder.hidden = false;
    return;
  }

  setText(elements.download, latest.download_mbps.toFixed(1));
  setText(elements.upload, latest.upload_mbps.toFixed(1));
  setText(elements.ping, latest.ping.toFixed(1));
  setText(elements.devices, String(latest.device_count));
  setText(elements.latestTime, `Latest: ${formatTime(latest.timestamp)}`);

  // The collector intentionally overwrites one stable PNG path. This query
  // prevents the browser from retaining an older graph after a new cycle.
  elements.graph.src = `/graph.png?t=${Date.now()}`;
  elements.graph.hidden = false;
  elements.graphPlaceholder.hidden = true;
}

function renderReports(reports) {
  elements.reportFeed.replaceChildren();
  if (!reports.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No reports yet.";
    elements.reportFeed.append(empty);
    return;
  }

  reports.forEach((report) => {
    const article = document.createElement("article");
    article.className = `report ${report.kind}`;

    const header = document.createElement("div");
    header.className = "report-header";

    const title = document.createElement("h3");
    title.textContent = report.title;

    const time = document.createElement("time");
    time.className = "muted";
    time.textContent = formatTime(report.created_at);

    const body = document.createElement("pre");
    body.textContent = report.body;

    header.append(title, time);
    article.append(header, body);
    elements.reportFeed.append(article);
  });
}

function renderDevices(devices) {
  elements.deviceTable.replaceChildren();
  if (!devices.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 2;
    cell.className = "empty-state";
    cell.textContent = "No scan yet.";
    row.append(cell);
    elements.deviceTable.append(row);
    return;
  }

  devices.forEach((device) => {
    const row = document.createElement("tr");
    const address = document.createElement("td");
    const latency = document.createElement("td");
    address.textContent = device.ip;
    latency.textContent = `${Number(device.latency_ms).toFixed(2)} ms`;
    row.append(address, latency);
    elements.deviceTable.append(row);
  });
}

function appendChatMessage(role, body, createdAt = null) {
  const message = document.createElement("div");
  message.className = `chat-message ${role}`;
  message.textContent = body;

  if (createdAt) {
    const time = document.createElement("time");
    time.textContent = formatTime(createdAt);
    message.append(time);
  }

  elements.chatLog.append(message);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
}

function renderChat(messages) {
  elements.chatLog.replaceChildren();
  if (!messages.length) {
    appendChatMessage(
      "assistant",
      "Ask about current speed, the slowest test, latency, devices or the last 24 hours. Enable Remote AI for free-form questions."
    );
    return;
  }

  messages.forEach((message) => {
    appendChatMessage(message.role, message.body, message.created_at);
  });
}

function showAiMessage(message, kind = "good") {
  elements.aiMessage.hidden = false;
  elements.aiMessage.className = `form-message ${kind}`;
  elements.aiMessage.textContent = message;
}

function clearAiMessage() {
  elements.aiMessage.hidden = true;
  elements.aiMessage.textContent = "";
}

function renderAiSettings(settings) {
  setText(elements.aiProvider, settings.provider);
  setText(elements.aiModel, settings.model);
  setText(elements.aiLastTest, formatTime(settings.last_test_at));

  if (settings.key_active) {
    elements.aiKeyStatus.textContent = "API key active";
    elements.aiKeyStatus.className = "status-pill good";
    elements.aiApiKey.placeholder = "API key active — paste a new key to replace it";
  } else {
    elements.aiKeyStatus.textContent = "No active API key";
    elements.aiKeyStatus.className = "status-pill muted";
    elements.aiApiKey.placeholder = "Paste a Groq API key";
  }

  elements.aiEnabled.checked = Boolean(settings.enabled);
  elements.aiEnabled.disabled = !settings.key_active;
  elements.aiTest.disabled = !settings.key_active;
  elements.aiRemove.disabled = !settings.key_active;

  elements.aiState.textContent = settings.enabled ? "Remote AI enabled" : "Local rules only";
  elements.aiState.className = settings.enabled ? "status-pill good" : "status-pill muted";

  if (settings.last_error) {
    showAiMessage(settings.last_error, "error");
  }
}

async function refreshAiSettings() {
  const response = await apiFetch("/api/ai-settings");
  const settings = await readJson(response);
  renderAiSettings(settings);
}

async function refreshDashboard() {
  try {
    const response = await apiFetch("/api/status");
    const data = await readJson(response);
    renderLatest(data.latest);
    renderReports(data.reports);
    renderDevices(data.devices);
    renderChat(data.chat);

    elements.serviceState.textContent = "Collector data online";
    elements.serviceState.className = "status-pill good";
  } catch (error) {
    console.error(error);
    elements.serviceState.textContent = "Dashboard error";
    elements.serviceState.className = "status-pill";
  }
}

elements.runNow.addEventListener("click", async () => {
  elements.runNow.disabled = true;
  elements.runNow.textContent = "Requested…";

  try {
    const response = await apiFetch("/api/run-now", { method: "POST" });
    await readJson(response);
    elements.serviceState.textContent = "Manual test queued";
  } catch (error) {
    console.error(error);
    elements.serviceState.textContent = "Manual request failed";
  } finally {
    window.setTimeout(() => {
      elements.runNow.disabled = false;
      elements.runNow.textContent = "Run test now";
    }, 4_000);
  }
});

elements.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = elements.chatInput.value.trim();
  if (!message) return;

  appendChatMessage("user", message);
  elements.chatInput.value = "";
  const submit = elements.chatForm.querySelector("button");
  submit.disabled = true;

  try {
    const response = await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await readJson(response);
    appendChatMessage("assistant", data.answer);
  } catch (error) {
    console.error(error);
    appendChatMessage("assistant", `Chat request failed: ${error.message}`);
  } finally {
    submit.disabled = false;
    elements.chatInput.focus();
  }
});

elements.aiKeyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearAiMessage();
  const apiKey = elements.aiApiKey.value.trim();
  if (!apiKey) {
    showAiMessage("Paste a Groq API key before saving.", "error");
    return;
  }

  const submit = elements.aiKeyForm.querySelector("button");
  submit.disabled = true;
  submit.textContent = "Testing…";

  try {
    const response = await apiFetch("/api/ai-settings/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    });
    const data = await readJson(response);
    elements.aiApiKey.value = "";
    showAiMessage(`API key saved and tested. ${data.confirmation}`, "good");
    await refreshAiSettings();
  } catch (error) {
    console.error(error);
    showAiMessage(error.message, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Save and test";
  }
});

elements.aiEnabled.addEventListener("change", async () => {
  const requestedState = elements.aiEnabled.checked;
  elements.aiEnabled.disabled = true;
  clearAiMessage();

  try {
    const response = await apiFetch("/api/ai-settings/enabled", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: requestedState }),
    });
    const data = await readJson(response);
    showAiMessage(
      data.enabled ? "Remote AI enabled." : "Remote AI disabled; local rules remain active.",
      "good"
    );
    await refreshAiSettings();
  } catch (error) {
    console.error(error);
    elements.aiEnabled.checked = !requestedState;
    showAiMessage(error.message, "error");
    await refreshAiSettings();
  }
});

elements.aiTest.addEventListener("click", async () => {
  elements.aiTest.disabled = true;
  elements.aiTest.textContent = "Testing…";
  clearAiMessage();

  try {
    const response = await apiFetch("/api/ai-settings/test", { method: "POST" });
    const data = await readJson(response);
    showAiMessage(`Connection test passed. ${data.confirmation}`, "good");
    await refreshAiSettings();
  } catch (error) {
    console.error(error);
    showAiMessage(error.message, "error");
    await refreshAiSettings();
  } finally {
    elements.aiTest.textContent = "Test active key";
  }
});

elements.aiRemove.addEventListener("click", async () => {
  if (!window.confirm("Remove the saved Groq API key and disable Remote AI?")) return;

  elements.aiRemove.disabled = true;
  clearAiMessage();

  try {
    const response = await apiFetch("/api/ai-settings/key", { method: "DELETE" });
    await readJson(response);
    elements.aiApiKey.value = "";
    showAiMessage("API key removed. Remote AI is disabled.", "good");
    await refreshAiSettings();
  } catch (error) {
    console.error(error);
    showAiMessage(error.message, "error");
    await refreshAiSettings();
  }
});

Promise.all([refreshDashboard(), refreshAiSettings()]).catch(console.error);
window.setInterval(refreshDashboard, refreshIntervalMs);
window.setInterval(refreshAiSettings, refreshIntervalMs);
