"""Publish a small JSON state file for external dashboards.

Writes the latest fan RPM, PWM duty %, temperature, mode, active mode settings
and link status to ~/.local/state/fancontroller/state.json on every update.
Other programs can read this file without talking to the GTK UI or serial
thread.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")) / "fancontroller"
STATE_PATH = STATE_DIR / "state.json"


def read() -> dict[str, Any] | None:
    """Read the daemon's latest published state, if available."""
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def publish(
    rpm: int,
    duty_byte: int,
    duty_pct: float,
    temp: float | None,
    mode: str,
    status: str,
    max_speed: bool = False,
    active_settings: dict[str, Any] | None = None,
    local_temp: float | None = None,
    temperature_override: dict[str, Any] | None = None,
) -> None:
    """Write current fan state to the shared JSON file."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "rpm": int(rpm),
            "duty_byte": int(duty_byte),
            "duty_pct": float(duty_pct),
            "temp": float(temp) if temp is not None else None,
            "local_temp": float(local_temp) if local_temp is not None else None,
            "temperature_override": dict(temperature_override or {}),
            "temperature_override_active": bool(temperature_override),
            "mode": str(mode),
            "active_settings": dict(active_settings or {}),
            "status": str(status),
            "max_speed": bool(max_speed),
            "ts": time.time(),
        }
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
    except OSError:
        # State publishing is best-effort; don't disturb the control loop.
        pass
