import unittest
from datetime import date, datetime, timedelta, timezone

from streamstudy.models import Sample, WeatherDay
from streamstudy.temperature_stats import (
    clear_days,
    hours_above,
    hours_above_daily,
    summarize_window,
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


class WindowSummaryTest(unittest.TestCase):
    def test_daily_window(self):
        start = date(2026, 11, 1)
        daily = {
            start + timedelta(days=index): 25.0 if index % 2 == 0 else 15.0
            for index in range(10)
        }
        summary = summarize_window(
            [], daily, 20.0, start, start + timedelta(days=9)
        )
        self.assertAlmostEqual(summary.hours, 5 * 24.0)
        self.assertAlmostEqual(summary.percent, 50.0, places=1)
        self.assertEqual(summary.days_above, 5)
        self.assertAlmostEqual(summary.mean_c, 20.0)
        self.assertEqual(summary.max_c, 25.0)
        self.assertIn("daily means", summary.source)

    def test_short_window_uses_samples(self):
        start = datetime(2026, 11, 20, tzinfo=timezone.utc)
        samples = [Sample(start + timedelta(hours=i), 21.0) for i in range(48)]
        summary = summarize_window(
            samples, {}, 20.0, date(2026, 11, 20), date(2026, 11, 20)
        )
        self.assertGreater(summary.hours, 0)
        self.assertLessEqual(summary.percent, 100.0)
        self.assertIn("samples", summary.source)


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
