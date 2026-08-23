"""Headless fan-control daemon.

This process owns the serial connection and applies the saved configuration.
It deliberately has no GTK dependency, so it can run from the user systemd
manager before (and without) a graphical login.
"""
from __future__ import annotations

import fcntl
import logging
import os
import signal
import time

from .control_reader import effective_temperature, read_control
from .controller import (
    FanCurve,
    Hysteresis,
    PID,
    SlewLimiter,
    TempSmoother,
    byte_to_pct,
    pct_to_byte,
)
from .sensors import aggregate_max, discover
from .serial_link import SerialLink
from .settings import CONFIG_PATH, Settings
from .state_publisher import STATE_DIR, publish

log = logging.getLogger("fancontroller.daemon")
LOCK_PATH = STATE_DIR / "daemon.lock"


class FanDaemon:
    def __init__(self) -> None:
        self.stopping = False
        self.rpm = 0
        self.status = "starting…"
        self.settings_mtime_ns: int | None = None
        self.link: SerialLink | None = None
        self._load_settings(initial=True)

    def _config_mtime(self) -> int | None:
        try:
            return os.stat(CONFIG_PATH).st_mtime_ns
        except OSError:
            return None

    def _load_settings(self, initial: bool = False) -> None:
        old_port = None if initial else self.settings.serial_port
        self.settings = Settings.load()
        self.settings_mtime_ns = self._config_mtime()

        self.sources = discover()
        source_map = {source.key: source for source in self.sources}
        self.selected_sources = [
            source_map[key] for key in self.settings.sources if key in source_map
        ]
        self.curve = FanCurve(
            [(point[0], point[1]) for point in self.settings.curve_points],
            self.settings.min_floor_pct,
        )
        self.pid = PID(
            self.settings.kp,
            self.settings.ki,
            self.settings.kd,
            self.settings.setpoint,
            self.settings.min_floor_pct,
        )
        self.hyst = Hysteresis(
            self.settings.hyst_on_temp,
            self.settings.hyst_off_temp,
        )
        self.temp_smoother = TempSmoother()
        self.slew = SlewLimiter()

        if initial or old_port != self.settings.serial_port:
            if self.link is not None:
                self.link.stop()
            self.link = SerialLink(
                self.settings.serial_port,
                self._on_rpm,
                self._on_status,
            )
            self.link.start()
        log.info("loaded configuration (mode=%s, port=%s)",
                 self.settings.mode, self.settings.serial_port)

    def _on_rpm(self, rpm: int) -> None:
        self.rpm = int(rpm)

    def _on_status(self, status: str) -> None:
        self.status = status
        log.info("serial: %s", status)

    def _target_duty(
        self, temp: float | None, now: float, max_speed: bool = False,
    ) -> tuple[int, bool]:
        if max_speed or temp is None:
            self.slew.sync(100.0, now)
            return 255, max_speed

        ctrl_temp = self.temp_smoother.update(
            temp, now, self.settings.temp_smoothing_s
        )
        mode = self.settings.mode
        if mode == "curve":
            raw = self.curve.update(ctrl_temp, now)
        elif mode == "pid":
            raw = self.pid.update(ctrl_temp, now)
        elif mode == "hysteresis":
            raw = self.hyst.update(ctrl_temp, now)
        elif mode == "manual":
            raw = pct_to_byte(self.settings.manual_duty_pct)
        else:
            log.error("unknown mode %r; forcing full speed", mode)
            raw = 255
        output_pct = self.slew.update(
            byte_to_pct(raw), now, self.settings.max_duty_rate_pct_per_s
        )
        return pct_to_byte(output_pct), max_speed

    def poll(self) -> None:
        current_mtime = self._config_mtime()
        if current_mtime != self.settings_mtime_ns:
            self._load_settings()

        local_temp = aggregate_max(self.selected_sources) if self.selected_sources else None
        control = read_control()
        temp = effective_temperature(local_temp, control)
        duty, max_speed = self._target_duty(
            temp, time.monotonic(), control.max_speed,
        )
        assert self.link is not None
        self.link.set_duty(duty)
        display_rpm = (
            int(round(byte_to_pct(duty) / 100.0 * self.settings.max_rpm))
            if self.settings.max_rpm > 0 else self.rpm
        )
        publish(
            rpm=display_rpm,
            duty_byte=duty,
            duty_pct=byte_to_pct(duty),
            temp=temp,
            mode=self.settings.mode,
            status=self.status,
            max_speed=max_speed,
            active_settings=self.settings.active_settings(),
            local_temp=local_temp,
            temperature_override={
                "temperature_c": control.temperature_c,
                "source": control.source,
                "node_id": control.node_id,
                "node_name": control.node_name,
                "observed_at": control.observed_at,
                "expires_at": control.expires_at,
            } if control.temperature_c is not None else None,
        )

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "stopping", True))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stopping", True))
        while not self.stopping:
            started = time.monotonic()
            try:
                self.poll()
            except Exception:
                log.exception("control poll failed")
                if self.link is not None:
                    self.link.set_duty(255)
            interval = max(0.05, float(self.settings.poll_interval_s))
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
        if self.link is not None:
            self.link.stop()


def _acquire_lock() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise RuntimeError("fan-control daemon is already running") from exc
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    lock_fd = _acquire_lock()
    FanDaemon().run()
    os.close(lock_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
