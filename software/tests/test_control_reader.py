import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fancontroller import control_reader


class ControlReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "control.json"
        self.path.write_text("{}", encoding="utf-8")
        self.path_patch = patch.object(control_reader, "CONTROL_PATH", self.path)
        self.path_patch.start()
        control_reader._cached_data = None
        control_reader._cached_mtime = None

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.directory.cleanup()

    def write(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        control_reader._cached_mtime = None

    def test_valid_temperature_override_is_combined_with_local_max(self) -> None:
        self.write({
            "temperature_override": {
                "temperature_c": 78.5,
                "source": "external-dashboard",
                "node_id": "node-3",
                "node_name": "gx10-node-3",
                "observed_at": 100.0,
                "expires_at": 120.0,
            },
        })

        control = control_reader.read_control(now=110.0)

        self.assertEqual(control.temperature_c, 78.5)
        self.assertEqual(control.node_name, "gx10-node-3")
        self.assertEqual(control_reader.effective_temperature(61.0, control), 78.5)
        self.assertEqual(control_reader.effective_temperature(82.0, control), 82.0)

    def test_expired_or_invalid_override_is_ignored(self) -> None:
        self.write({
            "temperature_override": {
                "temperature_c": 78.5,
                "expires_at": 109.0,
            },
        })
        self.assertIsNone(control_reader.read_control(now=110.0).temperature_c)

        self.write({
            "temperature_override": {
                "temperature_c": 500,
                "expires_at": 120.0,
            },
        })
        self.assertIsNone(control_reader.read_control(now=110.0).temperature_c)

    def test_max_speed_remains_independent(self) -> None:
        self.write({
            "max_speed": True,
            "temperature_override": {
                "temperature_c": 70.0,
                "expires_at": 120.0,
            },
        })
        control = control_reader.read_control(now=110.0)
        self.assertTrue(control.max_speed)
        self.assertEqual(control.temperature_c, 70.0)


if __name__ == "__main__":
    unittest.main()
