"""Smart installer monitoring via serial log pattern matching.

State machine:
    IDLE -> BOOTING -> INSTALLING -> READY | FAILED

Uses the serial console output (and QMP events) to classify the VM state.
Only evaluates output produced after the most recent boot marker so stale
lines from previous boot attempts cannot poison the verdict.
"""

import asyncio
import logging
import os
import re
from typing import Callable

logger = logging.getLogger("installer")

STATE_IDLE = "idle"
STATE_BOOTING = "booting"
STATE_INSTALLING = "installing"
STATE_READY = "ready"
STATE_FAILED = "failed"
STATE_UNKNOWN = "unknown"

# Emitted when the VM's boot target becomes the hard disk, i.e. the
# installer finished and the OS now boots on its own.
REBOOT_TO_HDD = re.compile(
    r"(booting from hard disk|Booting from Hard Disk|\\EFI\\BOOT\\BOOTX64\.EFI|"
    r"Windows Boot Manager|start htmlshell|grub.*\.img\.0|systemd-boot|"
    r"rebooting|installation finished|installation complete|install complete|"
    r"press enter to reboot|the installation is now complete)",
    re.IGNORECASE,
)

# Most Linux distros announce the kernel / bootloader via these markers.
BOOT_MARKERS = re.compile(
    r"(Booting from|boot from cd|ISOLINUX|GRUB \d|EFI Boot|Start PXE over IPv4|"
    r"Choosing language|Booting '|Memtest|spectre_v2|acpi: P/(A|0) pointer|"
    r"Linux version|Booting from DVD|start image|SYSLINUX|Press a key to boot)",
    re.IGNORECASE,
)

# Installer-activity fingerprints (sequences that identify the actual
# installation phase, not just booting).
INSTALLER_MARKERS = re.compile(
    r"(Preparing to install|Copying files|partitioning|Installing system|"
    r"Installation progress|Writing data to disk|Configuring installed system|"
    r"Setup is starting services|Installation-Step|Installing (base|packages|"
    r"the system)|unpacking|progress: \d+/|Installing\.\.\.|apt-get (install|"
    r"update)|dnf (install|update)|pacman -S|Starting installer|Debian installer|"
    r"Ubuntu installer|Calamares|Anaconda|Red Hat installer|"
    r"You are now entering|abinstaller.*processing|Installing\.\.\.|"
    r"Installation in progress|Installer.*done|installer.*% complete)",
    re.IGNORECASE,
)

# An explicit "we surrender" from the firmware. Only terminal after the
# firmware exhausted every boot target.
NO_BOOTABLE = re.compile(
    r"(No bootable device\.|BOOTMGR is missing|Boot failed: (not a bootable disk|"
    r"could not read the boot disk)|No bootable medium found|"
    r"Could not find a bootable device|PXE-M0F.*exit)"
    r".*(after|all)|No bootable device",
    re.IGNORECASE,
)

# Emitted by the serial console right before the kernel takes over.
KERNEL_UP = re.compile(
    r"(Linux version|Linux \d)\.(\d)+|FreeBSD|OpenBSD|NetBSD|loader\.3f\.rel|"
    r"Welcome to|login: *$|Debian GNU|Ubuntu \d+",
    re.IGNORECASE,
)


class InstallerMonitor:
    """State machine fed by serial chunks and QMP events."""

    def __init__(self, serial_log: str = "/tmp/vm-serial.log") -> None:
        self.serial_log = serial_log
        self.state = STATE_IDLE
        self.detail = "Waiting for VM"
        self.progress: int | None = None
        self.boot_attempt = 0
        self._last_marker_pos = 0  # byte offset of latest boot marker
        self._history: list[str] = []
        self._listeners: list[Callable[[dict], None]] = []
        self._pending_lines = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------
    def subscribe(self, cb: Callable[[dict], None]) -> None:
        self._listeners.append(cb)

    def feed_serial(self, chunk: bytes) -> None:
        """Feed a raw chunk from the serial socket / log file."""
        text = chunk.decode("utf-8", errors="replace")
        self._pending_lines.append(text)
        # Keep a bounded history for UI display.
        self._history.append(text)
        if len(self._history) > 500:
            self._history = self._history[-500:]

        # Only scan lines that appeared after the last known boot marker.
        self._scan_after_last_marker(text)

    def handle_qmp_event(self, event: dict) -> None:
        """React to QMP async events (GUEST_PANICKED, SHUTDOWN, RESET...)."""
        name = event.get("event", "")

        if name == "GUEST_PANICKED":
            self._set_state(STATE_FAILED, "Guest kernel panicked")
        elif name == "SHUTDOWN":
            # If we were installing, this may be a natural power-off after
            # install finished. Reboot-to-HDD marker already handles the
            # success path; a plain shutdown with no marker is ambiguous.
            if self.state in (STATE_IDLE, STATE_UNKNOWN):
                self._set_state(STATE_UNKNOWN, "VM shut down")
        elif name == "RESET":
            self._set_state(STATE_BOOTING, "VM reset — new boot attempt")

    def get_status(self) -> dict:
        return {
            "state": self.state,
            "detail": self.detail,
            "progress": self.progress,
            "boot_attempt": self.boot_attempt,
            "history": self._history[-80:],
        }

    # ------------------------------------------------------------------
    # Scan logic (scoped to the newest boot attempt)
    # ------------------------------------------------------------------
    def _scan_after_last_marker(self, text: str) -> None:
        # Re-locate the most recent boot marker position inside the chunk.
        for match in BOOT_MARKERS.finditer(text):
            self._last_marker_pos = self._last_marker_pos + match.end()
            self.boot_attempt += 1
            if self.state != STATE_BOOTING:
                self._set_state(STATE_BOOTING, f"Boot attempt #{self.boot_attempt}")

        # "No bootable device" — only terminal if we have NOT seen a boot
        # marker in between (i.e. this is the firmware giving up).
        if NO_BOOTABLE.search(text) and self.boot_attempt == 0:
            self._set_state(STATE_FAILED, "No bootable device detected")
            return

        if REBOOT_TO_HDD.search(text):
            self._set_state(STATE_READY, "System booted from disk — installer finished")
            return

        if self.state == STATE_BOOTING:
            if INSTALLER_MARKERS.search(text):
                self._set_state(STATE_INSTALLING, "Installer is running…")

        if self.state == STATE_INSTALLING:
            m = re.search(r"(\d+)\s*%", text)
            if m:
                self.progress = min(100, int(m.group(1)))

        if self.state != STATE_READY and KERNEL_UP.search(text):
            # Kernel booted into the OS (could still be first-boot setup).
            self._set_state(STATE_INSTALLING if self.state == STATE_BOOTING else self.state)

    def _set_state(self, new_state: str, detail: str) -> None:
        old = self.state
        if old == new_state and not (new_state == STATE_INSTALLING):
            return
        self.state = new_state
        self.detail = detail
        logger.info("Installer state: %s -> %s (%s)", old, new_state, detail)
        for cb in self._listeners:
            try:
                cb(self.get_status())
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Background tailer (falls back to reading the log file)
    # ------------------------------------------------------------------
    async def watch_serial_log(self) -> None:
        """Tail the serial log file as a fallback source of serial data."""
        pos = _file_size(self.serial_log)
        while True:
            await asyncio.sleep(0.5)
            size = _file_size(self.serial_log)
            if size < pos:
                pos = 0  # log was rotated
            if size > pos:
                with open(self.serial_log, "r", errors="replace") as fh:
                    fh.seek(pos)
                    data = fh.read()
                pos = fh.tell()
                if data:
                    self.feed_serial(data.encode())


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0