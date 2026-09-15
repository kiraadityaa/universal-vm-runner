# Universal VM Runner

> Boot **ISO Linux apa pun** di dalam mesin virtual QEMU yang berjalan di runner macOS gratis GitHub Actions — dan kelola langsung dari **dashboard web lengkap** di browser melalui noVNC + Cloudflare Quick Tunnel. Tanpa akun, tanpa API key, tanpa secret.

[![VM Runner](https://img.shields.io/badge/VM_Runner-QEMU%20%2B%20Dashboard-blue?style=flat-square&logo=qemu&logoColor=white)](https://github.com/kiraadityaa/universal-vm-runner)
[![Runner](https://img.shields.io/badge/Runner-macOS_Intel-000000?style=flat-square&logo=apple&logoColor=white)](https://github.com/actions/runner-images)
[![Tunnel](https://img.shields.io/badge/Tunnel-Cloudflare-brightgreen?style=flat-square)](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

- **English**: [README.md](README.md)

---

## Apa ini?

Pengen menjalankan distro Linux di cloud, main-main installer, mencoba live ISO, atau menjalankan workload server — semua dari browser, gratis, tanpa sewa VPS?

**Universal VM Runner** menjalankan emulator QEMU di **runner macOS Intel gratis dari GitHub** (4 vCPU / 14 GB RAM di repo publik) dan meng-expose **dashboard manajemen web yang lengkap**:

- 🖥️ **Tampilan VM** — noVNC tertanam, resize sesuai permintaan
- ⌨️ **Toolbar kontrol QMP** — reset, matikan, pause/resume, `Ctrl+Alt+Del`, F2, screenshot, snapshot
- 🔌 **Konsol serial interaktif** — xterm.js lewat WebSocket (tetap jalan walau GUI tidak bisa init)
- 📊 **Instrumen live** — status daya, uptime, beban CPU, RAM, I/O disk, jumlah vCPU
- 🧭 **Monitor installer cerdas** — mendeteksi `booting → installing → ready / failed` dari output serial
- ⏱️ **Snapshot** — membuat / mendaftarkan checkpoint VM lewat QMP

## Cara kerja

```
Anda klik "Run workflow" → tempel URL ISO
        │
        ▼
Runner macOS (macos-15-intel: 4 vCPU / 14 GB RAM)
        │
        ├─ Unduh ISO
        ├─ Deteksi arsitektur (x86_64 / arm64) + HVF (Hypervisor.framework)
        ├─ Buat disk qcow2 sparse
        ├─ VM QEMU: -boot order=cd + socket QMP + socket serial
        ├─ Dashboard aiohttp (:8080) — API + WebSocket + static UI
        │     ├─ /api/vm/*         REST (status, power, keys, snapshot)
        │     ├─ /ws/qmp           event QMP + metrik live
        │     ├─ /ws/serial        konsol serial (xterm.js)
        │     └─ /ws/vnc           bridge VNC (noVNC tertanam)
        └─ Cloudflare Quick Tunnel → https://xxx.trycloudflare.com
```

Satu URL, satu origin — dashboard, tampilan VM, konsol serial, dan API semuanya berada di belakang tunnel yang sama.

### Teknologi di baliknya

| Lapisan | Yang dipakai | Alasannya |
|---|---|---|
| **Server web** | [aiohttp](https://docs.aiohttp.org/) — satu proses Python di `:8080` | Menyajikan UI statis **dan** REST API **dan** semua endpoint WebSocket, jadi satu URL tunnel sudah cukup |
| **Kontrol VM** | **Klien QMP asyncio mandiri** (stdlib saja) | Berbicara ke QEMU Machine Protocol lewat `/tmp/qmp.sock`: handshake `greeting → qmp_capabilities`, reply dicocokkan berdasar id, auto-reconnect saat loop runner me-restart QEMU, dan broadcast event async (`RESET`, `SHUTDOWN`, `GUEST_PANICKED`). Tanpa dependency `qemu.qmp` — runner cukup butuh `aiohttp` + `psutil` |
| **Konsol serial** | [xterm.js](https://xtermjs.org/) lewat `/ws/serial` | Terminal interaktif yang tetap berguna walau GUI guest gagal init |
| **Tampilan VM** | noVNC di-bridge lewat `/ws/vnc` | Tunnel hanya meng-expose `:8080`, jadi adapter WebSocket meneruskan frame VNC ke klien noVNC tertanam |
| **Panel instrumen** | `psutil` + perintah QMP `query-*` | Statistik CPU/RAM host serta daya/disk guest, dikirim tiap detik |
| **Monitoring installer** | State machine regex pada output serial | Mengklasifikasikan `booting → installing → ready / failed` tanpa menebak-nebak |
| **Akses publik** | Cloudflare Quick Tunnel → `:8080` | URL HTTPS publik, tanpa akun, tanpa konfigurasi |

### Boot self-healing (tanpa jebakan "no bootable device")

Setiap restart menjalankan perintah QEMU **yang sama** dengan `-boot order=cd` — firmware mencoba **hard disk lebih dulu**, dan **fallback ke ISO** selama disk belum bootable. Jadi:

| Situasi | Hasil |
|---|---|
| Install belum selesai, terjadi reboot | Disk belum bootable → otomatis masuk lagi ke **ISO installer** |
| Install selesai + reboot | Disk bootable → otomatis boot ke **OS terpasang** |
| Reboot di dalam OS terpasang | Disk bootable → tetap di **OS terpasang** |
| Disk rusak permanen | Fallback ke ISO; jalankan ulang workflow untuk disk baru |

**Monitor installer** di dashboard mengawasi konsol serial dan melaporkan fase, progres, serta kegagalan — jadi Anda tidak pernah menebak-nebak kenapa layar gelap.

## Quick start

1. **Fork** repo ini (Actions hanya bisa dijalankan dari fork Anda sendiri).
2. Buka **Actions → Universal VM Runner → Run workflow**.
3. Isi input:

| Input | Wajib | Default | Deskripsi |
|---|---|---|---|
| `iso_url` | ya | — | Link langsung ke installer/live ISO (disarankan x86_64/amd64) |
| `vm_memory` | tidak | `8G` | RAM VM (runner punya 14 GB) |
| `vm_cpus` | tidak | `4` | vCPU VM (maks 4 di runner Intel) |
| `disk_size` | tidak | `20G` | Ukuran disk virtual (qcow2 sparse) |
| `keep_alive_minutes` | tidak | `360` | Lama sesi (maks 360) |

4. Jalankan, tunggu ~1–2 menit, lalu buka URL **`https://…trycloudflare.com`** yang tercetak di log langkah `Run Universal VM` — itulah dashboard-nya.

> Catatan: runner macOS GitHub **gratis & unlimited di repo publik**. Di repo **privat**, label macOS dihitung 10× kredit Actions dan dibatasi di paket gratis.

## Tur dashboard

| Bagian | Yang bisa Anda lakukan |
|---|---|
| **Tampilan VM** | Konsol noVNC tertanam dengan toolbar QMP: Reset, Resume, Pause, Matikan, kirim `Ctrl+Alt+Del`, F2, Esc, screenshot, buat snapshot |
| **Terminal serial** | Konsol xterm.js interaktif (plus tampilan log polos) — cara paling andal untuk mengamati installer |
| **Panel instrumen** | Status daya live, uptime, CPU % (dengan sparkline), RAM, disk tertulis, fase installer, jumlah vCPU |
| **Snapshot** | Daftar checkpoint VM (tag, ukuran, tanggal) |
| **Konfigurasi** | Expand & collapse konfigurasi VM + JSON mentah installer-monitor |

## Referensi API singkat

```
GET  /api/vm/status              → QMP query-status
GET  /api/vm/metrics             → baca CPU/RAM/disk teragregasi
GET  /api/vm/installer           → snapshot state machine installer
GET  /api/vm/snapshots           → daftar snapshot
GET  /api/vm/screenshot          → PNG screendump terbaru
POST /api/vm/power/{reset|powerdown|wakeup|quit}
POST /api/vm/control/{pause|resume}
POST /api/vm/send-key            → {"keys":["ctrl","alt","delete"]}
POST /api/vm/snapshot            → {"tag":"my-checkpoint"}
POST /api/vm/screendump          → ambil PNG
GET  /ws/qmp                     → event QMP + push metrik tiap 1 detik
GET  /ws/serial                  → konsol serial (biner)
GET  /ws/log                     → log tugas setup
GET  /ws/vnc                     → bridge VNC untuk noVNC
```

## Pilihan ISO yang pas

- **Debian netinst**: `https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-<ver>-amd64-netinst.iso` (~770 MB)
- **Ubuntu Server**: `https://releases.ubuntu.com/…/ubuntu-…-server-amd64.iso`
- **Alpine**: kecil (~50–170 MB), boot cepat
- ISO Linux **x86_64/amd64** apa pun jalan bagus; `arm64` juga didukung
- Pakai **link unduhan langsung** (bukan URL yang butuh browser)

## Bagaimana soal performa?

Script mendeteksi akselerasi saat runtime:

- **HVF** (Hypervisor.framework): dipakai otomatis kalau `sysctl kern.hv_support` mengembalikan `1` — runner Intel yang sekarang meng-expose-nya. Kecepatan mendekati native.
- **TCG** (emulasi software): fallback — masih lumayan kalau arsitektur guest **sama dengan runner** (guest x86_64 di runner x86_64). Campur lintas arsitektur (mis. ISO ARM64 di runner Intel) sangat lambat — hindari.

## Catatan jujur

- **Disk runner 14 GB** — ISO >4 GB plus qcow2 besar mungkin tidak muat. Pilih ISO ramping/netinstall.
- **Ketersediaan HVF bervariasi** antar runner — script memeriksanya tiap run dan otomatis fallback ke TCG.
- **VNC sempat putus** saat reboot VM (beberapa detik; noVNC auto-konek ulang).
- **ISO tetap terpasang** di OS terpasang — tidak berbahaya (disk boot lebih dulu); prompt Debian "remove installation media" hanya informasi.
- **Disk ephemeral** — qcow2 ada di runner dan hilang saat workflow berakhir. Belum ada persistensi.
- **ISO guest macOS belum didukung** versi ini (butuh konfigurasi bootloader OpenCore).
- **URL Quick Tunnel bersifat sementara** — mati seiring workflow (seumur hidup sesi VM).

## SSH ke guest

QEMU meneruskan `host:8022 → guest:22`, jadi dari runner:

```bash
ssh user@127.0.0.1 -p 8022   # dari shell run
```

(Port 22 di host dipakai daemon SSH milik runner, karena itu 8022.)

## Script

| File | Fungsi |
|---|---|
| `.github/workflows/vm-runner.yml` | Workflow GitHub Actions: install QEMU + cloudflared, jalankan VM |
| `scripts/qemu/setup-vm.sh` | Unduh ISO, deteksi arch/HVF, buat qcow2, nyalakan dashboard + tunnel, loop reboot QEMU |
| `scripts/qemu/server/app.py` | Server aiohttp: UI statis + REST API + WebSocket |
| `scripts/qemu/server/qmp_client.py` | Klien QMP asyncio mandiri (tanpa dep `qemu.qmp`), auto-reconnect, broadcast event |
| `scripts/qemu/server/installer_monitor.py` | State machine install dari pola serial |
| `scripts/qemu/server/api.py` | Route REST API |
| `scripts/qemu/server/ws.py` | Handler WebSocket (+ serial manager) |
| `scripts/qemu/server/fetch_vendor.sh` | Ambil asset xterm.js + klien noVNC |

## Install di mesin sendiri

Workflow adalah jalan termudah, tapi script ini juga bisa jalan di mana saja yang ada QEMU + cloudflared:

```bash
brew install qemu cloudflared     # macOS
sudo apt install qemu-system-x86 cloudflared   # Linux

ISO_URL=https://… VM_MEMORY=8G VM_CPUS=4 DISK_SIZE=20G \
  KEEP_ALIVE_MINUTES=360 ./scripts/qemu/setup-vm.sh
```

## Struktur repository

```
universal-vm-runner/
├── .github/workflows/
│   └── vm-runner.yml        # Workflow GitHub Actions
├── scripts/qemu/
│   ├── setup-vm.sh          # Siklus hidup QEMU: ISO, disk, VM, dashboard, tunnel
│   └── server/              # Dashboard web Python
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

## Proyek terkait

Proyek ini lahir dari fitur di dalam **RICH Linux CRD** ([kiraadityaa/rich-linux-crd](https://github.com/kiraadityaa/rich-linux-crd)) — desktop Chrome Remote Desktop di GitHub Actions — dan dipisah agar modular.

## Lisensi

MIT — lihat [LICENSE](LICENSE).