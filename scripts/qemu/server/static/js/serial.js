/* xterm.js serial console wiring + log view. */
"use strict";

const Serial = (() => {
  let term = null;
  let termFull = null;
  let fitAddon = null;
  let fitAddonFull = null;
  let conn = null;
  let connFull = null;
  const logBuffer = [];
  const LOG_MAX = 4000;

  function initConsoles() {
    if (!window.Terminal) {
      console.warn("xterm.js not loaded");
      return;
    }

    const common = {
      fontFamily: '"SF Mono", "JetBrains Mono", Menlo, Consolas, monospace',
      fontSize: 12,
      theme: {
        background: "#0e121b",
        foreground: "#59d1d1",
        cursor: "#e8ab3c",
        selectionBackground: "rgba(232,171,60,0.3)",
      },
      scrollback: 5000,
      convertEol: true,
    };

    term = new Terminal(common);
    termFull = new Terminal(common);
    fitAddon = new FitAddon.FitAddon();
    fitAddonFull = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    termFull.loadAddon(fitAddonFull);

    term.open(document.getElementById("serial-terminal"));
    termFull.open(document.getElementById("serial-terminal-full"));
    fitAddon.fit();
    fitAddonFull.fit();

    // The log-view elements (small + full) share the same buffer.
    connectTerminal(term, function onData(bytes) {
      appendLog(bytes);
      termFull && termFull.write(bytes);
    });
    connectTerminal(termFull, function onData(bytes) {
      appendLog(bytes);
      term && term.write(bytes);
    });

    // Redirect terminal writes to the shared log buffer too.
    const origWrite = term.write.bind(term);
    const origWriteFull = termFull.write.bind(termFull);
    term.write = (data) => { appendLog(data); origWrite(data); if (termFull) termFull.write(data); };
    termFull.write = (data) => { appendLog(data); origWriteFull(data); if (term) term.write(data); };

    window.addEventListener("resize", () => {
      try { fitAddon.fit(); } catch (_) {}
      try { fitAddonFull.fit(); } catch (_) {}
    });
  }

  function connectTerminal(t, onDataCb) {
    const c = WS.openSerial(() => {
      UI.toast("Serial console connected", "ok");
    });
    c.onData((bytes) => {
      if (onDataCb) onDataCb(bytes);
      try { t.write(bytes); } catch (_) {}
    });
    c.onClose(() => {
      UI.toast("Serial console disconnected — VM may be restarting", "warn");
    });
    const oldKey = t.onData ? t._keyHandler : null;
    t.onData((input) => {
      if (t === term) conn && conn.send(new TextEncoder().encode(input));
      if (t === termFull) connFull && connFull.send(new TextEncoder().encode(input));
    });
    if (t === term) conn = c;
    if (t === termFull) connFull = c;
  }

  function appendLog(data) {
    let text;
    if (typeof data === "string") text = data;
    else {
      try { text = new TextDecoder("utf-8").decode(data); } catch (_) { text = ""; }
    }
    if (!text) return;
    logBuffer.push(text);
    if (logBuffer.length > LOG_MAX) logBuffer.shift();
    renderLog();
  }

  function renderLog() {
    const viewSmall = document.getElementById("serial-log-view");
    const viewFull = document.getElementById("serial-log-view-full");
    const text = logBuffer.join("");
    if (viewSmall) viewSmall.textContent = text.slice(-30000);
    if (viewFull) viewFull.textContent = text.slice(-60000);
  }

  function setMode(mode) {
    // per-view mode toggling: switch active tab everywhere + show/hide terminal/log
    const views = [
      { termEl: "serial-terminal", logEl: "serial-log-view", container: ".serial-pane" },
      { termEl: "serial-terminal-full", logEl: "serial-log-view-full", container: "#view-terminal" },
    ];
    // simple global approach: interactive shows terminals; log shows log views
    UI.qsa(".console-tabs").forEach((tabs) => {
      UI.qsa(".tab", tabs).forEach((t) => {
        t.classList.toggle("active", t.dataset.mode === mode);
      });
    });
    if (mode === "interact") {
      UI.qs("#serial-terminal").style.display = "block";
      UI.qs("#serial-terminal-full").style.display = "block";
      UI.qs("#serial-log-view").style.display = "none";
      UI.qs("#serial-log-view-full").style.display = "none";
    } else {
      UI.qs("#serial-terminal").style.display = "none";
      UI.qs("#serial-terminal-full").style.display = "none";
      UI.qs("#serial-log-view").style.display = "block";
      UI.qs("#serial-log-view-full").style.display = "block";
    }
  }

  function clearTerminal() {
    term && term.clear();
    termFull && termFull.clear();
  }

  return { initConsoles, setMode, clearTerminal };
})();