"""Read optional, short-lived control overrides from external tools.

An external tool can drop a JSON file at
``~/.local/state/fancontroller/control.json``. ``max_speed`` forces 100% duty,
while ``temperature_override`` supplies an expiring external sensor reading.
The latter is combined with local sensors using ``max()`` so an external tool
can never make the fan run cooler than local telemetry requires. FanController
works normally when this file is absent.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path


CONTROL_DIR = Path(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")) / "fancontroller"
CONTROL_PATH = CONTROL_DIR / "control.json"

@dataclass(frozen=True)
class ExternalControl:
    max_speed: bool = False
    temperature_c: float | None = None
    source: str | None = None
    node_id: str | None = None
    node_name: str | None = None
    observed_at: float | None = None
    expires_at: float | None = None


_cached_data: dict[str, object] | None = None
_cached_mtime: float | None = None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def read_control(now: float | None = None) -> ExternalControl:
    """Return validated, currently active external control inputs.

    Results are cached keyed on the file's mtime so we don't hit disk on
    every poll tick. Expiry is evaluated on every call even when cached.
    """
    global _cached_data, _cached_mtime
    try:
        mtime = CONTROL_PATH.stat().st_mtime_ns
    except OSError:
        _cached_data = None
        _cached_mtime = None
        return ExternalControl()
    if _cached_mtime != mtime:
        try:
            raw = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
            _cached_data = raw if isinstance(raw, dict) else None
        except Exception:
            _cached_data = None
        _cached_mtime = mtime

    data = _cached_data or {}
    result = ExternalControl(max_speed=bool(data.get("max_speed", False)))
    override = data.get("temperature_override")
    if not isinstance(override, dict):
        return result
    temperature_c = _number(override.get("temperature_c"))
    expires_at = _number(override.get("expires_at"))
    current_time = time.time() if now is None else float(now)
    if (temperature_c is None or temperature_c < -40 or temperature_c > 150
            or expires_at is None or expires_at < current_time):
        return result

    def text(key: str) -> str | None:
        value = override.get(key)
        return value if isinstance(value, str) and value else None

    return ExternalControl(
        max_speed=result.max_speed,
        temperature_c=temperature_c,
        source=text("source"),
        node_id=text("node_id"),
        node_name=text("node_name"),
        observed_at=_number(override.get("observed_at")),
        expires_at=expires_at,
    )


def effective_temperature(
    local_temperature_c: float | None,
    control: ExternalControl,
) -> float | None:
    """Use the hottest valid local or external temperature."""
    temperatures = [
        value for value in (local_temperature_c, control.temperature_c)
        if value is not None
    ]
    return max(temperatures) if temperatures else None


def read_max_speed() -> bool:
    """Backward-compatible helper for max-speed-only integrations."""
    return read_control().max_speed


def clear_max_speed() -> None:
    """Clear max speed without discarding unrelated external controls."""
    global _cached_data, _cached_mtime
    try:
        raw = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        data = raw if isinstance(raw, dict) else {}
        data.pop("max_speed", None)
        if data:
            tmp = CONTROL_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, CONTROL_PATH)
        else:
            CONTROL_PATH.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError):
        pass
    _cached_data = None
    _cached_mtime = None
