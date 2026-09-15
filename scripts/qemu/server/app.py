"""Universal VM Runner — Web Interface Server.

A single aiohttp process serving the dashboard UI, REST API, and
WebSocket endpoints (QMP events, serial console, log stream, VNC bridge).

Run:
    python3 app.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("uvm")

HERE = Path(__file__).resolve().parent

# ---- First-pass import of modules that live in the same directory -----
sys.path.insert(0, str(HERE))

import api  # noqa: E402
import ws  # noqa: E402
from installer_monitor import InstallerMonitor  # noqa: E402
from qmp_client import QMPClient  # noqa: E402

HOST = os.environ.get("SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("SERVER_PORT", "8080"))


async def camera_task(app: web.Application) -> None:
    """Take periodic screenshots so the UI can offer a static snapshot."""
    while True:
        await asyncio.sleep(30)
        qmp = app["qmp"]
        try:
            await qmp.screendump(f"{api.SCREENDIR}/screen.png")
        except Exception:
            pass


async def on_startup(app: web.Application) -> None:
    app["qmp"] = QMPClient()
    await app["qmp"].start()

    log_path = os.environ.get("VM_LOG_FILE", "/tmp/vm-setup.log")
    monitor = InstallerMonitor(serial_log=log_path)
    app["installer_monitor"] = monitor
    app["qmp"].on_event(monitor.handle_qmp_event)

    # Serial manager: owns the QEMU serial socket, writes to vm-serial.log,
    # and feeds the installer monitor with every byte.
    serial_log = os.environ.get("SERIAL_LOG", "/tmp/vm-serial.log")
    serial_manager = ws.SerialManager(log_path=serial_log)
    app["serial"] = serial_manager
    await serial_manager.start()

    # Route serial bytes to the installer monitor.
    async def serial_to_monitor():
        q = serial_manager.subscribe()
        while True:
            kind, payload = await q.get()
            if kind == "data":
                monitor.feed_serial(payload)

    asyncio.create_task(serial_to_monitor())

    asyncio.create_task(api.metrics_loop(app))
    asyncio.create_task(monitor.watch_serial_log())
    asyncio.create_task(camera_task(app))
    logger.info("Universal VM Runner web interface ready on http://%s:%d", HOST, PORT)


async def on_shutdown(app: web.Application) -> None:
    qmp: QMPClient = app.get("qmp")
    if qmp:
        await qmp.shutdown()
    serial: ws.SerialManager = app.get("serial")
    if serial:
        await serial.stop()


def build_app() -> web.Application:
    app = web.Application()

    # Static assets (dashboard).
    app.router.add_static("/static", str(HERE / "static"), show_index=False)
    app.router.add_static("/vendor", str(HERE / "static" / "vendor"))

    # API + WebSocket routes.
    app.add_routes(api.routes())
    app.add_routes(
        [
            web.get("/ws/qmp", ws.qmp_ws),
            web.get("/ws/serial", ws.serial_ws),
            web.get("/ws/log", ws.log_ws),
            web.get("/ws/vnc", ws.vnc_ws),
        ]
    )

    # Dashboard entry point.
    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(str(HERE / "static" / "index.html"))

    app.router.add_get("/", index)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    app = build_app()
    web.run_app(app, host=HOST, port=PORT, print=None)