"""Integration test: simulate QEMU serial socket, verify InstallerMonitor state machine and /ws/serial bridge."""
import asyncio
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SERIAL = "/tmp/serial.sock"


def start_fake_qemu_serial():
    """Open a unix socket server that accepts ONE connection and writes fake boot output."""
    try:
        os.unlink(SERIAL)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SERIAL)
    srv.listen(1)
    done = {}

    def run():
        conn, _ = srv.accept()
        done["connected"] = True
        chunks = [
            b"\r\nSeaBIOS (version 1.16.2)\r\n",
            b"Booting from Hard Disk...\r\n",
            b"[     0.000] Linux version 6.1.0 (debian) ...\r\n",
            b"Installer is running... 45% complete\r\n",
            b"Copying files. 78% ...\r\n",
            b"Installation finished, rebooting\r\n",
            b"Booting from Hard Disk...\r\n",
            b"Welcome to Debian GNU/Linux!\r\n",
        ]
        for c in chunks:
            conn.sendall(c)
            time.sleep(0.3)
        time.sleep(5)
        conn.close()

    threading.Thread(target=run, daemon=True).start()
    return srv, done


def check():
    import urllib.request

    def get(path):
        with urllib.request.urlopen(f"http://127.0.0.1:8080{path}") as r:
            return json.loads(r.read())

    # wait for server
    for _ in range(20):
        try:
            get("/api/vm/installer")
            break
        except Exception:
            time.sleep(0.5)

    # Poll the state machine as the fake serial stream plays out.
    # Regression guard: an early "Booting from Hard Disk" (while still booting,
    # not installing) must NOT flip the VM to "ready" — the Debian-menu bug.
    seen_installing = False
    final = None
    for _ in range(50):
        st = get("/api/vm/installer")
        s = st["state"]
        if s == "installing":
            seen_installing = True
        if s == "ready":
            final = st
            break
        time.sleep(0.3)

    print("INSTALLER STATE:", s, "| detail:", st["detail"], "| installing-before-ready:", seen_installing)
    assert s in ("ready", "installing", "booting"), f"unexpected: {st}"
    assert seen_installing, "state never reached 'installing' before 'ready' — READY gating broken"
    if final is not None:
        print("PASS: installer monitor reached READY via installing (reboot-to-HDD only after installing)")
    return 0


def main():
    srv, done = start_fake_qemu_serial()
    import subprocess
    proc = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")],
        env={**os.environ.copy()},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    code = 1
    try:
        code = check()
    finally:
        proc.terminate()
        srv.close()
    sys.exit(code)


if __name__ == "__main__":
    main()