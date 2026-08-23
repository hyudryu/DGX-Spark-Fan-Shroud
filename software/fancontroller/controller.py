"""Fan-control algorithms: Curve, PID, Hysteresis. All return duty bytes 0..255."""
from __future__ import annotations

import math
from typing import Sequence


def pct_to_byte(pct: float) -> int:
    if pct <= 0:
        return 0
    if pct >= 100:
        return 255
    return int(round(pct * 255.0 / 100.0))


def byte_to_pct(b: int) -> float:
    return b * 100.0 / 255.0


class FanCurve:
    """Piecewise-linear fan curve: list of (temp_C, duty_pct) sorted by temp.

    Below the first point: hold first point's duty.
    Above the last point: hold last point's duty (typically 100).
    """

    def __init__(self, points: Sequence[tuple[float, float]] | None = None,
                 min_floor_pct: float = 0.0) -> None:
        self.points: list[tuple[float, float]] = list(points) if points else [
            (40.0, 0.0), (60.0, 30.0), (75.0, 60.0), (90.0, 100.0)
        ]
        self.min_floor_pct = min_floor_pct
        self._sort()

    def _sort(self) -> None:
        self.points.sort(key=lambda p: p[0])

    def set_points(self, points: Sequence[tuple[float, float]]) -> None:
        self.points = [(float(t), max(0.0, min(100.0, float(d)))) for t, d in points]
        self._sort()

    def evaluate_pct(self, temp: float) -> float:
        if not self.points:
            return self.min_floor_pct
        if temp <= self.points[0][0]:
            duty = self.points[0][1]
        elif temp >= self.points[-1][0]:
            duty = self.points[-1][1]
        else:
            duty = self.points[-1][1]
            for i in range(len(self.points) - 1):
                t0, d0 = self.points[i]
                t1, d1 = self.points[i + 1]
                if t0 <= temp <= t1:
                    f = (temp - t0) / (t1 - t0) if t1 > t0 else 0.0
                    duty = d0 + f * (d1 - d0)
                    break
        return max(self.min_floor_pct, duty)

    def update(self, temp: float, t: float) -> int:
        return pct_to_byte(self.evaluate_pct(temp))

    def reset(self) -> None:
        pass


class PID:
    """Standard PID with anti-windup. Output clamped to byte range."""

    def __init__(self, kp: float = 4.0, ki: float = 0.2, kd: float = 1.0,
                 setpoint: float = 65.0, min_floor_pct: float = 0.0) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.min_floor_pct = min_floor_pct
        self._integral = 0.0
        self._last_err: float | None = None
        self._last_t: float | None = None

    def reset(self) -> None:
        self._integral = 0.0
        self._last_err = None
        self._last_t = None

    def update(self, temp: float, t: float) -> int:
        err = temp - self.setpoint
        if self._last_t is None:
            dt = 0.0
            d_err = 0.0
        else:
            dt = max(1e-3, t - self._last_t)
            d_err = (err - (self._last_err or 0.0)) / dt
        new_i = self._integral + err * dt
        # tentative output to test saturation
        tentative = self.kp * err + self.ki * new_i + self.kd * d_err
        # anti-windup: only accumulate if not deepening saturation
        if not ((tentative > 255 and err > 0) or (tentative < 0 and err < 0)):
            self._integral = new_i
        out = self.kp * err + self.ki * self._integral + self.kd * d_err
        self._last_err = err
        self._last_t = t
        clamped = max(0.0, min(255.0, out))
        floor_byte = pct_to_byte(self.min_floor_pct)
        if clamped < floor_byte:
            clamped = floor_byte
        return int(round(clamped))


class Hysteresis:
    """Bang-bang controller with two thresholds to avoid rapid cycling."""

    def __init__(self, on_temp: float = 75.0, off_temp: float = 65.0,
                 on_duty: int = 255, off_duty: int = 0) -> None:
        self.on_temp = on_temp
        self.off_temp = off_temp
        self.on_duty = on_duty
        self.off_duty = off_duty
        self._on = False

    def reset(self) -> None:
        self._on = False

    def update(self, temp: float, t: float) -> int:
        if not self._on and temp >= self.on_temp:
            self._on = True
        elif self._on and temp <= self.off_temp:
            self._on = False
        return self.on_duty if self._on else self.off_duty


class TempSmoother:
    """Exponential moving average of the temperature.

    tau_s is the EMA time constant in seconds; tau_s <= 0 disables smoothing.
    The first sample (or first after reset) initializes to the raw value.
    """

    def __init__(self) -> None:
        self._value: float | None = None
        self._last_t: float | None = None

    def reset(self) -> None:
        self._value = None
        self._last_t = None

    def update(self, temp: float, t: float, tau_s: float) -> float:
        if tau_s <= 0:
            self._value = temp
            self._last_t = t
            return temp
        if self._value is None or self._last_t is None:
            self._value = temp
        else:
            dt = max(0.0, t - self._last_t)
            alpha = 1.0 - math.exp(-dt / tau_s)
            self._value += alpha * (temp - self._value)
        self._last_t = t
        return self._value


class SlewLimiter:
    """Rate-limits a duty-percent target to rate_pct_per_s, up and down.

    The first call (or first after reset) jumps straight to the target so
    startup behaves like an unlimited controller. sync() forces the internal
    state when the output was set while bypassing the limiter (safety path).
    """

    def __init__(self) -> None:
        self._value: float | None = None
        self._last_t: float | None = None

    def reset(self) -> None:
        self._value = None
        self._last_t = None

    def sync(self, value_pct: float, t: float) -> None:
        self._value = value_pct
        self._last_t = t

    def update(self, target_pct: float, t: float, rate_pct_per_s: float) -> float:
        if self._value is None or self._last_t is None:
            self._value = target_pct
        else:
            dt = max(0.0, t - self._last_t)
            max_step = max(0.0, rate_pct_per_s) * dt
            delta = target_pct - self._value
            if delta > max_step:
                delta = max_step
            elif delta < -max_step:
                delta = -max_step
            self._value += delta
        self._last_t = t
        return self._value
