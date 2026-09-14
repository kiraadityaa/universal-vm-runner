# Universal VM Runner

> Boot **ISO Linux apa pun** di dalam mesin virtual QEMU yang berjalan di runner macOS gratis GitHub Actions — dan lihat langsung di browser lewat noVNC + Cloudflare Quick Tunnel. Tanpa akun, tanpa API key, tanpa secret.

[![VM Runner](https://img.shields.io/badge/VM_Runner-QEMU+noVNC-blue?style=flat-square&logo=qemu&logoColor=white)](https://github.com/kiraadityaa/universal-vm-runner)
[![Runner](https://img.shields.io/badge/Runner-macOS_Intel-000000?style=flat-square&logo=apple&logoColor=white)](https://github.com/actions/runner-images)
[![Tunnel](https://img.shields.io/badge/Tunnel-Cloudflare-brightgreen?style=flat-square)](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

- **English**: [README.md](README.md)

---

## Apa ini?

Pengen menjalankan distro Linux di cloud, main-main installer, mencoba live ISO, atau menjalankan workload server — semua dari browser, gratis, tanpa sewa VPS?

**Universal VM Runner** menjalankan emulator QEMU di **runner macOS Intel gratis dari GitHub** (4 vCPU / 14 GB RAM di repo publik) dan meneruskan tampilan VM ke Anda lewat:

1. **QEMU** — mengemulasi mesin penuh, boot ISO yang Anda berikan
2. **VNC (port 5900)** — server VNC bawaan QEMU
3. **noVNC** — klien VNC berbasis HTML5 di port 6080
4. **Cloudflare Quick Tunnel** — tunnel HTTPS gratis, tanpa akun

Anda cukup memberi satu hal: **link langsung ke ISO**. Workflow mengembalikan satu URL. Buka, dan Anda melihat VM asli sedang boot.

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
        ├─ VM QEMU: -cdrom ISO -boot order=cd   ← boot self-healing
        ├─ noVNC → WebSocket :6080
        └─ Cloudflare Quick Tunnel → https://xxx.trycloudflare.com
```

Buka URL yang tercetak di browser → lihat VM → install OS → reboot → VM tetap jalan.

### Boot self-healing (tanpa jebakan "no bootable device")

Setiap restart menjalankan perintah QEMU **yang sama** dengan `-boot order=cd` — firmware mencoba **hard disk lebih dulu**, dan **fallback ke ISO** selama disk belum bootable. Jadi:

| Situasi | Hasil |
|---|---|
| Install belum selesai, terjadi reboot | Disk belum bootable → otomatis masuk lagi ke **ISO installer** |
| Install selesai + reboot | Disk bootable → otomatis boot ke **OS terpasang** |
| Reboot di dalam OS terpasang | Disk bootable → tetap di **OS terpasang** |
| Disk rusak permanen | Fallback ke ISO; jalankan ulang workflow untuk disk baru |

Tanpa state machine fase, tanpa asumsi "reboot = installer selesai" — firmware yang memutuskan.

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

4. Jalankan, tunggu ~1–2 menit, lalu buka URL **`https://…trycloudflare.com/vnc.html…`** yang tercetak di log langkah `Run Universal VM`.

> Catatan: runner macOS GitHub **gratis & unlimited di repo publik**. Di repo **privat**, label macOS dihitung 10× kredit Actions dan dibatasi di paket gratis.

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
- **ISO tetap terpasang** di OS terpasang — tidak berbahaya (disk boot lebih dulu); prompt Debian "remove installation media" hanya informasi, Enter tetap boot OS Anda.
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
| `scripts/qemu/setup-vm.sh` | Sisanya: unduh ISO, deteksi arch/HVF, qcow2, noVNC + tunnel, loop reboot QEMU |

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
│   └── setup-vm.sh          # Siklus hidup QEMU: ISO, disk, VM, noVNC, tunnel
├── README.md
├── README.id.md
└── LICENSE                  # MIT
```

## Proyek terkait

Proyek ini lahir dari fitur di dalam **RICH Linux CRD** ([kiraadityaa/rich-linux-crd](https://github.com/kiraadityaa/rich-linux-crd)) — desktop Chrome Remote Desktop di GitHub Actions — dan dipisah agar modular.

## Lisensi

MIT — lihat [LICENSE](LICENSE).