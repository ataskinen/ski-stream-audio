const form = document.querySelector("#settings");
const $ = (s) => document.querySelector(s);
let config = null;
let busy = false;
let dirty = false;
const bools = ["autostart", "send_mute", "receive_mute"];
const numbers = [
  "device_latency_seconds",
  "peer_port",
  "listen_port",
  "source_port",
  "input_channels",
  "output_channels",
  "send_gain",
  "receive_gain",
  "jitter_packets",
  "max_packets",
  "timeout_seconds",
  "retry_seconds",
];
async function api(path, value) {
  const opts =
    value === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Ski-Audio": "1" },
          body: JSON.stringify(value),
        };
  const response = await fetch(`/api/${path}`, opts);
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ error: `HTTP ${response.status}` }));
    throw Error(body.error);
  }
  return response.json();
}
function changed(value = true) {
  dirty = value;
  $("#dirty").textContent = dirty ? "Unsaved changes" : "";
  for (const side of ["send", "receive"])
    $("#" + side + "-gain-value").textContent =
      Math.round(form.elements[side + "_gain"].value * 100) + "%";
  $("#send-fields").classList.toggle(
    "inactive",
    form.elements.mode.value === "receive",
  );
  $("#receive-fields").classList.toggle(
    "inactive",
    form.elements.mode.value === "send",
  );
}
function setOptions(key, devices, current) {
  const select = form.elements[key];
  select.replaceChildren();
  const values = new Set();
  const add = (value, label) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = label;
    select.append(option);
    values.add(String(value));
  };
  add("", "Not selected");
  if (key === "input_device") add("Test tone", "Test tone · quiet 1 kHz");
  const kind =
    key === "input_device" ? "max_input_channels" : "max_output_channels";
  devices
    .filter((d) => d[kind] > 0)
    .forEach((d) => add(d.name, `${d.name} · ${d[kind]} channels`));
  if (!values.has(String(current)))
    add(current, `${current} (configured, unavailable or index)`);
  select.value = String(current);
}
async function refresh() {
  const devices = await api("devices");
  for (const key of ["input_device", "output_device"])
    setOptions(key, devices, form.elements[key].value || config[key]);
  $("#notice").textContent =
    "Device list refreshed. Select devices and channel counts, then Save and apply.";
}
function fill(c) {
  for (const element of form.elements) {
    if (!element.name || !(element.name in c)) continue;
    if (bools.includes(element.name)) element.checked = c[element.name];
    else if (element.tagName === "SELECT" && element.name.endsWith("_device"))
      setOptions(element.name, [], c[element.name]);
    else
      element.value = Array.isArray(c[element.name])
        ? c[element.name].join(", ")
        : c[element.name];
  }
  changed(false);
}
function gather() {
  const c = { ...config };
  for (const element of form.elements) {
    const key = element.name;
    if (!key) continue;
    if (bools.includes(key)) c[key] = element.checked;
    else if (numbers.includes(key)) c[key] = Number(element.value);
    else if (key.endsWith("_map"))
      c[key] = element.value.split(",").map((v) => Number(v.trim()));
    else c[key] = element.value;
  }
  // Preserve numeric device IDs when an existing config uses one.
  for (const key of ["input_device", "output_device"])
    if (typeof config[key] === "number" && String(config[key]) === c[key])
      c[key] = config[key];
  return c;
}
async function task(fn) {
  if (busy) return;
  busy = true;
  document.querySelectorAll("button").forEach((b) => (b.disabled = true));
  $("#error").textContent = "";
  try {
    await fn();
  } catch (e) {
    $("#error").textContent = e.message;
  } finally {
    busy = false;
    document.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}
form.addEventListener("input", () => changed());
form.addEventListener("submit", (e) => {
  e.preventDefault();
  task(async () => {
    await api("config", gather());
    config = await api("config");
    fill(config);
    $("#notice").textContent = "Settings saved and applied.";
  });
});
for (const action of ["start", "stop", "tone"])
  $("#" + action).onclick = () =>
    task(async () => {
      if (dirty && action !== "stop")
        throw Error("Save your settings before starting audio or a test.");
      await api(action, {});
      $("#notice").textContent =
        action === "tone"
          ? "Playing a quiet local test tone for three seconds."
          : `${action === "start" ? "Starting" : "Stopping"} audio…`;
    });
$("#refresh").onclick = () => task(refresh);
async function poll() {
  try {
    const s = await api("status");
    const m = s.metrics;
    $("#state").textContent = s.testing
      ? "Testing local output"
      : s.running
        ? m.mode === "send"
          ? "Sending audio"
          : m.link === "receiving"
            ? "Receiving audio"
            : "Waiting for audio"
        : s.desired
          ? "Restarting audio"
          : "Audio stopped";
    $("#details").textContent =
      `Sent ${m.sent || 0} · Received ${m.received || 0} · Missing ${m.missing || 0} · Dropped ${m.dropped || 0} · Device warnings ${m.audio_warnings || 0}`;
    $("#send-level").value = m.send_peak || 0;
    $("#receive-level").value = m.receive_peak || 0;
    $("#logs").textContent = s.log.join("\n") || "No activity yet.";
    if (s.last_error)
      $("#details").textContent += " · Last error: " + s.last_error;
  } catch (e) {
    $("#state").textContent = "Control panel disconnected";
    $("#details").textContent = e.message;
  }
  setTimeout(poll, 1000);
}
task(async () => {
  config = await api("config");
  fill(config);
  await refresh();
}).then(poll);
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
