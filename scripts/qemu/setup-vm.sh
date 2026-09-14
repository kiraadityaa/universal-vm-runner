#!/bin/bash
# setup-vm.sh — Universal VM runner: QEMU + noVNC + Cloudflare Quick Tunnel
#
# Alur:
#   1. Download ISO dari URL yang diberikan user
#   2. Deteksi arsitektur ISO (arm64 / x86_64)
#   3. Buat disk image qcow2 (sparse allocation)
#   4. Setup noVNC + websockify (port 6080 → VNC TCP 5900)
#   5. Jalankan Cloudflare Quick Tunnel → URL publik
#   6. Jalankan QEMU VM dengan -boot order=cd (disk dulu, fallback ISO — self-healing)
#
# Cara pakai (dari GitHub Actions):
#   ISO_URL=https://... VM_MEMORY=2G VM_CPUS=2 DISK_SIZE=20G \
#     ./scripts/qemu/setup-vm.sh
#
# Prasyarat: QEMU + cloudflared sudah terinstall (brew install qemu cloudflared).
#
# Catatan:
#   - QEMU VNC server di port 5900 (TCP), noVNC bridge ke WebSocket 6080.
#   - -no-reboot: QEMU exit saat guest reboot → loop restart perintah yang sama (self-healing).
#   - -boot order=cd: SeaBIOS/EFI coba hard disk dulu, fallback ke ISO selagi disk belum bootable.
#   - Quick Tunnel (TryCloudflare) gratis, URL acak, ephemeral.

set -euo pipefail

# ============================================================
# ANSI COLORS
# ============================================================
C_RED='\033[1;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[1;33m'
C_CYAN='\033[1;36m'
C_BLUE='\033[0;34m'
C_BOLD='\033[1m'
C_NC='\033[0m'

step()  { echo -e "\n${C_CYAN}[$1/$TOTAL_STEPS] ${C_BOLD}$2${C_NC}"; }
ok()    { echo -e "  ${C_GREEN}[OK]${C_NC} $1"; }
warn()  { echo -e "  ${C_YELLOW}[WARN]${C_NC} $1"; }
fail()  { echo -e "  ${C_RED}[FAIL]${C_NC} $1"; }
info()  { echo -e "  ${C_BLUE}[INFO]${C_NC} $1"; }

# ============================================================
# INPUTS
# ============================================================
TOTAL_STEPS=8

ISO_URL="${ISO_URL:?ISO_URL is required}"
VM_MEMORY="${VM_MEMORY:-2G}"
VM_CPUS="${VM_CPUS:-2}"
DISK_SIZE="${DISK_SIZE:-20G}"
KEEP_ALIVE_MINUTES="${KEEP_ALIVE_MINUTES:-360}"

WORK_DIR="${WORK_DIR:-$(pwd)}"
ISO_FILE="${WORK_DIR}/installer.iso"
DISK_FILE="${WORK_DIR}/disk.qcow2"
NOVNC_DIR="/tmp/noVNC"
SERIAL_LOG="${WORK_DIR}/vm-serial.log"

echo -e "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_NC}"
echo -e "${C_CYAN}  ${C_BOLD}UNIVERSAL VM RUNNER - QEMU + noVNC + Cloudflare Tunnel${C_NC}"
echo -e "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_NC}"
echo ""
echo -e "  ${C_BLUE}ISO:${C_NC}       ${ISO_URL}"
echo -e "  ${C_BLUE}Memory:${C_NC}    ${VM_MEMORY}"
echo -e "  ${C_BLUE}CPUs:${C_NC}      ${VM_CPUS}"
echo -e "  ${C_BLUE}Disk:${C_NC}      ${DISK_SIZE}"
echo ""

# ============================================================
# STEP 1: CHECK DISK SPACE
# ============================================================
step 1 "Checking disk space..."
FREE_KB=$(df -k / | awk 'NR==2{print $4}')
FREE_GB=$((FREE_KB / 1048576))
echo "  Free: ~${FREE_GB} GB"
if [ "$FREE_GB" -lt 5 ]; then
  warn "Low disk space (< 5 GB). Large ISOs may fail."
fi

