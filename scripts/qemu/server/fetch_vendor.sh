#!/bin/bash
# fetch_vendor.sh — Download xterm.js + noVNC client assets into static/vendor.
# Run from this directory (scripts/qemu/server).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="${HERE}/static/vendor"
mkdir -p "${VENDOR}/xterm" "${VENDOR}/novnc"

C='\033[1;96m'; G='\033[0;32m'; Y='\033[1;33m'; N='\033[0m'
echo -e "${C}[vendor] fetching xterm.js + noVNC${N}"

# Versi xterm core dan addon rilis terpisah.
XTERM_VER="${XTERM_VER:-5.5.0}"
ADDON_FIT_VER="${ADDON_FIT_VER:-0.10.0}"
ADDON_ATTACH_VER="${ADDON_ATTACH_VER:-0.11.0}"

# fetch <dest> <url1> <url2> ... — coba mirror berurutan (jeda 1s untuk hindari rate-limit CDN).
fetch() {
  local dest="$1"; shift
  local u
  local first=1
  for u in "$@"; do
    if [ "$first" -eq 0 ]; then
      sleep 1
    fi
    first=0
    if curl -fsSL -o "$dest" "$u" 2>/dev/null; then
      return 0
    fi
  done
  return 1
}

fail=0

# ---- xterm.js core (UMD bundles) ----
fetch_core() {
  local f="$1" p="$2"
  if [ ! -f "${VENDOR}/xterm/${f}" ]; then
    echo -e "  ${C}->${N} ${f} (v${XTERM_VER})"
    if ! fetch "${VENDOR}/xterm/${f}" \
        "https://cdn.jsdelivr.net/npm/@xterm/xterm@${XTERM_VER}/${p}" \
        "https://unpkg.com/@xterm/xterm@${XTERM_VER}/${p}"; then
      echo -e "  ${Y}!! ${f} gagal diunduh dari semua mirror${N}"
      fail=1
    fi
  fi
}
fetch_core xterm.js lib/xterm.js
fetch_core xterm.css css/xterm.css

# ---- xterm.js addons ----
fetch_addon() {
  local name="$1" ver="$2"
  local f="xterm-addon-${name}.js"
  if [ ! -f "${VENDOR}/xterm/${f}" ]; then
    echo -e "  ${C}->${N} ${f} (v${ver})"
    if ! fetch "${VENDOR}/xterm/${f}" \
        "https://cdn.jsdelivr.net/npm/@xterm/addon-${name}@${ver}/lib/addon-${name}.js" \
        "https://unpkg.com/@xterm/addon-${name}@${ver}/lib/addon-${name}.js"; then
      echo -e "  ${Y}!! ${f} gagal diunduh${N}"
      fail=1
    fi
  fi
}
fetch_addon fit "$ADDON_FIT_VER"
fetch_addon attach "$ADDON_ATTACH_VER"

# ---- noVNC (client files only) ----
if [ ! -f "${VENDOR}/novnc/vnc.html" ]; then
  echo -e "  ${C}->${N} noVNC (depth 1 clone)"
  git clone --depth 1 https://github.com/novnc/noVNC.git "${VENDOR}/novnc" >/dev/null 2>&1 || {
    echo -e "${Y}  clone gagal — noVNC akan disiapkan setup-vm.sh${N}"
    fail=1
  }
fi

echo -e "${G}[vendor] done${N}"
echo "  vendor/xterm:  $(ls ${VENDOR}/xterm 2>/dev/null | tr '\n' ' ')"
if [ -f "${VENDOR}/novnc/vnc.html" ]; then
  echo "  vendor/novnc:  present"
else
  echo "  vendor/novnc:  MISSING — akan diclone oleh setup-vm.sh"
fi

exit "$fail"