import unittest

from fancontroller.settings import Settings


class ActiveSettingsTests(unittest.TestCase):
    def test_curve_contains_only_curve_settings(self) -> None:
        settings = Settings(mode="curve")

        self.assertEqual(
            settings.active_settings(),
            {
                "curve_points": [
                    [40.0, 0.0],
                    [60.0, 30.0],
                    [75.0, 60.0],
                    [90.0, 100.0],
                ],
                "curve_min_temp": 30.0,
                "curve_max_temp": 100.0,
                "min_floor_pct": 0.0,
            },
        )

    def test_pid_contains_only_pid_settings(self) -> None:
        settings = Settings(mode="pid")

        self.assertEqual(
            settings.active_settings(),
            {
                "setpoint": 65.0,
                "kp": 4.0,
                "ki": 0.2,
                "kd": 1.0,
                "min_floor_pct": 0.0,
            },
        )

    def test_other_modes_contain_only_their_settings(self) -> None:
        self.assertEqual(
            Settings(mode="hysteresis").active_settings(),
            {"hyst_on_temp": 75.0, "hyst_off_temp": 65.0},
        )
        self.assertEqual(
            Settings(mode="manual").active_settings(),
            {"manual_duty_pct": 100.0},
        )


if __name__ == "__main__":
    unittest.main()
