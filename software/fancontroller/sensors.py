"""Temperature sources for the fan controllers."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class TempSource:
    def __init__(self, key: str, label: str) -> None:
        self.key = key
        self.label = label

    def read(self) -> Optional[float]:
        raise NotImplementedError


class CpuTempSource(TempSource):
    """Read the hottest CPU/package temperature exposed by Linux hwmon."""

    # Names used by the common x86, ARM, and firmware-backed CPU sensors.
    # acpitz is included because some ARM systems expose their SoC/CPU thermal
    # zones only through ACPI rather than a CPU-specific hwmon driver.
    HWMON_NAMES = {
        "acpitz",
        "coretemp",
        "cpu_thermal",
        "cpu-thermal",
        "k10temp",
        "soc_thermal",
        "soc-thermal",
        "zenpower",
    }

    def __init__(self, inputs: list[Path]) -> None:
        super().__init__("cpu", "CPU (Linux hwmon)")
        self.inputs = inputs

    @classmethod
    def discover(
        cls, hwmon_root: Path = Path("/sys/class/hwmon")
    ) -> Optional["CpuTempSource"]:
        inputs: list[Path] = []
        try:
            devices = sorted(hwmon_root.glob("hwmon*"))
        except OSError:
            return None
        for device in devices:
            try:
                name = (device / "name").read_text().strip().lower()
            except OSError:
                continue
            if name not in cls.HWMON_NAMES:
                continue
            inputs.extend(sorted(device.glob("temp*_input")))
        source = cls(inputs)
        return source if source.read() is not None else None

    def read(self) -> Optional[float]:
        temps: list[float] = []
        for path in self.inputs:
            try:
                # The hwmon ABI reports temperatures in millidegrees Celsius.
                value = float(path.read_text().strip()) / 1000.0
            except (OSError, ValueError):
                continue
            # Ignore disconnected/broken sensor values while retaining a wide
            # enough range for valid readings during startup and shutdown.
            if -20.0 <= value <= 150.0:
                temps.append(value)
        return max(temps) if temps else None


class NvidiaSmiSource(TempSource):
    def __init__(self) -> None:
        super().__init__("gpu", "GPU (nvidia-smi)")

    def read(self) -> Optional[float]:
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return None
        if out.returncode != 0:
            return None
        temps: list[float] = []
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                temps.append(float(line))
            except ValueError:
                log.warning("ignoring non-numeric nvidia-smi output: %r", line)
        return max(temps) if temps else None


def discover() -> list[TempSource]:
    """Discover available temperature sources.

    CPU is listed first so it is preferred when a configuration has no valid
    selected source. Returns an empty list if no sources are available.
    """
    sources: list[TempSource] = []
    cpu = CpuTempSource.discover()
    if cpu is not None:
        sources.append(cpu)
    nv = NvidiaSmiSource()
    if nv.read() is not None:
        sources.append(nv)
    return sources


def aggregate_max(sources: list[TempSource]) -> Optional[float]:
    vals = [v for v in (s.read() for s in sources) if v is not None]
    return max(vals) if vals else None
