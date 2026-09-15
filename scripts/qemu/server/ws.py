"""WebSocket endpoints: QMP event stream, serial console bridge, log stream."""

import asyncio
import base64
import json
import logging
import os
import socket as pysocket

from aiohttp import web

logger = logging.getLogger("ws")

SERIAL_SOCKET = "/tmp/serial.sock"
VNC_PORT = 5900


class SerialManager:
    """Owns the single QEMU serial socket connection.

    Reads bytes in the background, appends them to a persistent log file,
    feeds the installer monitor, and fans output out to subscribed WebSocket
    clients. Browser terminals send input through us (one writer at a time).
    """

    def __init__(self, log_path: str = "/tmp/vm-serial.log") -> None:
        self.log_path = log_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass

    async def _run(self) -> None:
        while True:
            try:
                self._reader, self._writer = await asyncio.open_unix_connection(
                    SERIAL_SOCKET
                )
                logger.info("serial console connected")
                while True:
                    data = await self._reader.read(4096)
                    if not data:
                        break
                    self._handle(data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._writer:
                    try:
                        self._writer.close()
                    except Exception:
                        pass
                    self._writer = None
                await asyncio.sleep(1.5)

    def _handle(self, data: bytes) -> None:
        # Append to persistent log
        try:
            with open(self.log_path, "ab") as fh:
                fh.write(data)
                fh.flush()
        except OSError:
            pass
        # Fan out to web subscribers (binary)
        for q in list(self._subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(("data", data))
            except asyncio.QueueFull:
                pass

    async def write(self, data: bytes) -> None:
        if not self._writer:
            return
        async with self._write_lock:
            try:
                self._writer.write(data)
                await self._writer.drain()
            except Exception:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)


SERIAL_MANAGER: SerialManager | None = None


async def qmp_ws(request: web.Request) -> web.WebSocketResponse:
    """Real-time QMP event + metric stream."""
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    app = request.app
    qmp = app["qmp"]
    monitor = app["installer_monitor"]
    q: asyncio.Queue = qmp.subscribe(maxsize=200)

    # Push current state immediately.
    await ws.send_str(
        json.dumps(
            {"type": "status", "status": (await qmp.query_status())}
        )
    )
    await ws.send_str(
        json.dumps({"type": "installer", "data": monitor.get_status()})
    )

    async def push_metrics():
        # Periodic metrics
        try:
            while not ws.closed:
                await asyncio.sleep(1)
                metrics = app["api"].METRICS if hasattr(app["api"], "METRICS") else None
                if metrics is None:
                    import api as api_mod

                    metrics = api_mod.METRICS
                await ws.send_str(
                    json.dumps(
                        {"type": "metrics", "data": metrics}
                    )
                )
        except Exception:
            pass

    metrics_task = asyncio.create_task(push_metrics())

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "ping":
                    await ws.send_str(json.dumps({"type": "pong"}))
                elif data.get("type") == "get-status":
                    await ws.send_str(
                        json.dumps(
                            {
                                "type": "status",
                                "status": (await qmp.query_status()),
                            }
                        )
                    )
                    await ws.send_str(
                        json.dumps(
                            {"type": "installer", "data": monitor.get_status()}
                        )
                    )
            while not q.empty():
                event = q.get_nowait()
                await ws.send_str(json.dumps(event))
    finally:
        metrics_task.cancel()
        qmp.unsubscribe(q)
    return ws


async def serial_ws(request: web.Request) -> web.WebSocketResponse:
    """Bidirectional bridge between a browser terminal and the QEMU serial sock."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    mgr: SerialManager = request.app["serial"]
    q: asyncio.Queue = mgr.subscribe()

    async def pump():
        while True:
            kind, payload = await q.get()
            if kind == "data":
                try:
                    await ws.send_bytes(payload)
                except Exception:
                    return
                continue
            try:
                await ws.send_str(json.dumps({"type": "state", "connected": bool(payload)}))
            except Exception:
                return

    pump_task = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.BINARY:
                await mgr.write(msg.data)
            elif msg.type == web.WSMsgType.TEXT:
                # Accept base64-encoded bytes for terminals that send text.
                if msg.data == "ping":
                    await ws.send_str(json.dumps({"type": "pong"}))
                    continue
                try:
                    raw = base64.b64decode(msg.data)
                    await mgr.write(raw)
                except Exception:
                    pass
    finally:
        pump_task.cancel()
        mgr.unsubscribe(q)
    return ws


async def log_ws(request: web.Request) -> web.WebSocketResponse:
    """Stream the tail of setup-vm.sh output (task log view)."""
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)

    log_path = os.environ.get("VM_LOG_FILE", "/tmp/vm-setup.log")

    async def tail_loop():
        pos = 0
        while True:
            await asyncio.sleep(1)
            try:
                size = os.path.getsize(log_path)
                if size < pos:
                    pos = 0
                if size <= pos:
                    continue
                with open(log_path, "rb") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
                pos = fh.tell()
                if chunk:
                    await ws.send_str(json.dumps({"type": "log", "data": chunk.decode("utf-8", errors="replace")}))
            except OSError:
                pass

    task = asyncio.create_task(tail_loop())
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                if msg.data == "ping":
                    await ws.send_str(json.dumps({"type": "pong"}))
    finally:
        task.cancel()
    return ws


async def vnc_ws(request: web.Request) -> web.WebSocketResponse:
    """Bridge a WebSocket to the QEMU VNC TCP port (in case of browsers that
    fail to reach 6080 directly; this proxies through the same aiohttp port)."""
    ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)

    reader = None
    writer = None

    async def _connect():
        nonlocal reader, writer
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", VNC_PORT)
        except OSError:
            reader, writer = None, None

    await _connect()

    async def pump():
        while True:
            if reader is None:
                await asyncio.sleep(1)
                await _connect()
                if reader is None:
                    continue
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            except Exception:
                reader = None
                continue
            if not data:
                continue
            await ws.send_bytes(data)

    pump_task = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.BINARY and writer:
                writer.write(msg.data)
                try:
                    await writer.drain()
                except Exception:
                    pass
    finally:
        pump_task.cancel()
        if writer:
            try:
                writer.close()
            except Exception:
                pass
    return ws