# ============================================================
# STEP 2: DOWNLOAD ISO
# ============================================================
step 2 "Downloading ISO..."
if [ -f "$ISO_FILE" ]; then
  info "ISO already exists, skipping download."
else
  HTTP_CODE=$(curl -L -# -w "%{http_code}" -o "$ISO_FILE" "$ISO_URL" 2>/dev/null || true)
  if [ ! -f "$ISO_FILE" ]; then
    fail "Download failed (HTTP ${HTTP_CODE})."
    exit 1
  fi
  if [ "$HTTP_CODE" != "200" ]; then
    warn "HTTP ${HTTP_CODE} — file may be partial, continuing anyway."
  fi
fi
ISO_SIZE=$(du -h "$ISO_FILE" | cut -f1)
ok "Downloaded: ${ISO_SIZE}"

# ============================================================
# STEP 3: DETECT HOST + ISO ARCH, PICK QEMU CONFIG
# ============================================================
step 3 "Detecting host + ISO architecture..."
ISO_URL_LOWER=$(echo "$ISO_URL" | tr '[:upper:]' '[:lower:]')
ISO_BASENAME=$(basename "$ISO_URL" | tr '[:upper:]' '[:lower:]')

HOST_ARCH="x86_64"
case "$(uname -m 2>/dev/null)" in
  arm64|aarch64) HOST_ARCH="arm64" ;;
esac
info "Host architecture: ${HOST_ARCH}"

if echo "${ISO_URL_LOWER} ${ISO_BASENAME}" | grep -qiE '(arm64|aarch64)'; then
  GUEST_ARCH="arm64"
  ARCH_LABEL="ARM64"
elif echo "${ISO_URL_LOWER} ${ISO_BASENAME}" | grep -qiE '(amd64|x86_64|x64)'; then
  GUEST_ARCH="x86_64"
  ARCH_LABEL="x86_64"
else
  GUEST_ARCH="$HOST_ARCH"
  ARCH_LABEL="unknown (defaulting to ${HOST_ARCH})"
  warn "Could not detect ISO architecture — assuming ${HOST_ARCH}."
fi
ok "ISO architecture: ${ARCH_LABEL}"

if [ "$GUEST_ARCH" != "$HOST_ARCH" ]; then
  warn "Guest (${GUEST_ARCH}) != host (${HOST_ARCH}) — TCG lintas-arsitektur, akan sangat lambat."
  warn "Gunakan ISO yang sesuai arsitektur runner: ${HOST_ARCH}."
fi

# QEMU binary + machine model by guest architecture
if [ "$GUEST_ARCH" = "x86_64" ]; then
  QEMU_BIN="qemu-system-x86_64"
  QEMU_MACHINE="q35"
  GUEST_CPU_TEMPLATE="qemu64"
else
  QEMU_BIN="qemu-system-aarch64"
  QEMU_MACHINE="virt"
  GUEST_CPU_TEMPLATE="cortex-a72"
fi

# HVF detection (macOS Hypervisor.framework)
HVF_OK=0
if [ "$(sysctl -n kern.hv_support 2>/dev/null || echo 0)" = "1" ]; then
  HVF_OK=1
fi

# Accelerator + CPU choice
if [ "$HVF_OK" -eq 1 ] && [ "$GUEST_ARCH" = "$HOST_ARCH" ]; then
  QEMU_MODE_LABEL="HVF (hardware-accelerated)"
  ok "HVF tersedia — memakai akselerasi hardware."
  QEMU_ACCEL=(-accel hvf)
  QEMU_CPU=(host)
elif [ "$GUEST_ARCH" = "$HOST_ARCH" ]; then
  QEMU_MODE_LABEL="TCG same-arch"
  ok "HVF tidak tersedia — memakai TCG same-arch."
  QEMU_ACCEL=(-accel tcg)
  QEMU_CPU=("$GUEST_CPU_TEMPLATE")
else
  QEMU_MODE_LABEL="TCG cross-arch"
  warn "Cross-arch TCG — performa jauh lebih lambat."
  QEMU_ACCEL=(-accel tcg)
  QEMU_CPU=("$GUEST_CPU_TEMPLATE")
fi
info "QEMU: ${QEMU_BIN} | machine=${QEMU_MACHINE} | cpu=${QEMU_CPU[*]} | ${QEMU_MODE_LABEL}"

