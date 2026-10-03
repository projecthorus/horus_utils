"use strict";

const socket = io();
const payloads = new Map();
const logs = [];
const uplinks = [];
let selectedId = null;
let lastPacket = null;

const byId = (id) => document.getElementById(id);
const text = (id, value) => { byId(id).textContent = value ?? "—"; };
const value = (item, unit = "") => item === null || item === undefined ? "—" : `${item}${unit}`;
const decimal = (item, digits) => typeof item === "number" ? item.toFixed(digits) : "—";
const time = (item) => item ? item.replace("T", " ").replace(/(\+00:00|Z)$/, " UTC") : "—";

function renderPayloads() {
  const list = byId("payload-list");
  list.replaceChildren();
  const entries = [...payloads.values()].sort((a, b) => a.id - b.id);
  text("payload-count", entries.length);
  if (entries.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Waiting for valid radio packets…";
    list.append(empty);
  }
  for (const payload of entries) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `payload-button${payload.id === selectedId ? " selected" : ""}`;
    button.setAttribute("aria-pressed", payload.id === selectedId ? "true" : "false");
    const id = document.createElement("strong");
    id.textContent = `Payload ${payload.id}`;
    const detail = document.createElement("small");
    detail.textContent = payload.heard_at ? time(payload.heard_at) : "Heard";
    button.append(id, detail);
    button.addEventListener("click", () => selectPayload(payload.id));
    list.append(button);
  }
}

function selectPayload(id) {
  selectedId = id;
  renderPayloads();
  renderSelected();
}

function renderSelected() {
  const payload = payloads.get(selectedId);
  text("selected-id", payload ? `#${selectedId}` : "—");
  byId("send-button").disabled = !payload || !socket.connected;
  const telemetry = payload?.telemetry;
  text("telemetry-kind", telemetry?.kind ? `${telemetry.kind} packet` : "—");
  text("position-time", telemetry?.time);
  text("position-lat", telemetry ? decimal(telemetry.latitude, 5) + "°" : "—");
  text("position-lon", telemetry ? decimal(telemetry.longitude, 5) + "°" : "—");
  text("position-alt", value(telemetry?.altitude_m, " m"));
  text("position-speed", value(telemetry?.speed_kmh, " km/h"));
  text("position-sats", telemetry?.satellites);
  text("telem-counter", telemetry?.counter);
  text("telem-battery", value(telemetry?.battery_v, " V"));
  text("telem-pyro", value(telemetry?.pyro_v, " V"));
  text("telem-temp", value(telemetry?.temperature_c, " °C"));
  text("telem-received", telemetry?.received_packets);
  text("telem-noise", value(telemetry?.noise_floor_dbm, " dBm"));
  text("telem-slot", telemetry?.current_slot === undefined ? "—" : `${telemetry.current_slot} / ${telemetry.used_slots}`);
  renderUplinks();
}

function renderPacket(packet) {
  text("packet-crc", packet ? (packet.crc_ok ? "CRC OK" : "CRC FAIL") : "—");
  text("packet-time", time(packet?.timestamp));
  text("packet-id", packet?.payload_id);
  text("packet-type", packet?.type);
  text("packet-signal", packet ? `${value(packet.rssi_dbm, " dBm")} / ${value(packet.snr_db, " dB")}` : "—");
  text("packet-error", value(packet?.freq_error_hz, " Hz"));
  text("packet-detail", packet ? `${packet.length} bytes / ${packet.repeated ? "yes" : "no"}` : "—");
}

function renderStatus(status) {
  text("radio-time", time(status?.time));
  text("radio-frequency", value(status?.frequency_mhz, " MHz"));
  text("radio-rssi", value(status?.rssi_dbm, " dBm"));
  text("radio-queue", status?.queue_size);
}

