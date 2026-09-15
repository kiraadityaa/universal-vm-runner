"""REST API routes for VM management, proxied through QMP."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from qmp_client import QMPClient

logger = logging.getLogger("api")

SCREENDIR = "/tmp/vm-screens"
os.makedirs(SCREENDIR, exist_ok=True)

# ---- Idle metric cache (updated by a background task) ---------------
METRICS: dict[str, Any] = {
    "status": {"status": "unknown", "running": False},
    "cpus": [],
    "blockstats": [],
    "cpu_percent": 0.0,
    "ram_used_gb": 0.0,
    "disk_used_gb": 0.0,
    "uptime_s": 0,
    "updated_at": 0,
}

QEMU_PID_FILE = "/tmp/qemu.pid"
VM_START_TIME_FILE = "/tmp/vm-start-time"


def _read_qemu_pid() -> int | None:
    try:
        return int(Path(QEMU_PID_FILE).read_text().strip())
    except (OSError, ValueError):
        return None


def _qemu_cpu_percent() -> float:
    import psutil

    pid = _read_qemu_pid()
    if not pid:
        return 0.0
    try:
        ps = psutil.Process(pid)
        return ps.cpu_percent(interval=None) or 0.0
    except psutil.NoSuchProcess:
        return 0.0


async def refresh_metrics(qmp: QMPClient) -> dict:
    status = await qmp.query_status()
    cpus = await qmp.query_cpus()
    blockstats = await qmp.query_blockstats()

    used_b = 0
    total_b = 0
    for blk in blockstats:
        stats = blk.get("stats", {})
        used_b += stats.get("wr_bytes", 0)
        total_b += stats.get("rd_bytes", 0)

    ram_used = 0.0
    ram_total = 0.0

    METRICS.update(
        {
            "status": status,
            "cpus": cpus,
            "blockstats": blockstats,
            "cpu_percent": round(_qemu_cpu_percent(), 1),
            "ram_used_gb": round(ram_used, 2),
            "disk_used_gb": round(used_b / (1024**3), 2),
            "updated_at": time.time(),
        }
    )
    return METRICS


async def metrics_loop(app: web.Application) -> None:
    qmp: QMPClient = app["qmp"]
    while True:
        try:
            await refresh_metrics(qmp)
        except Exception as exc:
            logger.debug("metrics refresh failed: %s", exc)
        await asyncio.sleep(1.5)


# ----------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------
def routes() -> web.RouteTableDef:
    routes = web.RouteTableDef()

    @routes.get("/api/vm/status")
    async def vm_status(request: web.Request) -> web.Response:
        qmp: QMPClient = request.app["qmp"]
        status = await qmp.query_status()
        return web.json_response({"status": status})

    @routes.get("/api/vm/metrics")
    async def vm_metrics(request: web.Request) -> web.Response:
        return web.json_response(METRICS)

    @routes.get("/api/vm/installer")
    async def installer_status(request: web.Request) -> web.Response:
        monitor = request.app["installer_monitor"]
        return web.json_response(monitor.get_status())

    @routes.get("/api/vm/snapshots")
    async def list_snapshots(request: web.Request) -> web.Response:
        qmp: QMPClient = request.app["qmp"]
        try:
            raw = await qmp.snapshot_list()
            text = raw.get("return", "") if isinstance(raw, dict) else str(raw)
            snapshots = _parse_snapshot_list(text)
            return web.json_response({"snapshots": snapshots})
        except RuntimeError as exc:
            return web.json_response({"snapshots": [], "error": str(exc)}, status=503)

    @routes.post("/api/vm/power/{action}")
    async def power_action(request: web.Request) -> web.Response:
        qmp: QMPClient = request.app["qmp"]
        action = request.match_info["action"]
        actions = {
            "reset": qmp.system_reset,
            "powerdown": qmp.system_powerdown,
            "wakeup": qmp.system_wakeup,
            "quit": qmp.quit,
        }
        fn = actions.get(action)
        if not fn:
            return web.json_response({"error": f"unknown action {action}"}, status=400)
        try:
            await fn()
            return web.json_response({"ok": True, "action": action})
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=503)

    @routes.post("/api/vm/control/{action}")
    async def control_action(request: web.Request) -> web.Response:
        qmp: QMPClient = request.app["qmp"]
        action = request.match_info["action"]
        actions = {
            "pause": qmp.pause,
            "resume": qmp.cont,
        }
        fn = actions.get(action)
        if not fn:
            return web.json_response({"error": f"unknown action {action}"}, status=400)
        try:
            await fn()
            return web.json_response({"ok": True, "action": action})
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=503)

    @routes.post("/api/vm/send-key")
    async def send_key(request: web.Request) -> web.Response:
        qmp: QMPClient = request.app["qmp"]
        body = await request.json()
        keys = body.get("keys", [])
        hold = body.get("hold_ms", 100)
        if not keys:
            return web.json_response({"error": "keys required"}, status=400)
        try:
            await qmp.send_key(keys, hold)
            return web.json_response({"ok": True, "keys": keys})
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=503)

    @routes.post("/api/vm/screendump")
    async def screendump(request: web.Request) -> web.Response:
        qmp: QMPClient = request.app["qmp"]
        path = f"{SCREENDIR}/screen.png"
        try:
            await qmp.screendump(path)
            return web.json_response({"path": f"/api/vm/screenshot", "ok": True})
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=503)

    @routes.get("/api/vm/screenshot")
    async def screenshot(request: web.Request) -> web.Response:
        path = f"{SCREENDIR}/screen.png"
        if not os.path.exists(path):
            return web.Response(status=404)
        return web.FileResponse(
            path, headers={"Content-Type": "image/png", "Cache-Control": "no-store"}
        )

    @routes.post("/api/vm/snapshot")
    async def create_snapshot(request: web.Request) -> web.Response:
        qmp: QMPClient = request.app["qmp"]
        body = await request.json()
        tag = body.get("tag") or f"snap-{int(time.time())}"
        try:
            await qmp.snapshot_save(tag)
            return web.json_response({"ok": True, "snapshot": tag})
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=503)

    @routes.get("/api/config")
    async def config(request: web.Request) -> web.Response:
        env = {
            "ISO_URL": os.environ.get("ISO_URL", ""),
            "VM_MEMORY": os.environ.get("VM_MEMORY", ""),
            "VM_CPUS": os.environ.get("VM_CPUS", ""),
            "DISK_SIZE": os.environ.get("DISK_SIZE", ""),
            "KEEP_ALIVE_MINUTES": os.environ.get("KEEP_ALIVE_MINUTES", ""),
        }
        # Strip URL params for display safety.
        url = env["ISO_URL"]
        env["ISO_URL_DISPLAY"] = url.split("?")[0] if url else ""
        return web.json_response(env)

    return routes


def _parse_snapshot_list(text: str) -> list[dict]:
    """Parse `info snapshots` HMP output into a list of snapshots."""
    snaps = []
    if not text:
        return snaps
    lines = text.splitlines()
    header = None
    for line in lines:
        if line.startswith("ID") and "VM" in line:
            header = line
            continue
        if header and line.strip() and not line.startswith("-"):
            parts = line.split()
            if len(parts) >= 4:
                snaps.append(
                    {
                        "id": parts[0],
                        "tag": parts[1],
                        "vm_size": parts[2],
                        "date": parts[3] if len(parts) > 3 else "",
                    }
                )
    return snaps