command -v "$QEMU_BIN" >/dev/null 2>&1 || {
  fail "${QEMU_BIN} not found (brew install qemu)."
  exit 1
}

# ============================================================
# STEP 4: CREATE DISK IMAGE
# ============================================================
step 4 "Creating disk image (${DISK_SIZE})..."
if [ -f "$DISK_FILE" ]; then
  info "Disk image already exists, skipping creation."
else
  qemu-img create -f qcow2 "$DISK_FILE" "$DISK_SIZE"
fi
DISK_ACTUAL=$(du -h "$DISK_FILE" | cut -f1)
ok "Disk ready: ${DISK_ACTUAL} (sparse, grows on demand)"

# ============================================================
# STEP 5: SETUP noVNC + WEBSOCKIFY
# ============================================================
step 5 "Setting up noVNC..."
if [ ! -d "${NOVNC_DIR}/utils" ]; then
  git clone --depth 1 https://github.com/novnc/noVNC.git "$NOVNC_DIR"
fi
if [ ! -d "${NOVNC_DIR}/utils/websockify" ]; then
  git clone --depth 1 https://github.com/novnc/websockify.git "${NOVNC_DIR}/utils/websockify"
fi
chmod +x "${NOVNC_DIR}/utils/novnc_proxy"
ok "noVNC ready at ${NOVNC_DIR}"

# ============================================================
# STEP 6: START noVNC PROXY + CLOUDFLARE TUNNEL
# ============================================================
step 6 "Starting noVNC proxy + Cloudflare tunnel..."

pkill -f "novnc_proxy" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 1

nohup "${NOVNC_DIR}/utils/novnc_proxy" \
  --vnc localhost:5900 \
  --listen 127.0.0.1:6080 \
  > /tmp/novnc.log 2>&1 &
NOVNC_PID=$!
sleep 2

if ! kill -0 "$NOVNC_PID" 2>/dev/null; then
  fail "noVNC proxy failed to start. Log:"
  cat /tmp/novnc.log
  exit 1
fi
ok "noVNC proxy running (PID: ${NOVNC_PID})"

TUNNEL_URL=""
_start_cloudflared(){
  nohup cloudflared tunnel --url http://127.0.0.1:6080 --no-autoupdate \
    > /tmp/cf-tunnel.log 2>&1 &
  CF_PID=$!
}

_wait_for_tunnel(){
  local max_wait=$1 label=$2
  info "Menunggu Cloudflare tunnel URL (maks ${max_wait}s)... "
  for i in $(seq 1 "$max_wait"); do
    if ! kill -0 "$CF_PID" 2>/dev/null; then
      warn "cloudflared mati di detik ${i}. Restarting..."
      _start_cloudflared
    fi
    TUNNEL_URL=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' /tmp/cf-tunnel.log | head -1)
    if [ -n "$TUNNEL_URL" ]; then
      ok "Tunnel URL diterima di detik ${i}."
      return 0
    fi
    if [ $((i % 15)) -eq 0 ]; then
      warn "Belum ada URL (${i}/${max_wait}s). Log cloudflared:"
      tail -5 /tmp/cf-tunnel.log 2>/dev/null | sed 's/^/    /' || true
    fi
    sleep 1
  done
  return 1
}

_start_cloudflared
if ! _wait_for_tunnel 120 "first"; then
  warn "Percobaan pertama gagal — retry dengan cloudflared baru..."
  pkill -f "cloudflared tunnel" 2>/dev/null || true
  sleep 3
  _start_cloudflared
  if ! _wait_for_tunnel 60 "retry"; then
    fail "Cloudflare tunnel gagal setelah 2 percobaan. Full log:"
    cat /tmp/cf-tunnel.log 2>/dev/null || echo "(log kosong)"
    exit 1
  fi
fi

NOVNC_URL="${TUNNEL_URL}/vnc.html?autoconnect=true&resize=scale&reconnect=true&reconnect_delay=3000"

echo ""
echo -e "${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_NC}"
echo -e "${C_GREEN}  Connect via noVNC: ${C_BOLD}${NOVNC_URL}${C_NC}"
echo -e "${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_NC}"
echo ""
echo "${NOVNC_URL}" > "${WORK_DIR}/novnc-url.txt"

