import unittest
from datetime import date, datetime, timedelta, timezone

from streamstudy.models import Sample, WeatherDay
from streamstudy.temperature_stats import (
    clear_days,
    hours_above,
    hours_above_daily,
    threshold_windows,
)


class HoursAboveTest(unittest.TestCase):
    def test_integrates_hours_above(self):
        start = datetime(2026, 11, 20, tzinfo=timezone.utc)
        samples = [
            Sample(start + timedelta(hours=index), 21.0 if index < 12 else 18.0)
            for index in range(25)
        ]
        hours = hours_above(samples, 20.0, start, start + timedelta(hours=24))
        self.assertAlmostEqual(hours, 11.0, places=1)

    def test_gap_is_capped(self):
        start = datetime(2026, 11, 20, tzinfo=timezone.utc)
        samples = [Sample(start, 22.0), Sample(start + timedelta(hours=10), 22.0)]
        self.assertAlmostEqual(
            hours_above(samples, 20.0, start, start + timedelta(hours=12)), 2.0
        )

    def test_daily_duration(self):
        daily = {
            date(2026, 11, 1) + timedelta(days=index): 25.0 if index % 2 == 0 else 15.0
            for index in range(10)
        }
        hours = hours_above_daily(
            daily, 20.0, date(2026, 11, 1), date(2026, 11, 10)
        )
        self.assertAlmostEqual(hours, 5 * 24.0)


class WindowsTest(unittest.TestCase):
    def test_windows_shape_and_percent(self):
        now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
        samples = [
            Sample(now - timedelta(hours=index), 21.0) for index in range(48)
        ]
        daily = {date(2026, 11, 1) + timedelta(days=index): 22.0 for index in range(60)}
        windows = threshold_windows(samples, daily, 20.0, now=now)
        labels = [window.label for window in windows]
        self.assertEqual(labels, ["24 h", "7 days", "30 days", "1 year"])
        self.assertAlmostEqual(windows[0].hours, 24.0, places=1)
        self.assertAlmostEqual(windows[0].percent, 100.0, places=1)
        for window in windows:
            self.assertLessEqual(window.hours, window.window_hours)
            self.assertGreaterEqual(window.percent, 0.0)


class ClearDaysTest(unittest.TestCase):
    def test_counts_recent_clear_days(self):
        today = date.today()
        weather = tuple(
            WeatherDay(day=today - timedelta(days=index), cloud_pct=cloud)
            for index, cloud in enumerate([10, 20, 30, 5, 80])
        )
        self.assertEqual(clear_days(weather, 3), 2)
        self.assertEqual(clear_days(weather, 14), 3)


if __name__ == "__main__":
    unittest.main()
