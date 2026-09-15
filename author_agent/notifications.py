from __future__ import annotations

import logging
import os
import shutil
import subprocess

LOG = logging.getLogger(__name__)


def send_desktop_notification(title: str, message: str) -> bool:
    """Best-effort Linux desktop notification. Never raises for delivery failures."""
    if not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY") or os.getenv("DBUS_SESSION_BUS_ADDRESS")):
        LOG.warning("Desktop notification skipped: no desktop session environment detected.")
        return False
    binary = shutil.which("notify-send")
    if not binary:
        LOG.warning("Desktop notification skipped: `notify-send` is not installed.")
        return False
    try:
        proc = subprocess.run(
            [binary, "--app-name=Author Agent", title, message],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.warning("Desktop notification failed: %s", exc)
        return False
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown notify-send error").strip()
        LOG.warning("Desktop notification failed: %s", detail)
        return False
    return True
