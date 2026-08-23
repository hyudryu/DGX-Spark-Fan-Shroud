"""JSON-backed settings at ~/.config/fancontroller/config.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

CONFIG_DIR = os.path.expanduser("~/.config/fancontroller")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CURVE: list[list[float]] = [
    [40.0, 0.0],
    [60.0, 30.0],
    [75.0, 60.0],
    [90.0, 100.0],
]


@dataclass
class Settings:
    serial_port: str = "MOCK"
    sources: list[str] = field(default_factory=lambda: ["cpu"])

    mode: str = "curve"  # "curve" | "pid" | "hysteresis" | "manual"

    # curve mode
    curve_points: list[list[float]] = field(
        default_factory=lambda: [list(p) for p in DEFAULT_CURVE]
    )
    curve_min_temp: float = 30.0
    curve_max_temp: float = 100.0

    # pid mode
    setpoint: float = 65.0
    kp: float = 4.0
    ki: float = 0.2
    kd: float = 1.0
    min_floor_pct: float = 0.0

    # hysteresis mode
    hyst_on_temp: float = 75.0
    hyst_off_temp: float = 65.0

    # manual mode
    manual_duty_pct: float = 100.0

    poll_interval_s: float = 1.0
    start_minimized: bool = True

    # output smoothing / ramping
    temp_smoothing_s: float = 5.0  # EMA time constant; 0 disables
    max_duty_rate_pct_per_s: float = 10.0  # max fan duty change rate

    # fan's rated max RPM; 0 = show tach-reported RPM instead of estimate
    max_rpm: int = 3000

    def active_settings(self) -> dict[str, object]:
        """Return only the settings used by the active control mode."""
        if self.mode == "curve":
            return {
                "curve_points": [list(point) for point in self.curve_points],
                "curve_min_temp": float(self.curve_min_temp),
                "curve_max_temp": float(self.curve_max_temp),
                "min_floor_pct": float(self.min_floor_pct),
            }
        if self.mode == "pid":
            return {
                "setpoint": float(self.setpoint),
                "kp": float(self.kp),
                "ki": float(self.ki),
                "kd": float(self.kd),
                "min_floor_pct": float(self.min_floor_pct),
            }
        if self.mode == "hysteresis":
            return {
                "hyst_on_temp": float(self.hyst_on_temp),
                "hyst_off_temp": float(self.hyst_off_temp),
            }
        if self.mode == "manual":
            return {"manual_duty_pct": float(self.manual_duty_pct)}
        return {}

    @classmethod
    def load(cls) -> "Settings":
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        s = cls()
        for k, v in data.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s

    def save(self) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(self), f, indent=2)
        os.replace(tmp, CONFIG_PATH)
