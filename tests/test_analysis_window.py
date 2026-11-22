import unittest
from datetime import date

from streamstudy.analysis_window import (
    key_for_window,
    parse_custom,
    preset_window,
    window_from_settings,
    window_to_settings,
)

TODAY = date(2026, 11, 22)


class PresetTest(unittest.TestCase):
    def test_last_30_days(self):
        window = preset_window("30d", today=TODAY)
        self.assertEqual(window.end, TODAY)
        self.assertEqual(window.days, 30)
        self.assertEqual(window.start, date(2026, 10, 24))
        self.assertEqual(window.label, "Last 30 days")
        self.assertEqual(key_for_window(window, today=TODAY), "30d")

    def test_one_day(self):
        window = preset_window("1d", today=TODAY)
        self.assertEqual(window.days, 1)
        self.assertEqual(window.hours, 24.0)

    def test_unknown_preset_falls_back_to_one_year(self):
        self.assertEqual(preset_window("nope", today=TODAY).days, 365)


class CustomTest(unittest.TestCase):
    def test_parse_dates(self):
        window = parse_custom("2025-01-01", "2025-03-01", today=TODAY)
        self.assertEqual(window.start, date(2025, 1, 1))
        self.assertEqual(window.end, date(2025, 3, 1))
        self.assertEqual(window.days, 60)

    def test_future_end_is_clamped(self):
        window = parse_custom("2026-01-01", "2027-01-01", today=TODAY)
        self.assertEqual(window.end, TODAY)

    def test_reversed_and_invalid_dates(self):
        with self.assertRaises(ValueError):
            parse_custom("2026-02-01", "2026-01-01", today=TODAY)
        with self.assertRaises(ValueError):
            parse_custom("01/02/2026", "2026-01-03", today=TODAY)


class SettingsRoundtripTest(unittest.TestCase):
    def test_preset_roundtrip(self):
        window = preset_window("90d", today=TODAY)
        self.assertEqual(window_to_settings(window, today=TODAY), {"mode": "90d"})
        restored = window_from_settings({"mode": "90d"}, today=TODAY)
        self.assertEqual((restored.start, restored.end), (window.start, window.end))

    def test_custom_roundtrip(self):
        window = parse_custom("2025-05-01", "2025-08-15", today=TODAY)
        data = window_to_settings(window, today=TODAY)
        self.assertEqual(data["mode"], "custom")
        restored = window_from_settings(data, today=TODAY)
        self.assertEqual((restored.start, restored.end), (window.start, window.end))

    def test_invalid_settings_fall_back(self):
        self.assertEqual(window_from_settings({"mode": "bogus"}, today=TODAY).days, 365)
        self.assertEqual(
            window_from_settings(
                {"mode": "custom", "start": "x", "end": "y"}, today=TODAY
            ).days,
            365,
        )


if __name__ == "__main__":
    unittest.main()
