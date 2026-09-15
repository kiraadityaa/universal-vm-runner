/* WebSocket manager: QMP event + metrics stream, and serial console bridge. */
"use strict";

const WS = (() => {
  let statusSocket = null;
  let statusHandlers = new Set();
  let reconnectTimer = null;
  let backoff = 1000;

  // Serial connections (may be multiple terminals)
  const serialSockets = new Map();

  function connectStatus() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/qmp`;
    try {
      statusSocket = new WebSocket(url);
    } catch (_) {
      scheduleReconnect();
      return;
    }

    statusSocket.onopen = () => {
      backoff = 1000;
      emit({ type: "_open" });
    };

    statusSocket.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        emit(msg);
      } catch (_) { /* ignore */ }
    };

    statusSocket.onclose = () => {
      emit({ type: "_close" });
      scheduleReconnect();
    };

    statusSocket.onerror = () => {
      statusSocket && statusSocket.close();
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectStatus();
    }, backoff);
    backoff = Math.min(backoff * 2, 10000);
  }

  function emit(msg) {
    statusHandlers.forEach((fn) => {
      try { fn(msg); } catch (e) { /* handler error */ }
    });
  }

  return {
    onStatus(fn) { statusHandlers.add(fn); },
    statusOpen() { return statusSocket && statusSocket.readyState === WebSocket.OPEN; },
    connect() {
      if (!statusSocket || statusSocket.readyState === WebSocket.CLOSED) connectStatus();
    },
    statusSocket,

    /**
     * Open a serial-console WebSocket. Returns an object:
     *   { ws, onData(fn), onClose(fn), send(bytes), close() }
     */
    openSerial(onOpen) {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const url = `${proto}://${location.host}/ws/serial`;
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";

      const item = {
        ws,
        dataHooks: new Set(),
        closeHooks: new Set(),
        onData(fn) { this.dataHooks.add(fn); },
        onClose(fn) { this.closeHooks.add(fn); },
        send(bytes) {
          if (ws.readyState === WebSocket.OPEN) ws.send(bytes);
        },
        close() {
          try { ws.close(); } catch (_) {}
        },
      };

      ws.onopen = () => { onOpen && onOpen(); };
      ws.onmessage = (ev) => {
        const data = ev.data instanceof ArrayBuffer ? new Uint8Array(ev.data) : (typeof ev.data === "string"
          ? new TextEncoder().encode(ev.data)
          : new Uint8Array(ev.data));
        item.dataHooks.forEach((fn) => {
          try { fn(data); } catch (_) {}
        });
      };
      ws.onclose = () => {
        item.closeHooks.forEach((fn) => {
          try { fn(); } catch (_) {}
        });
      };

      return item;
    },
  };
})();