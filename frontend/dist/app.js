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
    const detail = data.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d) => d.msg).join(", ")
      : detail || data.message || res.statusText;
    throw new Error(msg);
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
  await loadDeviceStats();
}

function statBar(label, usedPct, detail) {
  const pct = Math.min(100, Math.max(0, Number(usedPct) || 0));
  return `
    <div class="stat-block">
      <div class="stat-head">
        <span>${label}</span>
        <span class="muted">${detail}</span>
      </div>
      <div class="stat-track"><div class="stat-fill" style="width:${pct}%"></div></div>
    </div>`;
}

function stateLabel(stat) {
  if (stat.includes("R")) return "Running";
  if (stat.includes("S")) return "Sleeping";
  if (stat.includes("D")) return "Waiting";
  if (stat.includes("Z")) return "Zombie";
  return stat;
}

async function loadDeviceStats() {
  if (!state.serial) return;
  $("device-stats").innerHTML = '<p class="loading">Loading memory and storage…</p>';
  const stats = await api(`/api/device/${encodeURIComponent(state.serial)}/stats`);
  const mem = stats.memory;
  const primary = stats.storage?.primary;
  const proc = stats.processes;

  let storageHtml = "";
  if (primary) {
    storageHtml = statBar(
      `Storage (${primary.mount})`,
      primary.use_percent,
      `${primary.used} used · ${primary.available} free · ${primary.total} total`
    );
  }

  const fg = proc.foreground_app
    ? `<p class="muted foreground-app">Foreground app: <code>${escapeHtml(proc.foreground_app)}</code></p>`
    : "";

  $("device-stats").innerHTML = `
    <div class="stats-grid">
      ${statBar("Memory", mem.used_percent, `${mem.used} used · ${mem.available} free · ${mem.total} total`)}
      ${storageHtml}
    </div>
    <p class="process-meta">${proc.total} processes · ${proc.running} running (active)</p>
    ${fg}
  `;

  $("process-summary").textContent = `(${proc.total} total, ${proc.running} running)`;
  const tbody = $("process-table").querySelector("tbody");
  tbody.innerHTML = (proc.top || [])
    .map(
      (p) => `
    <tr class="${p.stat.includes("R") ? "proc-running" : ""}">
      <td class="proc-name" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</td>
      <td>${escapeHtml(p.pid)}</td>
      <td>${stateLabel(p.stat)}</td>
    </tr>`
    )
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

function statusBadge(status) {
  const labels = {
    enabled: "Enabled",
    disabled: "Disabled",
    uninstalled: "Uninstalled",
  };
  return `<span class="badge badge-${status}">${labels[status] || status}</span>`;
}

function typeBadge(type) {
  const label = type === "system" ? "System" : "User";
  return `<span class="badge badge-type">${label}</span>`;
}

function actionButtons(pkg) {
  const buttons = [
    `<button class="small" data-action="enable" data-pkg="${pkg.package}">Enable</button>`,
    `<button class="small" data-action="disable" data-pkg="${pkg.package}">Disable</button>`,
    `<button class="danger" data-action="uninstall" data-pkg="${pkg.package}">Uninstall</button>`,
  ];
  if (pkg.status === "uninstalled") {
    buttons.unshift(
      `<button class="small btn-restore" data-action="restore" data-pkg="${pkg.package}">Restore</button>`
    );
  }
  return buttons.join("");
}

async function loadPackages() {
  if (!state.serial) return;

  const params = new URLSearchParams();
  params.set("status", $("status-filter").value);
  params.set("app_type", $("type-filter").value);
  const q = $("pkg-filter").value.trim();
  if (q) params.set("q", q);
  if ($("refresh-labels").checked) params.set("refresh_labels", "true");

  $("btn-load-packages").disabled = true;
  $("pkg-loading").classList.remove("hidden");
  $("pkg-count").textContent = "";

  try {
    const { packages, count } = await api(
      `/api/device/${encodeURIComponent(state.serial)}/packages?${params}`
    );
    $("pkg-count").textContent = `${count} app(s)`;
    const tbody = $("pkg-table").querySelector("tbody");
    if (!packages.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted">No packages match your filters.</td></tr>';
      return;
    }
    tbody.innerHTML = packages
      .map(
        (p) => `
    <tr title="${escapeHtml(p.package)}">
      <td class="col-app">
        <strong>${escapeHtml(p.label)}</strong>
        <span class="pkg-id">${escapeHtml(p.package)}</span>
      </td>
      <td>${typeBadge(p.type)}</td>
      <td>${statusBadge(p.status)}</td>
      <td class="actions">${actionButtons(p)}</td>
    </tr>`
      )
      .join("");

    tbody.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => packageAction(btn.dataset.action, btn.dataset.pkg));
    });
  } finally {
    $("btn-load-packages").disabled = false;
    $("pkg-loading").classList.add("hidden");
  }
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function packageAction(action, pkg) {
  if (!state.serial) return;
  const labels = {
    disable: "Disable",
    enable: "Enable",
    uninstall: "Uninstall",
    restore: "Restore",
  };
  if (!confirm(`${labels[action]} ${pkg}?`)) return;

  const endpoint = action === "restore" ? "/api/package/restore" : `/api/package/${action}`;
  const data = await api(endpoint, {
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
$("btn-refresh-stats").addEventListener("click", () =>
  loadDeviceStats().catch((e) => toast(e.message, "error"))
);

$("pkg-filter").addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadPackages().catch((err) => toast(err.message, "error"));
});

refreshDevices().catch(() => {});
