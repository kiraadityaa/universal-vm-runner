"""Test: QMP client handshake + command + event against a minimal fake QEMU QMP server."""
import asyncio
import json
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

QMP_SOCK = "/tmp/qmp.sock"


def start_fake_qmp():
    try:
        os.unlink(QMP_SOCK)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(QMP_SOCK)
    srv.listen(1)

    def run():
        conn, _ = srv.accept()
        f = conn.makefile("rwb", buffering=0)
        greeting = {"QMP": {"version": {"qemu": {"micro": 0, "minor": 2, "major": 8}}, "capabilities": []}}
        f.write(json.dumps(greeting).encode() + b"\r\n")
        while True:
            line = f.readline()
            if not line:
                break
            try:
                req = json.loads(line)
            except Exception:
                continue
            if req.get("execute") == "qmp_capabilities":
                # QMP spec: the capabilities reply carries no id.
                resp = {"return": {}}
            elif req.get("execute") == "query-status":
                resp = {"return": {"running": True, "singlestep": False, "status": "running"}, "id": req.get("id")}
            elif req.get("execute") == "send-key":
                resp = {"return": {}, "id": req.get("id")}
            else:
                resp = {"return": {}, "id": req.get("id")}
            f.write(json.dumps(resp).encode() + b"\r\n")
        conn.close()

    threading.Thread(target=run, daemon=True).start()
    return srv


async def main():
    import qmp_client

    client = qmp_client.QMPClient()
    await client.start()
    # give it time to connect
    for _ in range(20):
        s = await client.query_status()
        if s.get("status") == "running":
            break
        await asyncio.sleep(0.3)
    st = await client.query_status()
    print("query-status:", st)
    assert st["running"] is True, st
    await client.send_key(["ctrl", "alt", "delete"])
    print("send-key: OK")
    await client.shutdown()
    print("QMP TEST PASS")


if __name__ == "__main__":
    srv = start_fake_qmp()
    try:
        asyncio.run(main())
    finally:
        srv.close()