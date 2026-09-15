"""QMP client manager for controlling QEMU via the QEMU Machine Protocol.

A self-contained asyncio QMP implementation (stdlib only). It owns the
QMP unix socket, speaks JSON-lines over it, reconnects whenever QEMU is
restarted by the runner loop, executes commands with id-matched replies,
and fans asynchronous QEMU events out to WebSocket subscribers.

No third-party dependency (qemu.qmp) is required, which keeps the
GitHub Actions runner environment predictable.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("qmp")

QMP_SOCKET = "/tmp/qmp.sock"

OptionalResult = Any


class QMPClient:
    """Async QMP client with reconnect + broadcast."""

    def __init__(self, socket_path: str = QMP_SOCKET) -> None:
        self._socket = socket_path
        self._lock = asyncio.Lock()
        self._connected = False
        self._connect_task: Optional[asyncio.Task] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._pending: dict[str, asyncio.Future] = {}
        self._cmd_id = 0
        self._stopped = False
        self._subscribers: list[asyncio.Queue] = []
        self._event_handlers: list[Callable[[dict], Any]] = []
        self.errors = asyncio.Queue()  # store recent errors for UI display

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Begin the reconnect-until-socket-exists loop."""
        self._connect_task = asyncio.create_task(self._run_loop())

    async def shutdown(self) -> None:
        """Stop the reconnect loop and release the socket."""
        self._stopped = True
        if self._connect_task:
            self._connect_task.cancel()
        self._teardown()

    async def _run_loop(self) -> None:
        while not self._stopped:
            try:
                # QEMU may not be up yet — poll for socket existence.
                if not _socket_exists(self._socket):
                    await asyncio.sleep(2)
                    continue
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("QMP session error: %s", exc)
                self._teardown()
                self._broadcast({"type": "qmp", "connected": False})
                try:
                    await self.errors.put(
                        "QMP disconnect — waiting for VM restart"
                    )
                except Exception:
                    pass
                await asyncio.sleep(2)

    async def _session(self) -> None:
        """Connect, negotiate capabilities, then run the inbound read loop."""
        reader, writer = await asyncio.open_unix_connection(self._socket)

        # QMP handshake: greeting, then qmp_capabilities (reply has no id).
        greeting_raw = await asyncio.wait_for(reader.readline(), timeout=10)
        greeting = _loads(greeting_raw)
        if not greeting or "QMP" not in greeting:
            raise RuntimeError(f"bad QMP greeting: {greeting_raw[:120]!r}")

        self._writer = writer
        payload = b'{"execute": "qmp_capabilities"}\r\n'
        writer.write(payload)
        await writer.drain()
        reply_raw = await asyncio.wait_for(reader.readline(), timeout=10)
        reply = _loads(reply_raw)
        if not reply or "return" not in reply:
            raise RuntimeError(f"capabilities negotiation failed: {reply}")

        self._reader = reader
        self._connected = True
        logger.info("QMP connected")
        self._broadcast({"type": "qmp", "connected": True})

        while True:
            line = await reader.readline()
            if not line:
                raise EOFError("QMP socket closed by QEMU")
            msg = _loads(line)
            if msg is not None:
                asyncio.create_task(self._route(msg))

    async def _route(self, msg: dict) -> None:
        """Dispatch an inbound QMP message: async event or command reply."""
        if "event" in msg:
            name = msg.get("event", "")
            logger.debug("QMP event: %s", name)
            self._broadcast({"type": "event", "event": name, "data": msg})
            for handler in list(self._event_handlers):
                try:
                    result = handler(msg)
                    if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    logger.warning("event handler failed: %s", exc)
            return

        rid = msg.get("id")
        if rid is not None and rid in self._pending:
            fut = self._pending.pop(rid)
            if not fut.done():
                if "error" in msg:
                    fut.set_exception(RuntimeError(str(msg["error"])))
                else:
                    fut.set_result(msg.get("return"))

    def on_event(self, handler: Callable[[dict], Any]) -> None:
        """Register a callable (sync or async) invoked for each QMP event."""
        self._event_handlers.append(handler)

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------
    async def execute(self, cmd: str, arguments: dict | None = None):
        """Run a QMP command; raises RuntimeError if QMP is unavailable."""
        if not self._connected or not self._writer:
            raise RuntimeError("QMP not connected — VM may be starting")
        arguments = arguments or {}
        async with self._lock:
            self._cmd_id += 1
            rid = f"uvm{self._cmd_id}"
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._pending[rid] = fut
            payload = json.dumps(
                {"execute": cmd, "arguments": arguments, "id": rid}
            )
            try:
                self._writer.write(payload.encode() + b"\r\n")
                await self._writer.drain()
                return await asyncio.wait_for(fut, timeout=15)
            except asyncio.TimeoutError:
                raise RuntimeError(f"QMP command timed out: {cmd}") from None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise RuntimeError(f"QMP command failed: {cmd}: {exc}") from exc
            finally:
                self._pending.pop(rid, None)

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------
    async def query_status(self) -> dict:
        try:
            return await self.execute("query-status")
        except RuntimeError:
            return {"status": "unknown", "running": False}

    async def query_cpus(self) -> list:
        try:
            return await self.execute("query-cpus-fast")
        except RuntimeError:
            return []

    async def query_blockstats(self) -> list:
        try:
            return await self.execute("query-blockstats")
        except RuntimeError:
            return []

    async def query_balloon(self) -> dict:
        try:
            return await self.execute("query-balloon")
        except RuntimeError:
            return {}

    async def system_reset(self) -> OptionalResult:
        return await self.execute("system_reset")

    async def system_powerdown(self) -> OptionalResult:
        return await self.execute("system_powerdown")

    async def system_wakeup(self) -> OptionalResult:
        return await self.execute("system_wakeup")

    async def cont(self) -> OptionalResult:
        return await self.execute("cont")

    async def pause(self) -> OptionalResult:
        return await self.execute("stop")

    async def quit(self) -> OptionalResult:
        return await self.execute("quit")

    async def screendump(self, path: str) -> OptionalResult:
        return await self.execute("screendump", {"filename": path})

    async def send_key(self, keys: list[str], hold_ms: int = 100) -> OptionalResult:
        qcodes = [
            {"type": "qcode", "data": _normalize_qcode(k)} for k in keys
        ]
        return await self.execute(
            "send-key", {"keys": qcodes, "hold-time": hold_ms}
        )

    async def snapshot_save(self, tag: str, name: str | None = None) -> OptionalResult:
        return await self.execute(
            "snapshot-save", {"tag": tag}
        )

    async def snapshot_list(self) -> OptionalResult:
        try:
            return await self.execute(
                "human-monitor-command", {"command-line": "info snapshots"}
            )
        except RuntimeError:
            return {"return": ""}

    # ------------------------------------------------------------------
    # Broadcast / subscribe
    # ------------------------------------------------------------------
    def subscribe(self, maxsize: int = 100) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def _broadcast(self, message: dict) -> None:
        for q in list(self._subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)

    def _teardown(self) -> None:
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
        self._reader = None
        self._writer = None
        exc = RuntimeError("QMP disconnected")
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _socket_exists(path: str) -> bool:
    try:
        import os

        return os.path.exists(path)
    except Exception:
        return False


def _loads(raw: bytes) -> dict | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _normalize_qcode(key: str) -> str:
    """Map friendly names (e.g. 'altgr', 'del', 'arrowup') to QEMU qcodes."""
    mapping = {
        "esc": "esc",
        "ctrl": "ctrl",
        "alt": "alt",
        "altgr": "alt_r",
        "shift": "shift",
        "del": "delete",
        "backspace": "backspace",
        "tab": "tab",
        "enter": "ret",
        "ret": "ret",
        "space": "spc",
        "capslock": "caps_lock",
        "f1": "f1",
        "f2": "f2",
        "f3": "f3",
        "f4": "f4",
        "f5": "f5",
        "f6": "f6",
        "f7": "f7",
        "f8": "f8",
        "f9": "f9",
        "f10": "f10",
        "f11": "f11",
        "f12": "f12",
        "home": "home",
        "end": "end",
        "pageup": "pgup",
        "pagedown": "pgdn",
        "insert": "insert",
        "arrowup": "up",
        "arrowdown": "down",
        "arrowleft": "left",
        "arrowright": "right",
        "printscreen": "print",
        "pause": "pause",
        "super": "super_l",
        "menu": "menu",
    }
    k = key.lower()
    return mapping.get(k, k)