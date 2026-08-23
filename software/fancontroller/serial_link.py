"""Serial link to the RP2040, plus a MOCK backend that simulates a fan."""
from __future__ import annotations

import glob
import logging
import random
import threading
import time
from typing import Callable, Optional

try:
    import serial as pyserial
    import serial.tools.list_ports as list_ports
except ImportError:
    pyserial = None  # type: ignore
    list_ports = None  # type: ignore

log = logging.getLogger(__name__)

MOCK_PORT = "MOCK"


def list_serial_ports() -> list[tuple[str, str]]:
    """[(device, description)]. Always includes the mock entry first.

    Built-in 16550-style /dev/ttyS* ports are filtered out — fans don't live there.
    """
    out: list[tuple[str, str]] = [(MOCK_PORT, "Mock fan (no hardware)")]
    if list_ports is not None:
        for p in list_ports.comports():
            dev = p.device
            desc = p.description or dev
            if dev.startswith("/dev/ttyS") and (desc == "n/a" or desc == dev):
                continue
            out.append((dev, desc))
    else:
        for d in sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")):
            out.append((d, d))
    return out


class SerialLink:
    """Background thread. Owner sets duty; we send DUTY/PING and surface RPM/status."""

    def __init__(
        self,
        port: str,
        on_rpm: Callable[[int], None],
        on_status: Callable[[str], None],
    ) -> None:
        self.port = port
        self.on_rpm = on_rpm
        self.on_status = on_status
        self._stop = threading.Event()
        self._duty = 0
        self._duty_dirty = True
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._mock_rpm = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def set_duty(self, duty: int) -> None:
        duty = max(0, min(255, int(duty)))
        with self._lock:
            if duty != self._duty:
                self._duty = duty
                self._duty_dirty = True

    # ------ internals ------

    def _run(self) -> None:
        if self.port == MOCK_PORT:
            self._run_mock()
        else:
            self._run_real()

    def _run_mock(self) -> None:
        self.on_status("connected (mock)")
        while not self._stop.is_set():
            with self._lock:
                duty = self._duty
            target = (duty / 255.0) * 5000.0  # 5000 RPM at full speed
            self._mock_rpm += (target - self._mock_rpm) * 0.3
            self.on_rpm(int(self._mock_rpm + random.uniform(-30, 30)))
            time.sleep(1.0)
        self.on_status("disconnected")

    def _run_real(self) -> None:
        import sys

        def dbg(msg: str) -> None:
            print(f"[link {self.port}] {msg}", file=sys.stderr, flush=True)

        SILENCE_S = 5.0     # if no firmware output in this window, reconnect
        REOPEN_DELAY_S = 2.0

        dbg("worker starting")
        if pyserial is None:
            self.on_status("pyserial missing")
            return

        while not self._stop.is_set():
            try:
                ser = pyserial.Serial(self.port, 115200, timeout=0.2)
            except Exception as e:
                self.on_status(f"open failed: {e}")
                dbg(f"open failed: {e!r} — retry in {REOPEN_DELAY_S}s")
                if self._stop.wait(REOPEN_DELAY_S):
                    return
                continue

            self.on_status(f"connected ({self.port})")
            dbg("port open, entering loop")
            with self._lock:
                # Always re-send the duty on a fresh connection
                self._duty_dirty = True
            last_send = 0.0
            last_recv = time.monotonic()
            buf = b""
            sent_count = 0
            reason = ""

            try:
                while not self._stop.is_set():
                    with self._lock:
                        duty = self._duty
                        dirty = self._duty_dirty
                        self._duty_dirty = False
                    now = time.monotonic()
                    if dirty:
                        ser.write(f"DUTY {duty}\n".encode())
                        last_send = now
                        sent_count += 1
                        dbg(f"sent DUTY {duty} (#{sent_count})")
                    elif now - last_send > 1.0:
                        ser.write(b"PING\n")
                        last_send = now
                        sent_count += 1
                        if sent_count % 30 == 1:
                            dbg(f"heartbeat: {sent_count} writes, last duty {duty}")

                    data = ser.read(256)
                    if data:
                        last_recv = now
                        buf += data
                        while b"\n" in buf:
                            line, _, buf = buf.partition(b"\n")
                            s = line.decode("ascii", "ignore").strip()
                            if s.startswith("RPM"):
                                try:
                                    self.on_rpm(int(s.split()[1]))
                                except (IndexError, ValueError):
                                    pass
                            elif s == "BOOT":
                                log.info("Pico booted")
                                dbg("BOOT seen, marking dirty for resync")
                                with self._lock:
                                    self._duty_dirty = True
                            elif s.startswith("ERR"):
                                dbg(f"firmware: {s}")
                    elif now - last_recv > SILENCE_S:
                        reason = f"no firmware output for {SILENCE_S}s"
                        break
            except Exception as e:
                reason = f"{type(e).__name__}: {e}"
                dbg(f"loop exception: {reason}")

            # close and either retry or exit
            try:
                ser.close()
            except Exception:
                pass
            if self._stop.is_set():
                self.on_status("disconnected")
                dbg("worker exited")
                return
            self.on_status(f"reconnecting ({reason})")
            dbg(f"reconnecting: {reason}")
            if self._stop.wait(REOPEN_DELAY_S):
                return
