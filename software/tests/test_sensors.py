import tempfile
import unittest
from pathlib import Path

from fancontroller.sensors import CpuTempSource, TempSource, aggregate_max


class FakeSource(TempSource):
    def __init__(self, value: float | None) -> None:
        super().__init__("fake", "Fake")
        self.value = value

    def read(self) -> float | None:
        return self.value


class CpuTempSourceTests(unittest.TestCase):
    def test_discovers_cpu_hwmon_and_uses_hottest_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cpu = root / "hwmon0"
            cpu.mkdir()
            (cpu / "name").write_text("coretemp\n")
            (cpu / "temp1_input").write_text("61000\n")
            (cpu / "temp2_input").write_text("73500\n")

            source = CpuTempSource.discover(root)

            self.assertIsNotNone(source)
            self.assertEqual(source.read(), 73.5)

    def test_ignores_non_cpu_hwmon_devices_and_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nvme = root / "hwmon0"
            nvme.mkdir()
            (nvme / "name").write_text("nvme\n")
            (nvme / "temp1_input").write_text("45000\n")
            cpu = root / "hwmon1"
            cpu.mkdir()
            (cpu / "name").write_text("k10temp\n")
            (cpu / "temp1_input").write_text("not-a-temperature\n")

            self.assertIsNone(CpuTempSource.discover(root))

    def test_aggregate_max_uses_hottest_available_source(self) -> None:
        sources = [FakeSource(65.0), FakeSource(None), FakeSource(72.0)]
        self.assertEqual(aggregate_max(sources), 72.0)


if __name__ == "__main__":
    unittest.main()
