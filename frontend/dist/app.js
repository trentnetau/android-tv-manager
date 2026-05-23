const state = { serial: null };

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || res.statusText);
  }
  return data;
}

function toast(msg, type = "success") {
  const el = $("toast");
  el.textContent = msg;
  el.className = `toast ${type}`;
  setTimeout(() => el.classList.add("hidden"), 4000);
}

function showSections(visible) {
  ["device-section", "packages-section", "sideload-section", "shell-section"].forEach((id) => {
    $(id).classList.toggle("hidden", !visible);
  });
}

function renderDevices(devices) {
  const container = $("devices");
  if (!devices.length) {
    container.innerHTML = '<p class="muted">No devices. Connect to your TV IP above.</p>';
    return;
  }
  container.innerHTML = devices
    .map(
      (d) => `
    <div class="device-chip ${state.serial === d.serial ? "selected" : ""}" data-serial="${d.serial}">
      <div>
        <strong>${d.model || d.serial}</strong>
        <div class="muted">${d.serial}</div>
      </div>
      <span class="state ${d.state === "device" ? "" : "offline"}">${d.state}</span>
    </div>`
    )
    .join("");

  container.querySelectorAll(".device-chip").forEach((chip) => {
    chip.addEventListener("click", () => selectDevice(chip.dataset.serial));
  });
}

async function refreshDevices() {
  const { devices } = await api("/api/devices");
  renderDevices(devices);
  if (state.serial && !devices.find((d) => d.serial === state.serial && d.state === "device")) {
    state.serial = null;
    showSections(false);
  }
}

async function selectDevice(serial) {
  state.serial = serial;
  await refreshDevices();
  showSections(true);
  const info = await api(`/api/device/${encodeURIComponent(serial)}/info`);
  $("device-info").innerHTML = Object.entries(info)
    .map(([k, v]) => `<div><span>${k}</span>${v || "—"}</div>`)
    .join("");
}

async function connect() {
  const host = $("host").value.trim();
  const port = Number($("port").value) || 5555;
  if (!host) {
    toast("Enter your TV IP address", "error");
    return;
  }
  const data = await api("/api/connect", {
    method: "POST",
    body: JSON.stringify({ host, port }),
  });
  toast(data.message || "Connected");
  await refreshDevices();
  const online = data.devices?.[0];
  if (online) await selectDevice(online);
}

async function loadPackages() {
  if (!state.serial) return;
  const params = new URLSearchParams();
  if ($("third-party").checked) params.set("third_party", "true");
  if ($("disabled-only").checked) params.set("disabled", "true");
  const q = $("pkg-filter").value.trim();
  if (q) params.set("q", q);

  const { packages, count } = await api(
    `/api/device/${encodeURIComponent(state.serial)}/packages?${params}`
  );
  $("pkg-count").textContent = `${count} package(s)`;
  const tbody = $("pkg-table").querySelector("tbody");
  tbody.innerHTML = packages
    .map(
      (p) => `
    <tr>
      <td><code>${p.package}</code></td>
      <td class="actions">
        <button class="small" data-action="disable" data-pkg="${p.package}">Disable</button>
        <button class="small" data-action="enable" data-pkg="${p.package}">Enable</button>
        <button class="danger" data-action="uninstall" data-pkg="${p.package}">Uninstall</button>
      </td>
    </tr>`
    )
    .join("");

  tbody.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => packageAction(btn.dataset.action, btn.dataset.pkg));
  });
}

async function packageAction(action, pkg) {
  if (!state.serial) return;
  const labels = { disable: "Disable", enable: "Enable", uninstall: "Uninstall" };
  if (!confirm(`${labels[action]} ${pkg}?`)) return;

  const data = await api(`/api/package/${action}`, {
    method: "POST",
    body: JSON.stringify({ serial: state.serial, package: pkg }),
  });
  toast(data.result || "Done");
  await loadPackages();
}

async function installApk() {
  if (!state.serial) return;
  const file = $("apk-file").files[0];
  if (!file) {
    toast("Choose an APK file", "error");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  $("install-log").textContent = "Installing…";
  try {
    const res = await fetch(`/api/device/${encodeURIComponent(state.serial)}/install`, {
      method: "POST",
      body: form,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Install failed");
    $("install-log").textContent = data.result;
    toast("APK installed");
  } catch (e) {
    $("install-log").textContent = e.message;
    toast(e.message, "error");
  }
}

async function runShell() {
  if (!state.serial) return;
  const command = $("shell-cmd").value.trim();
  if (!command) return;
  const { output } = await api("/api/shell", {
    method: "POST",
    body: JSON.stringify({ serial: state.serial, command }),
  });
  $("shell-out").textContent = output;
}

$("btn-connect").addEventListener("click", () => connect().catch((e) => toast(e.message, "error")));
$("btn-refresh").addEventListener("click", () =>
  refreshDevices().catch((e) => toast(e.message, "error"))
);
$("btn-load-packages").addEventListener("click", () =>
  loadPackages().catch((e) => toast(e.message, "error"))
);
$("btn-install").addEventListener("click", () => installApk());
$("btn-shell").addEventListener("click", () => runShell().catch((e) => toast(e.message, "error")));

refreshDevices().catch(() => {});
