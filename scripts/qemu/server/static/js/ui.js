/* UI utilities: toasts, formatting, DOM helpers. */
"use strict";

const UI = (() => {
  function toast(text, kind = "") {
    const wrap = document.getElementById("toast-wrap");
    if (!wrap) return;
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = text;
    wrap.appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity 300ms";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 300);
    }, 3000);
  }

  function fmtBytes(bytes) {
    if (bytes == null || isNaN(bytes)) return "0 B";
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let v = bytes / 1024;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return v.toFixed(1) + " " + units[i];
  }

  function fmtDuration(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(h)}:${pad(m)}:${pad(s)}`;
  }

  function fmtClock() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function $el(tag, attrs, children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const k of Object.keys(attrs)) {
        if (k === "className") el.className = attrs[k];
        else if (k === "text") el.textContent = attrs[k];
        else if (k === "html") el.innerHTML = attrs[k];
        else el.setAttribute(k, attrs[k]);
      }
    }
    (children || []).forEach((c) => el.appendChild(c));
    return el;
  }

  return { toast, fmtBytes, fmtDuration, fmtClock, setText, qs, qsa, $el };
})();