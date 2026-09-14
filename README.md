# Universal VM Runner

> Boot **any Linux ISO** in a QEMU virtual machine running on a free GitHub Actions macOS runner — and watch it live in your browser via noVNC + Cloudflare Quick Tunnel. No account, no API key, no secrets.

[![VM Runner](https://img.shields.io/badge/VM_Runner-QEMU+noVNC-blue?style=flat-square&logo=qemu&logoColor=white)](https://github.com/kiraadityaa/universal-vm-runner)
[![Runner](https://img.shields.io/badge/Runner-macOS_Intel-000000?style=flat-square&logo=apple&logoColor=white)](https://github.com/actions/runner-images)
[![Tunnel](https://img.shields.io/badge/Tunnel-Cloudflare-brightgreen?style=flat-square)](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

- **Bahasa Indonesia**: [README.id.md](README.id.md)

---

## What is this?

Have you ever wanted to spin up a Linux distro in the cloud, fiddle with an installer, test a live ISO, or run a server workload — all from your browser, for free, without renting a VPS?

**Universal VM Runner** runs the QEMU emulator on a **free GitHub-hosted macOS Intel runner** (4 vCPU / 14 GB RAM on public repos) and pipes the VM's display to you through:

1. **QEMU** — emulates a full machine, boots the ISO you give it
2. **VNС (port 5900)** — QEMU's built-in VNC server
3. **noVNC** — HTML5 VNC client served on port 6080
4. **Cloudflare Quick Tunnel** — free HTTPS tunnel, no account needed

You provide one thing: a **direct link to an ISO**. The workflow returns a URL. Open it, and you're looking at a real VM booting.

## How it works

```
You click "Run workflow" → paste ISO URL
        │
        ▼
macOS runner (macos-15-intel: 4 vCPU / 14 GB RAM)
        │
        ├─ Download ISO
        ├─ Detect architecture (x86_64 / arm64) + HVF (Hypervisor.framework)
        ├─ Create sparse qcow2 disk
        ├─ QEMU VM: -cdrom ISO -boot order=cd   ← self-healing boot
        ├─ noVNC → WebSocket :6080
        └─ Cloudflare Quick Tunnel → https://xxx.trycloudflare.com
```

Open the printed URL in any browser → see the VM → install the OS → reboot → the VM keeps working.

### Self-healing boot (no "no bootable device" trap)

Every restart runs the **same** QEMU command with `-boot order=cd` — the firmware tries the **hard disk first**, and falls back to the **ISO** while the disk isn't bootable yet. So:

| Situation | Result |
|---|---|
| Install not finished, a reboot happens | Disk not bootable → auto re-enters **ISO installer** |
| Install finished + reboot | Disk bootable → auto boots the **installed OS** |
| Reboot inside the installed OS | Disk bootable → stays on the **installed OS** |
| Disk permanently broken | Falls back to ISO; re-run the workflow for a fresh disk |

No phase state machine, no assumption that "reboot = installer done" — the firmware decides.

## Quick start

1. **Fork** this repository (so you can run the workflow — Actions must run from your own fork).
2. Go to **Actions → Universal VM Runner → Run workflow**.
3. Fill in the inputs:

| Input | Required | Default | Description |
|---|---|---|---|
| `iso_url` | yes | — | Direct link to the installer/live ISO (x86_64/amd64 recommended) |
| `vm_memory` | no | `8G` | VM RAM (runner has 14 GB) |
| `vm_cpus` | no | `4` | VM vCPUs (max 4 on the Intel runner) |
| `disk_size` | no | `20G` | Virtual disk size (sparse qcow2) |
| `keep_alive_minutes` | no | `360` | Session length (max 360) |

4. Run, wait ~1–2 minutes, then open the **`https://…trycloudflare.com/vnc.html…`** URL printed in the `Run Universal VM` step log.

> Note: GitHub-hosted macOS runners are **free & unlimited on public repos**. The macOS label for **private** repos costs 10× Actions credits and is limited on the free plan.

## Good ISO choices

- **Debian netinst**: `https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-<ver>-amd64-netinst.iso` (~770 MB)
- **Ubuntu Server**: `https://releases.ubuntu.com/…/ubuntu-…-server-amd64.iso`
- **Alpine**: tiny (~50–170 MB), boots fast
- Any **x86_64/amd64** Linux ISO works well; `arm64` also supported
- Use a **direct download link** (not a browser-download URL)

## What about performance?

The script detects acceleration at runtime:

- **HVF** (`Hypervisor.framework`): used automatically when `sysctl kern.hv_support` returns `1` — current Intel VMware-esque runners expose it. Near-native speed.
- **TCG** (software emulation): fallback — usable when the guest architecture **matches the runner** (x86_64 guest on x86_64 runner). A cross-arch mix (e.g. ARM64 ISO on the Intel runner) is very slow — avoid it.

## Honest caveats

- **14 GB runner disk** — a >4 GB ISO plus a big qcow2 may not fit. Prefer slim/netinstall ISOs.
- **HVF availability varies** across the runner fleet — the script probes it every run and auto-falls back to TCG.
- **Brief VNC drop** during a VM reboot (a few seconds; noVNC auto-reconnects).
- **ISO stays attached** in the installed OS — harmless (disk boots first); a Debian "remove installation media" prompt is informational only, Enter still boots your OS.
- **Ephemeral disk** — the qcow2 lives on the runner and is lost when the workflow ends. No persistence yet.
- **macOS guest ISOs unsupported** in this version (needs OpenCore bootloader config).
- **Quick Tunnel URL is ephemeral** — dies with the workflow run (same lifecycle as the VM session).

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
| `scripts/qemu/setup-vm.sh` | Everything else: ISO download, arch/HVF detection, qcow2, noVNC + tunnel, QEMU reboot loop |

## Installing on your own machine

The workflow is the easy path, but the script itself works anywhere with QEMU + cloudflared:

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
│   └── setup-vm.sh          # QEMU lifecycle: ISO, disk, VM, noVNC, tunnel
├── README.md
├── README.id.md
└── LICENSE                  # MIT
```

## Related project

This project started as a feature inside **RICH Linux CRD** ([kiraadityaa/rich-linux-crd](https://github.com/kiraadityaa/rich-linux-crd)) — Chrome Remote Desktop desktops on GitHub Actions — and was split out to keep things modular.

## License

MIT — see [LICENSE](LICENSE).