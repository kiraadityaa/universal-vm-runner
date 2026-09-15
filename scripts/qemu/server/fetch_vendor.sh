#!/bin/bash
# fetch_vendor.sh — Download xterm.js + noVNC client assets into static/vendor.
# Run from this directory (scripts/qemu/server).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="${HERE}/static/vendor"
mkdir -p "${VENDOR}/xterm" "${VENDOR}/novnc"

C='\033[1;96m'; G='\033[0;32m'; Y='\033[1;33m'; N='\033[0m'
echo -e "${C}[vendor] fetching xterm.js + noVNC${N}"

# ---- xterm.js (UMD bundles, latest 5.x) ----
XTERM_VER="${XTERM_VER:-5.3.0}"
BASE="https://cdn.jsdelivr.net/npm/@xterm/xterm@${XTERM_VER}/lib"
for f in xterm.js xterm.css; do
  if [ ! -f "${VENDOR}/xterm/${f}" ]; then
    echo -e "  ${C}->${N} ${f} (v${XTERM_VER})"
    curl -fsSL -o "${VENDOR}/xterm/${f}" "${BASE}/${f}" || {
      echo -e "${Y}  first fetch failed, retrying raw.githubusercontent${N}"
      curl -fsSL -o "${VENDOR}/xterm/${f}" \
        "https://raw.githubusercontent.com/xtermjs/xterm.js/${XTERM_VER}/lib/${f}" || true
    }
  fi
done

for f in xterm-addon-fit.js xterm-addon-attach.js; do
  ADDON=$(echo "$f" | sed 's/xterm-//; s/\.js//')
  if [ ! -f "${VENDOR}/xterm/${f}" ]; then
    echo -e "  ${C}->${N} ${f} (v${XTERM_VER})"
    curl -fsSL -o "${VENDOR}/xterm/${f}" \
      "https://cdn.jsdelivr.net/npm/@xterm/${ADDON}@${XTERM_VER}/lib/${f}" || true
  fi
done

# ---- noVNC (client files only) ----
if [ ! -f "${VENDOR}/novnc/vnc.html" ]; then
  echo -e "  ${C}->${N} noVNC (depth 1 clone)"
  git clone --depth 1 https://github.com/novnc/noVNC.git "${VENDOR}/novnc" || {
    echo -e "${Y}  clone failed — noVNC will be fetched by setup-vm.sh${N}"
  }
fi

echo -e "${G}[vendor] done${N}"
echo "  vendor/xterm:  $(ls ${VENDOR}/xterm 2>/dev/null | tr '\n' ' ')"
echo "  vendor/novnc:  $(test -f ${VENDOR}/novnc/vnc.html && echo 'present' || echo 'MISSING — run setup-vm.sh which clones noVNC')"