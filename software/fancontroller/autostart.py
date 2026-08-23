"""Toggle the user-level systemd unit that runs this app on login."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

SERVICE_NAME = "fancontroller.service"
USER_UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
USER_UNIT_PATH = os.path.join(USER_UNIT_DIR, SERVICE_NAME)


def _systemctl(*args: str, timeout: float = 5.0) -> tuple[int, str, str]:
    if not shutil.which("systemctl"):
        return (127, "", "systemctl not found")
    try:
        out = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return (out.returncode, out.stdout.strip(), out.stderr.strip())
    except subprocess.SubprocessError as e:
        return (1, "", str(e))


def is_installed() -> bool:
    return os.path.exists(USER_UNIT_PATH)


def is_enabled() -> Optional[bool]:
    """True if enabled, False if disabled, None if unknown/not installed."""
    if not is_installed():
        return None
    code, out, _ = _systemctl("is-enabled", SERVICE_NAME)
    if code == 0 and out == "enabled":
        return True
    if out in ("disabled", "linked", "static", "masked", ""):
        return False
    return None


def install_unit(unit_text: str) -> tuple[bool, str]:
    """Write the unit file and reload the user daemon."""
    try:
        os.makedirs(USER_UNIT_DIR, exist_ok=True)
        with open(USER_UNIT_PATH, "w") as f:
            f.write(unit_text)
    except OSError as e:
        return (False, f"write failed: {e}")
    code, _, err = _systemctl("daemon-reload")
    if code != 0:
        return (False, err or "daemon-reload failed")
    return (True, "")


def set_enabled(enabled: bool) -> tuple[bool, str]:
    if not is_installed():
        return (False, f"unit not installed at {USER_UNIT_PATH}")
    verb = "enable" if enabled else "disable"
    code, _, err = _systemctl(verb, SERVICE_NAME)
    if code != 0:
        return (False, err or f"{verb} failed")
    return (True, "")
