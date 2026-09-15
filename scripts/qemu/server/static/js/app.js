/* Universal VM Runner — main application logic. */
"use strict";

(() => {
  // ----------------------------------------------------------------
  // Global state
  // ----------------------------------------------------------------
  let installerState = { state: "idle", detail: "waiting for VM", progress: null, boot_attempt: 0 };
  let bootStartedAt = Date.now();

  // ----------------------------------------------------------------
  // Clock
  // ----------------------------------------------------------------
  setInterval(() => {
    UI.setText("clock", UI.fmtClock());
    UI.setText("rail-time", UI.fmtClock());
  }, 1000);

  // ----------------------------------------------------------------
  // Navigation
  // ----------------------------------------------------------------
  function showView(name) {
    UI.qsa(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    const titles = {
      console: "VM Display",
      terminal: "Serial Terminal",
      snapshots: "Snapshots",
      config: "Configuration",
    };
    UI.setText("page-title", titles[name] || name);

    UI.qsa(".view").forEach((v) => {
      const on = v.id === `view-${name}`;
      v.classList.toggle("active", on);
      v.style.display = on ? "" : "none";
    });

    if (name === "snapshots") loadSnapshots();
    if (name === "config") loadConfig();
  }

  UI.qsa(".nav-item").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

  // ----------------------------------------------------------------
  // VM display (noVNC iframe)
  // ----------------------------------------------------------------
  function bootConsole() {
    const screen = UI.qs("#vm-screen");
    const placeholder = UI.qs("#vm-placeholder");
    if (!screen) return;

    const iframe = document.createElement("iframe");
    iframe.id = "vm-frame";
    iframe.allow = "clipboard-read; clipboard-write";
    // noVNC served from same origin; it will connect to /ws/vnc (aiohttp -> qemu VNC).
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const query = [
      "autoconnect=true",
      "resize=scale",
      "reconnect=true",
      "reconnect_delay=3000",
      `host=${location.hostname}`,
      `port=${location.port || (location.protocol === "https:" ? "443" : "80")}`,
      "path=ws/vnc",
      "shared=true",
    ].join("&");
    iframe.src = `/vendor/novnc/vnc.html?${query}`;
    iframe.onload = () => {
      if (placeholder) placeholder.remove();
    };
    placeholder.innerHTML = "Starting console&hellip;";
    screen.appendChild(iframe);
  }

  // ----------------------------------------------------------------
  // Toolbar actions
  // ----------------------------------------------------------------
  async function post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  UI.qs("#vm-toolbar").addEventListener("click", async (e) => {
    const btn = e.target.closest(".tool-btn");
    if (!btn || btn.disabled) return;
    const action = btn.dataset.action;
    try {
      if (action === "reset") {
        btn.disabled = true; await post("/api/vm/power/reset"); UI.toast("Reset sent via ACPI", "ok");
        btn.disabled = false;
      } else if (action === "resume") {
        await post("/api/vm/control/resume"); UI.toast("VM resumed", "ok");
      } else if (action === "pause") {
        await post("/api/vm/control/pause"); UI.toast("VM paused");
      } else if (action === "powerdown") {
        if (!confirm("Send ACPI power-off to the VM?")) return;
        await post("/api/vm/power/powerdown"); UI.toast("Power-off signal sent");
      } else if (action === "screenshot") {
        await post("/api/vm/screendump");
        window.open("/api/vm/screenshot", "_blank");
        UI.toast("Screenshot captured", "ok");
      } else if (action === "snapshot") {
        const tag = prompt("Snapshot tag:", `snap-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}`);
        if (!tag) return;
        await post("/api/vm/snapshot", { tag });
        UI.toast("Snapshot created", "ok");
        loadSnapshots();
      } else if (action && action.startsWith("key ")) {
        const keys = action.slice(4).split(/\s*,\s*/);
        await post("/api/vm/send-key", { keys });
        UI.toast(`Sent: ${keys.join(" + ")}`, "ok");
      }
    } catch (err) {
      UI.toast(err.message || "Action failed", "bad");
    }
  });

  // ----------------------------------------------------------------
  // Status / metrics wiring
  // ----------------------------------------------------------------
  function applyVmState(status) {
    const tag = UI.qs("#vm-status-tag");
    const beacon = UI.qs("#rail-beacon");
    const railState = UI.qs("#rail-state");
    const glow = UI.qs("#state-glow");
    const stateText = UI.qs("#state-text");

    const st = String((status && status.status) || "unknown").toLowerCase();
    const cls = st === "running" ? "ok" : st === "paused" ? "warn" : st === "shutdown" || st === "prelaunch" ? "off" : "bad";
    if (tag) { tag.textContent = st; tag.className = "vm-status-tag " + cls; }
    if (beacon) beacon.className = "beacon-dot " + (cls === "off" ? "off" : cls);
    if (railState) railState.textContent = "vm: " + st;
    if (glow) glow.className = "glow " + cls;
    if (stateText) stateText.textContent = st;

    if (st === "running") {
      UI.qs("#qmp-badge").textContent = "qmp: online";
      UI.qs("#qmp-badge").style.color = "var(--ok)";
    } else if (st === "shutdown" || st === "prelaunch") {
      UI.qs("#qmp-badge").textContent = "qmp: offline";
      UI.qs("#qmp-badge").style.color = "var(--text-low)";
    } else {
      UI.qs("#qmp-badge").textContent = "qmp: " + st;
      UI.qs("#qmp-badge").style.color = "var(--warn)";
    }
  }

  function applyInstaller(data) {
    installerState = data || installerState;
    const fill = UI.qs("#inst-fill");
    const val = UI.qs("#inst-val");
    if (!fill || !val) return;

    const map = {
      idle: { label: "idle — waiting", pct: 0, cls: "warn" },
      booting: { label: "booting…", pct: 15, cls: "warn" },
      installing: { label: `installing… ${data.progress != null ? data.progress + "%" : ""}`, pct: data.progress != null ? data.progress : 40, cls: "warn" },
      ready: { label: "ready — booted from disk", pct: 100, cls: "ok" },
      failed: { label: "failed — " + (data.detail || "no bootable device"), pct: 100, cls: "danger" },
      unknown: { label: "unknown — " + (data.detail || ""), pct: 30, cls: "warn" },
    };
    const m = map[data.state] || map.unknown;
    fill.style.width = m.pct + "%";
    fill.className = "fill " + m.cls;
    val.textContent = m.label;
    val.style.color = m.cls === "ok" ? "var(--ok)" : m.cls === "danger" ? "var(--danger)" : "";
  }

  WS.onStatus((msg) => {
    if (msg.type === "status") applyVmState(msg.status);
    else if (msg.type === "metrics") Metrics.render(msg.data);
    else if (msg.type === "installer") applyInstaller(msg.data);
    else if (msg.type === "event") {
      const ev = msg.event;
      installEventHandlers(ev);
    }
  });

  function installEventHandlers(ev) {
    if (ev === "RESET" || ev === "STOP") {
      UI.toast("VM event: " + ev, "warn");
    } else if (ev === "SHUTDOWN") {
      UI.toast("VM shut down", "warn");
    } else if (ev === "GUEST_PANICKED") {
      UI.toast("Guest kernel panic detected", "bad");
    } else if (ev === "RESUME") {
      UI.toast("VM resumed", "ok");
    }
  }

  // ----------------------------------------------------------------
  // Snapshots
  // ----------------------------------------------------------------
  async function loadSnapshots() {
    try {
      const res = await fetch("/api/vm/snapshots");
      const data = await res.json();
      const body = UI.qs("#snap-body");
      const snaps = data.snapshots || [];
      if (!snaps.length) {
        body.innerHTML = '<tr><td colspan="5" class="empty">No snapshots yet. Click "create snapshot".</td></tr>';
        return;
      }
      body.innerHTML = "";
      snaps.forEach((s) => {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${s.id}</td>
          <td>${s.tag}</td>
          <td>${s.vm_size}</td>
          <td>${s.date}</td>
          <td style="text-align:right">
            <button class="tool-btn" data-snap="${s.id}">…</button>
          </td>`;
        body.appendChild(row);
      });
    } catch (err) {
      UI.toast("Failed to load snapshots: " + err.message, "bad");
    }
  }

  UI.qs("#snap-create").addEventListener("click", async () => {
    const tag = prompt("Snapshot tag:", `snap-${Date.now()}`);
    if (!tag) return;
    try { await post("/api/vm/snapshot", { tag }); UI.toast("Snapshot created", "ok"); loadSnapshots(); }
    catch (e) { UI.toast(e.message, "bad"); }
  });
  UI.qs("#snap-refresh").addEventListener("click", loadSnapshots);

  // ----------------------------------------------------------------
  // Config view
  // ----------------------------------------------------------------
  async function loadConfig() {
    try {
      const res = await fetch("/api/config");
      const cfg = await res.json();
      const grid = UI.qs("#config-grid");
      grid.innerHTML = "";
      Object.entries(cfg).forEach(([k, v]) => {
        if (k.endsWith("_DISPLAY") || k.startsWith("ISO_URL_DISPLAY")) return;
        grid.appendChild(UI.$el("div", { className: "kv" }, [
          UI.$el("div", { className: "k", text: k }),
          UI.$el("div", { className: "v", text: String(v) }),
        ]));
      });
      window.__vmConfig = cfg;
    } catch (_) {}

    // Installer state JSON
    try {
      const res = await fetch("/api/vm/installer");
      const data = await res.json();
      UI.setText("installer-json", JSON.stringify(data, null, 2));
    } catch (_) {}
  }

  // ----------------------------------------------------------------
  // Terminal modes
  // ----------------------------------------------------------------
  UI.qsa(".console-tabs").forEach((tabs) => {
    UI.qsa(".tab", tabs).forEach((t) => {
      t.addEventListener("click", () => Serial.setMode(t.dataset.mode));
    });
  });
  const termClear = UI.qs("#term-clear");
  if (termClear) termClear.addEventListener("click", () => Serial.clearTerminal());

  // ----------------------------------------------------------------
  // Boot
  // ----------------------------------------------------------------
  async function init() {
    Serial.initConsoles();
    bootConsole();
    WS.connect();
    Metrics.setStartedAt(Date.now());
    // Initial fetches
    try {
      const res = await fetch("/api/vm/status");
      const data = await res.json();
      applyVmState(data.status);
    } catch (_) {}
    try {
      const res = await fetch("/api/vm/installer");
      const data = await res.json();
      applyInstaller(data);
    } catch (_) {}
    try {
      const res = await fetch("/api/config");
      const cfg = await res.json();
      window.__vmConfig = cfg;
      const mem = cfg.VM_MEMORY || "";
      const cpu = cfg.VM_CPUS || "";
      UI.setText("top-cfg", `${mem} RAM · ${cpu} vCPU`);
    } catch (_) {}
  }

  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
})();