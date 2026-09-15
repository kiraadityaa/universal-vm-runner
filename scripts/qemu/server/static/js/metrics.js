/* Real-time metrics rendering: instrument readouts + sparkline canvases. */
"use strict";

const Metrics = (() => {
  const cpuHistory = [];
  const diskHistory = [];
  const MAX_POINTS = 120;
  let startedAt = Date.now();

  function drawSpark(canvas, data, color) {
    if (!canvas || !data.length) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width = canvas.clientWidth || 200;
    const h = canvas.height = canvas.clientHeight || 34;
    ctx.clearRect(0, 0, w, h);

    const max = Math.max(1, ...data);
    const step = w / MAX_POINTS;
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = i * step;
      const y = h - (v / max) * (h - 4) - 2;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.4;
    ctx.stroke();

    // faint fill
    ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
    ctx.fillStyle = hexA(color, 0.12);
    ctx.fill();
  }

  function hexA(hex, a) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  function scaleClass(v) {
    if (v > 85) return "danger";
    if (v > 60) return "warn";
    return "ok";
  }

  function render(m) {
    const status = m.status || {};
    const running = !!status.running;

    // Power state
    const glow = UI.qs("#state-glow");
    const stateText = UI.qs("#state-text");
    if (glow && stateText) {
      const st = String(status.status || "unknown").toLowerCase();
      glow.className = "glow " + (st === "running" ? "ok" : (st === "paused" ? "warn" : (st === "shutdown" || st === "prelaunch" ? "off" : "bad")));
      stateText.textContent = st;
    }

    // Uptime (we estimate from process start or first metric arrival)
    const uptimeS = m.uptime_s || Math.floor((Date.now() - startedAt) / 1000);
    UI.setText("uptime-val", UI.fmtDuration(uptimeS));

    // CPU
    const cpu = m.cpu_percent || 0;
    UI.setText("cpu-val", Math.round(cpu));
    const cpuFill = UI.qs("#cpu-fill");
    if (cpuFill) { cpuFill.style.width = Math.min(100, cpu) + "%"; cpuFill.className = "fill " + scaleClass(cpu); }

    // RAM
    const ram = m.ram_used_gb ?? 0;
    const ramTotal = Number((window.__vmConfig && window.__vmConfig.VM_MEMORY) || "8G".replace(/[^0-9]/g, "") || 8);
    const ramPct = Math.min(100, ((ram / Math.max(1, ramTotal)) * 100));
    UI.setText("ram-val", ram > 0 ? ram.toFixed(1) : "–");
    const ramFill = UI.qs("#ram-fill");
    if (ramFill) { ramFill.style.width = ramPct + "%"; ramFill.className = "fill " + scaleClass(ramPct); }

    // Disk written
    const diskUsedBytes = (m.disk_used_gb || 0) * 1024 * 1024 * 1024;
    UI.setText("disk-val", diskUsedBytes > 0 ? UI.fmtBytes(diskUsedBytes).replace(/\sB?$/, "") : "0");

    // vCPUs info
    const vcpu = Array.isArray(m.cpus) ? m.cpus.length : 0;
    UI.setText("vcpu-val", vcpu ? `${vcpu} vcpu${vcpu !== 1 ? "s" : ""} (QEMU)` : "–");

    // History
    cpuHistory.push(cpu);
    diskHistory.push(Math.max(0, diskUsedBytes / (1024 * 1024)));
    if (cpuHistory.length > MAX_POINTS) cpuHistory.shift();
    if (diskHistory.length > MAX_POINTS) diskHistory.shift();

    drawSpark(UI.qs("#cpu-spark"), cpuHistory, "#e8ab3c");
    drawSpark(UI.qs("#disk-spark"), diskHistory, "#6ea8e0");
  }

  function setStartedAt(t) { startedAt = t; }

  return { render, setStartedAt };
})();