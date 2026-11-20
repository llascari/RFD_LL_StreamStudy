import unittest
from datetime import date, datetime, timedelta, timezone

from streamstudy.analysis import (
    bundle_precip_sources,
    format_value,
    mm_to_inches,
    nice_step,
    precip_table,
    recent_days,
    series_stats,
    sum_by_day,
    totals_for_window,
    trend_per_hour,
)
from streamstudy.models import DataBundle, Sample, Series, Site

BASE = datetime(2026, 11, 20, 0, tzinfo=timezone.utc)


def make_series(values, code="00060", units="u", step_hours=1):
    samples = tuple(
        Sample(BASE + timedelta(hours=index * step_hours), value)
        for index, value in enumerate(values)
    )
    return Series(code, "test", units, samples, "test")


class StatsTest(unittest.TestCase):
    def test_series_stats_even_and_odd(self):
        stats = series_stats(make_series([1, 2, 3, 4]))
        self.assertEqual(stats.count, 4)
        self.assertEqual(stats.minimum, 1)
        self.assertEqual(stats.maximum, 4)
        self.assertEqual(stats.median, 2.5)
        self.assertEqual(stats.latest, 4)
        self.assertEqual(stats.mean, 2.5)

        odd = series_stats(make_series([10, 1, 4]))
        self.assertEqual(odd.median, 4)

    def test_stats_ignores_missing_values(self):
        series = Series("x", "x", "u", (Sample(BASE, None), Sample(BASE, 5.0)), "t")
        stats = series_stats(series)
        self.assertEqual(stats.count, 1)
        self.assertEqual(stats.latest, 5.0)

    def test_trend(self):
        rising = make_series([0, 1, 2, 3, 4, 5, 6])
        self.assertAlmostEqual(trend_per_hour(rising, hours=6), 1.0)
        flat = make_series([2, 2, 2])
        self.assertEqual(trend_per_hour(flat), 0.0)
        self.assertIsNone(trend_per_hour(make_series([1])))


class DailyTotalsTest(unittest.TestCase):
    def test_sum_by_day_splits_at_midnight(self):
        samples = [
            Sample(datetime(2026, 11, 19, 23, 0, tzinfo=timezone.utc), 0.2),
            Sample(datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc), 0.3),
            Sample(datetime(2026, 11, 20, 2, 0, tzinfo=timezone.utc), None),
        ]
        totals = sum_by_day(samples, timezone.utc)
        self.assertAlmostEqual(totals[date(2026, 11, 19)], 0.2)
        self.assertAlmostEqual(totals[date(2026, 11, 20)], 0.3)

    def test_recent_days_and_window_totals(self):
        days = recent_days(3, end=date(2026, 11, 20))
        self.assertEqual(days, [date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20)])
        daily = {date(2026, 11, 19): 0.5, date(2026, 11, 20): 0.25}
        self.assertAlmostEqual(totals_for_window(daily, 2, end=date(2026, 11, 20)), 0.75)

    def test_precip_table_shape(self):
        sources = {"a": {date(2026, 11, 20): 0.4}}
        rows = precip_table(sources, 2, end=date(2026, 11, 20))
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0][1]["a"])
        self.assertAlmostEqual(rows[1][1]["a"], 0.4)


class ConversionTest(unittest.TestCase):
    def test_mm_to_inches(self):
        self.assertAlmostEqual(mm_to_inches(25.4), 1.0)
        self.assertAlmostEqual(mm_to_inches(3.7), 0.1457, places=3)

    def test_format_value(self):
        self.assertEqual(format_value(None), "\u2014")
        self.assertEqual(format_value(1234.5), "1,234")
        self.assertEqual(format_value(12.34), "12.34")
        self.assertEqual(format_value(1.234), "1.23")

    def test_nice_step(self):
        self.assertEqual(nice_step(10), 2.0)
        self.assertEqual(nice_step(9.5), 2.0)
        self.assertEqual(nice_step(0), 1.0)


class BundlePrecipTest(unittest.TestCase):
    def test_sources_and_conversions(self):
        site = Site("0423205010", "Irondequoit", 43.14, -77.51)

        def precip_series(values):
            return Series(
                "00045",
                "Precipitation",
                "in",
                tuple(Sample(BASE + timedelta(hours=i), v) for i, v in enumerate(values)),
                "USGS NWIS",
            )

        bundle = DataBundle(
            site=site,
            usgs={"00045": precip_series([0.1, 0.2])},
            coco_daily=((date(2026, 11, 20), 0.45),),
            openmeteo_daily=((date(2026, 11, 20), 25.4),),
        )
        sources = bundle_precip_sources(bundle, timezone.utc)
        self.assertEqual(set(sources), {"usgs", "cocorahs", "openmeteo"})
        self.assertAlmostEqual(sources["usgs"][date(2026, 11, 20)], 0.3)
        self.assertAlmostEqual(sources["cocorahs"][date(2026, 11, 20)], 0.45)
        self.assertAlmostEqual(sources["openmeteo"][date(2026, 11, 20)], 1.0)


if __name__ == "__main__":
    unittest.main()