# ============================================================
# STEP 7: WAIT FOR VNC PORT
# ============================================================
step 7 "Waiting for QEMU VNC port 5900..."
# VNC port will be opened by QEMU (started in step 8)

# ============================================================
# STEP 8: RUN QEMU VM (reboot loop)
# ============================================================
step 8 "Starting QEMU VM..."

QEMU_COMMON=(
  -machine "$QEMU_MACHINE"
  -cpu "${QEMU_CPU[@]}"
  "${QEMU_ACCEL[@]}"
  -smp "$VM_CPUS"
  -m "$VM_MEMORY"
  -drive "file=${DISK_FILE},if=virtio,format=qcow2"
  -vnc :0
  -display none
  -device virtio-net-pci,netdev=net0
  -netdev "user,id=net0,hostfwd=tcp::8022-:22"
  -device virtio-gpu-pci
  -device virtio-keyboard-pci
  -device virtio-mouse-pci
  -serial "file:${SERIAL_LOG}"
)

RESTART_COUNT=0
KEEP_ALIVE_SECONDS=$((KEEP_ALIVE_MINUTES * 60))
START_TIME=$(date +%s)
SHORT_EXITS=0

info "SSH guest port-forward: host 127.0.0.1:8022 -> guest :22 (port 22 host dipakai SSHD runner)"
info "Boot order: hard disk dulu, fallback ke ISO selagi disk belum bootable (self-healing)."

# Unified self-healing boot:
#   - Setiap restart menjalankan perintah QEMU yang SAMA: -cdrom + -boot order=cd.
#   - SeaBIOS/EFI mencoba hard disk (c) dulu; kalau belum bootable, fallback ke ISO (d).
#   - Tidak ada asumsi "reboot = installer selesai"; BIOS yang memutuskan mau boot apa.
#   - -no-reboot: guest reboot/poweroff -> QEMU exit -> loop restart perintah yang sama.
while true; do
  ELAPSED=$(( $(date +%s) - START_TIME ))
  REMAIN=$(( KEEP_ALIVE_SECONDS - ELAPSED ))
  if [ "$REMAIN" -le 0 ]; then
    info "Keep-alive time exceeded (${KEEP_ALIVE_MINUTES} min). Session ending."
    break
  fi
  info "Session remaining: ~$((REMAIN / 60)) min"

  QEMU_START=$(date +%s)
  echo -e "  ${C_CYAN}[BOOT #${RESTART_COUNT}] disk -> fallback ISO${C_NC}"
  set +e
  "$QEMU_BIN" "${QEMU_COMMON[@]}" -no-reboot -cdrom "$ISO_FILE" -boot order=cd
  QEMU_EXIT=$?
  set -e
  QEMU_END=$(date +%s)
  QEMU_DURATION=$((QEMU_END - QEMU_START))
  echo -e "  ${C_YELLOW}[INFO] QEMU exited (rc=${QEMU_EXIT}) after ${QEMU_DURATION}s.${C_NC}"

  # Short exit = kemungkinan crash, tapi jangan berhenti: disk/ISO masih jadi fallback.
  # Session tetap hidup sampai keepalive habis.
  if [ "$QEMU_DURATION" -lt 30 ]; then
    SHORT_EXITS=$((SHORT_EXITS + 1))
    warn "QEMU berhenti cepat (${QEMU_DURATION}s, #${SHORT_EXITS} berturut-turut) — kemungkinan crash."
    if [ "$SHORT_EXITS" -ge 3 ]; then
      warn "Banyak short-exit. Cek isi VM via VNC: jika 'no bootable device' muncul, boot akan otomatis"
      warn "kembali ke ISO karena -boot order=cd. Kalau disk rusak permanen, re-run workflow saja."
    fi
    sleep 5
  else
    SHORT_EXITS=0
  fi

  RESTART_COUNT=$((RESTART_COUNT + 1))
  info "Reboot #${RESTART_COUNT} — restarting QEMU (back online in a few seconds)..."
  sleep 2
done

echo ""
echo -e "${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_NC}"
echo -e "${C_GREEN}  Session ended. Tunnel: ${TUNNEL_URL}${C_NC}"
echo -e "${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_NC}"