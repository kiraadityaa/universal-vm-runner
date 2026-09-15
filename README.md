# Universal VM Runner

> Boot **any Linux ISO** in a QEMU virtual machine running on a free GitHub Actions macOS runner — and manage it from a full **web dashboard** in your browser via noVNC + Cloudflare Quick Tunnel. No account, no API key, no secrets.

[![VM Runner](https://img.shields.io/badge/VM_Runner-QEMU%20%2B%20Dashboard-blue?style=flat-square&logo=qemu&logoColor=white)](https://github.com/kiraadityaa/universal-vm-runner)
[![Runner](https://img.shields.io/badge/Runner-macOS_Intel-000000?style=flat-square&logo=apple&logoColor=white)](https://github.com/actions/runner-images)
[![Tunnel](https://img.shields.io/badge/Tunnel-Cloudflare-brightgreen?style=flat-square)](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

- **Bahasa Indonesia**: [README.id.md](README.id.md)

---

## What is this?

Spin up a Linux distro in the cloud, interact with an installer, test a live ISO, or run a server workload — all from your browser, for free, without renting a VPS.

**Universal VM Runner** runs QEMU on a **free GitHub-hosted macOS Intel runner** (4 vCPU / 14 GB RAM on public repos) and exposes a **complete web management dashboard**:

- 🖥️ **VM display** — direct noVNC, layar penuh via tunnel terpisah
- ⌨️ **QMP control toolbar** — reset, power off, pause/resume, `Ctrl+Alt+Del`, F2, screenshot, snapshot
- 🔌 **Interactive serial console** — xterm.js over WebSocket (works even when the GUI can't initialize)
- 📊 **Live instruments** — power state, uptime, CPU load, RAM, disk I/O, vCPU count
- 🧭 **Smart installer monitor** — detects `booting → installing → ready / failed` from serial output
- ⏱️ **Snapshots** — create / list VM checkpoints via QMP

## How it works

```
You click "Run workflow" → paste ISO URL
        │
        ▼
macOS runner (macos-15-intel: 4 vCPU / 14 GB RAM)
        │
        ├─ Download ISO
        ├─ Detect architecture (x86_64 / arm64) + HVF
        ├─ Create sparse qcow2 disk
        ├─ QEMU VM: -boot order=cd + QMP socket + serial socket
        ├─ aiohttp dashboard (:8080) — API + WebSocket + static UI
        │     ├─ /api/vm/*         REST (status, power, keys, snapshot)
        │     ├─ /ws/qmp           QMP events + live metrics
        │     └─ /ws/serial        serial console bridge (xterm.js)
        ├─ novnc_proxy (:6080) — raw noVNC / websockify → QEMU VNC :5900
        ├─ Cloudflare Quick Tunnel #1 → :8080  (dashboard control)
        └─ Cloudflare Quick Tunnel #2 → :6080  (direct noVNC, full screen)
```

Two URLs, two jobs — **dashboard control** and **direct noVNC** each get their own public HTTPS link.

### Technology stack

| Layer | What we use | Why |
|---|---|---|
| **Web server** | [aiohttp](https://docs.aiohttp.org/) — one Python process on `:8080` | Serves the static UI **and** the REST API **and** every WebSocket endpoint for dashboard control |
| **VM control** | Self-contained **asyncio QMP client** (stdlib only) | Speaks the QEMU Machine Protocol over `/tmp/qmp.sock`: `greeting → qmp_capabilities` handshake, id-matched replies, auto-reconnect whenever QEMU (re)starts, and broadcast of async events (`RESET`, `SHUTDOWN`, `GUEST_PANICKED`). No `qemu.qmp` dependency, so the runner needs just `aiohttp` + `psutil` |
| **Serial console** | [xterm.js](https://xtermjs.org/) over `/ws/serial` | Interactive terminal that works even when the guest GUI can't initialize |
| **VM display** | **Direct noVNC** via `novnc_proxy` on `:6080` | A separate Cloudflare Quick Tunnel exposes the raw noVNC client in full screen, independent of the dashboard |
| **Instrument panel** | `psutil` + QMP `query-*` commands | Live host CPU/RAM and guest power/disk stats pushed every second |
| **Installer monitoring** | Regex state machine on serial output | Classifies `booting → installing → ready / failed` without any guesswork |
| **Public access** | **Two** Cloudflare Quick Tunnels → `:8080` + `:6080` | Public HTTPS URLs, zero account, zero config — one for dashboard control, one for direct noVNC |

### Single boot, no auto-reboot loop

QEMU runs **once** (no launcher loop, no "reboot detection"). The command uses `-boot order=cd` — the firmware tries the **hard disk first**, and falls back to the **ISO** while the disk isn't bootable yet:

| Situation | Result |
|---|---|
| Install not finished, a reboot happens | Disk not bootable → firmware re-enters **ISO installer** |
| Install finished + reboot | Disk bootable → firmware boots the **installed OS** |
| Reboot inside the installed OS | Disk bootable → stays on the **installed OS** |
| Disk permanently broken | Falls back to the ISO; re-run the workflow for a fresh disk |

Because the VM runs **without `-no-reboot`**, a guest-initiated reboot (e.g. Debian's "Installation complete, reboot") is handled **by QEMU's firmware in the same process** — no external restart, no installer-monitor guesswork. The only fallback is a single one-time retry with **TCG** if HVF crashes within the first 90 s (known bug in Homebrew QEMU 11.x, see caveats). After the VM exits, the dashboard and both tunnels stay reachable until the keep-alive window ends.

The dashboard's **installer monitor** watches the serial console and reports phase, progress, and failures — but `ready` is only reported after the VM was actually `installing`, so a bootloader/menu screen is never mistaken for a finished install.

## Quick start

1. **Fork** this repository (Actions must run from your own fork).
2. Go to **Actions → Universal VM Runner → Run workflow**.
3. Fill in the inputs:

| Input | Required | Default | Description |
|---|---|---|---|
| `iso_url` | yes | — | Direct link to the installer/live ISO (x86_64/amd64 recommended) |
| `vm_memory` | no | `8G` | VM RAM (runner has 14 GB) |
| `vm_cpus` | no | `4` | VM vCPUs (max 4 on the Intel runner) |
| `disk_size` | no | `20G` | Virtual disk size (sparse qcow2) |
| `keep_alive_minutes` | no | `360` | Session length (max 360) |

4. Run, wait ~1–2 minutes, then open the **two `https://…trycloudflare.com` URLs** printed in the `Run Universal VM` step log — the dashboard-control link (`/vnc.html?autoconnect` for the noVNC link). The dashboard also shows the direct noVNC link on its VM Display panel.

> Note: GitHub-hosted macOS runners are **free & unlimited on public repos**. The macOS label for **private** repos costs 10× Actions credits and is limited on the free plan.

## Dashboard tour

| Section | What you can do |
|---|---|
| **VM Display** | Button **Open noVNC — layar penuh** that jumps to the direct noVNC tunnel (full-screen client in a new tab); QMP toolbar: Reset, Resume, Pause, Power off, send `Ctrl+Alt+Del`, F2, Esc, screenshot, create snapshot |
| **Serial Terminal** | Interactive xterm.js console (plus a plain log view) — the most reliable way to watch an installer |
| **Instrument panel** | Live power state, uptime, CPU % (with sparkline), RAM, disk written, installer phase, vCPU count |
| **Snapshots** | List VM checkpoints (tag, size, date) |
| **Configuration** | Expand & collapse of VM config + raw installer-monitor JSON |

## API quick reference

```
GET  /api/vm/status              → QMP query-status
GET  /api/vm/metrics             → aggregated CPU/RAM/disk readouts
GET  /api/vm/installer           → installer state machine snapshot
GET  /api/vm/snapshots           → snapshot list
GET  /api/vm/screenshot          → latest PNG screendump
POST /api/vm/power/{reset|powerdown|wakeup|quit}
POST /api/vm/control/{pause|resume}
POST /api/vm/send-key            → {"keys":["ctrl","alt","delete"]}
POST /api/vm/snapshot            → {"tag":"my-checkpoint"}
POST /api/vm/screendump          → capture a PNG
GET  /ws/qmp                     → QMP events + 1s metrics push
GET  /ws/serial                  → serial console (binary)
GET  /ws/log                     → setup script task log
GET  /ws/vnc                     → VNC bridge (fallback — the UI uses the direct noVNC tunnel instead)
```

## Good ISO choices

- **Debian netinst**: `https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-<ver>-amd64-netinst.iso` (~770 MB)
- **Ubuntu Server**: `https://releases.ubuntu.com/…/ubuntu-…-server-amd64.iso`
- **Alpine**: tiny (~50–170 MB), boots fast
- Any **x86_64/amd64** Linux ISO works well; `arm64` also supported
- Use a **direct download link** (not a browser-download URL)

## What about performance?

The script detects acceleration at runtime:

- **HVF** (`Hypervisor.framework`): used automatically when `sysctl kern.hv_support` returns `1` — current Intel VMware-esque runners expose it. Near-native speed.
- **TCG** (software emulation): fallback — usable when the guest architecture **matches the runner**. A cross-arch mix (e.g. ARM64 ISO on the Intel runner) is very slow — avoid it.

## Honest caveats

- **14 GB runner disk** — a >4 GB ISO plus a big qcow2 may not fit. Prefer slim/netinstall ISOs.
- **HVF availability varies** across the runner fleet — probed every run, auto-falls back to TCG.
- **Homebrew QEMU 11.x may crash at boot under HVF** (`do_hv_vm_protect: assertion failed: !(size & ~page_mask)` → `Abort trap` / exit 134) — an upstream QEMU regression from Jan-2026. The runner mitigates this with **`-vga std`** (avoids the virtio-gpu dirty-tracking path that triggers it) and a **single TCG retry** if HVF aborts within the first 90 s.
- **Brief VNC drop** during a VM reboot (a few seconds; noVNC auto-reconnects).
- **ISO stays attached** in the installed OS — harmless (disk boots first); a Debian "remove installation media" prompt is informational only.
- **Ephemeral disk** — the qcow2 lives on the runner and is lost when the workflow ends. No persistence yet.
- **macOS guest ISOs unsupported** in this version (needs OpenCore bootloader config).
- **Quick Tunnel URL is ephemeral** — dies with the workflow run.

## SSH into the guest

QEMU forwards `host:8022 → guest:22`, so from the runner you can:

```bash
ssh user@127.0.0.1 -p 8022   # from the run's shell
```

(Port 22 on the host is taken by the runner's own SSH daemon, hence 8022.)

## Scripts

| File | Purpose |
|---|---|
| `.github/workflows/vm-runner.yml` | GitHub Actions workflow: install QEMU + cloudflared, run the VM |
| `scripts/qemu/setup-vm.sh` | ISO download, arch/HVF detection, qcow2, dashboard + tunnels, single QEMU boot (firmware-handled reboot, HVF→TCG fallback) |
| `scripts/qemu/server/app.py` | aiohttp server: static UI + REST API + WebSockets |
| `scripts/qemu/server/qmp_client.py` | self-contained asyncio QMP client (no `qemu.qmp` dep), auto-reconnect, event broadcast |
| `scripts/qemu/server/installer_monitor.py` | install state machine from serial patterns |
| `scripts/qemu/server/api.py` | REST API routes |
| `scripts/qemu/server/ws.py` | WebSocket handlers (+ serial manager) |
| `scripts/qemu/server/fetch_vendor.sh` | fetch xterm.js + noVNC client assets |

## Installing on your own machine

The workflow is the easy path, but the script works anywhere with QEMU + cloudflared:

```bash
brew install qemu cloudflared     # macOS
sudo apt install qemu-system-x86 cloudflared   # Linux

ISO_URL=https://… VM_MEMORY=8G VM_CPUS=4 DISK_SIZE=20G \
  KEEP_ALIVE_MINUTES=360 ./scripts/qemu/setup-vm.sh
```

## Repository structure

```
universal-vm-runner/
├── .github/workflows/
│   └── vm-runner.yml        # GitHub Actions workflow
├── scripts/qemu/
│   ├── setup-vm.sh          # QEMU lifecycle: ISO, disk, VM, dashboard, tunnel
│   └── server/              # Python web dashboard
│       ├── app.py
│       ├── qmp_client.py
│       ├── installer_monitor.py
│       ├── api.py
│       ├── ws.py
│       ├── fetch_vendor.sh
│       └── static/          # HTML/CSS/JS dashboard
├── README.md
├── README.id.md
└── LICENSE                  # MIT
```

## Related project

This project started as a feature inside **RICH Linux CRD** ([kiraadityaa/rich-linux-crd](https://github.com/kiraadityaa/rich-linux-crd)) — Chrome Remote Desktop desktops on GitHub Actions — and was split out to keep things modular.

## License

MIT — see [LICENSE](LICENSE).