function renderEvents(elementId, entries, emptyMessage) {
  const list = byId(elementId);
  list.replaceChildren();
  if (entries.length === 0) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = emptyMessage;
    list.append(item);
    return;
  }
  for (const entry of [...entries].reverse()) {
    const item = document.createElement("li");
    const head = document.createElement("div");
    head.className = "event-head";
    const label = document.createElement("strong");
    label.textContent = entry.stage || entry.kind;
    const stamp = document.createElement("time");
    stamp.textContent = time(entry.time);
    const message = document.createElement("p");
    message.textContent = entry.message;
    head.append(label, stamp);
    item.append(head, message);
    if (entry.stage === "ACK") {
      const signal = document.createElement("small");
      signal.textContent = `Payload measured ${value(entry.rssi_dbm, " dBm")} / ${value(entry.snr_db, " dB")}`;
      item.append(signal);
    }
    list.append(item);
  }
}

function renderUplinks() {
  renderEvents("uplink-list", uplinks.filter((entry) => entry.payload_id === selectedId || entry.payload_id === null), "No uplink activity for this payload.");
}

function setConnection(connected) {
  const indicator = byId("connection");
  indicator.className = `connection ${connected ? "online" : "offline"}`;
  indicator.textContent = connected ? "Web connected" : "Disconnected · reconnecting";
  renderSelected();
}

socket.on("connect", () => setConnection(true));
socket.on("disconnect", () => setConnection(false));
socket.on("connect_error", () => setConnection(false));
socket.on("snapshot", (state) => {
  payloads.clear();
  for (const payload of state.payloads || []) payloads.set(payload.id, payload);
  logs.splice(0, logs.length, ...(state.log || []));
  uplinks.splice(0, uplinks.length, ...(state.uplinks || []));
  if (!payloads.has(selectedId)) selectedId = payloads.size ? payloads.keys().next().value : null;
  renderPayloads();
  renderSelected();
  lastPacket = state.last_packet;
  renderPacket(lastPacket);
  renderStatus(state.status);
  renderEvents("status-list", logs, "Waiting for UDP messages…");
});
socket.on("payload_update", (payload) => {
  payloads.set(payload.id, payload);
  if (selectedId === null) selectedId = payload.id;
  renderPayloads();
  if (selectedId === payload.id) renderSelected();
});
socket.on("station_status", renderStatus);
socket.on("last_packet", (packet) => { lastPacket = packet; renderPacket(packet); });
socket.on("log_entry", (entry) => {
  logs.push(entry);
  if (logs.length > 150) logs.shift();
  renderEvents("status-list", logs, "Waiting for UDP messages…");
});
socket.on("uplink_event", (entry) => {
  uplinks.push(entry);
  if (uplinks.length > 60) uplinks.shift();
  renderUplinks();
});

byId("command").addEventListener("change", () => {
  const cutdown = byId("command").value === "cutdown";
  text("value-label", cutdown ? "Cutdown duration (1–10 s)" : "Ping value (0–255)");
  const input = byId("command-value");
  input.min = cutdown ? "1" : "0";
  input.max = cutdown ? "10" : "255";
  input.value = cutdown ? "4" : String(Math.floor(Math.random() * 256));
  text("send-button", cutdown ? "Send Cutdown" : "Send Ping");
});

byId("command-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (selectedId === null || !socket.connected) return;
  const command = byId("command").value;
  const value = Number(byId("command-value").value);
  const password = byId("uplink-code").value;
  const confirmed = command === "cutdown" ? window.confirm(
    `Send CUTDOWN to payload #${selectedId} for ${value} seconds? This will activate the cutdown output.`
  ) : false;
  if (command === "cutdown" && !confirmed) return;
  const button = byId("send-button");
  button.disabled = true;
  text("command-feedback", "Sending request to UDP gateway…");
  socket.timeout(5000).emit("send_command", {command, value, password, payload_id: selectedId, confirmed}, (error, response) => {
    button.disabled = !socket.connected || selectedId === null;
    text("command-feedback", error ? "No response from web server." : (response?.message || response?.error || "Unknown result"));
  });
});
