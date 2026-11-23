import math
import random
import unittest
from datetime import date, datetime, timedelta, timezone

from streamstudy.models import Sample, Series, WeatherDay
from streamstudy.thermal import (
    build_thermal_analysis,
    confidence_label,
    linear_fit,
    merge_weather,
    series_water_c,
)

START = date(2025, 1, 1)


def random_days(values):
    return {START + timedelta(days=index): value for index, value in enumerate(values)}


class LinearFitTest(unittest.TestCase):
    def test_recovers_slope_and_intercept(self):
        points = [(x, 2.0 + 0.75 * x) for x in range(-5, 6)]
        slope, intercept = linear_fit(points)
        self.assertAlmostEqual(slope, 0.75)
        self.assertAlmostEqual(intercept, 2.0)

    def test_needs_two_points(self):
        self.assertIsNone(linear_fit([(1.0, 2.0)]))
        self.assertIsNone(linear_fit([(1.0, 2.0), (1.0, 3.0)]))


class DriverFitTest(unittest.TestCase):
    def test_air_leads_water_by_one_day(self):
        rng = random.Random(7)
        air_values = [rng.uniform(-5.0, 25.0) for _ in range(31)]
        air = random_days(air_values)
        water = {
            START + timedelta(days=index + 1): 3.0 + 0.8 * air_values[index]
            for index in range(30)
        }
        analysis = build_thermal_analysis(water, air, {}, max_lag=5, min_pairs=5)
        self.assertIsNotNone(analysis.air.best)
        self.assertAlmostEqual(analysis.air.best.r, 1.0, places=6)
        self.assertEqual(analysis.air.best.lag_days, 1)
        self.assertEqual(analysis.air.best.n, 30)
        self.assertAlmostEqual(analysis.air.slope, 0.8, places=6)
        self.assertAlmostEqual(analysis.air.intercept, 3.0, places=6)
        self.assertEqual(analysis.air.confidence, "strong")
        self.assertTrue(analysis.air.points)
        self.assertIsNotNone(analysis.air.fit)
        self.assertIsNone(analysis.sun.best)

    def test_sunshine_tracks_water_at_zero_lag(self):
        rng = random.Random(11)
        sun_values = [rng.uniform(0.0, 12.0) for _ in range(25)]
        sun = random_days(sun_values)
        water = {
            START + timedelta(days=index): 9.0 + 0.9 * value
            for index, value in enumerate(sun_values)
        }
        analysis = build_thermal_analysis(water, {}, sun, max_lag=5, min_pairs=5)
        self.assertIsNotNone(analysis.sun.best)
        self.assertAlmostEqual(analysis.sun.best.r, 1.0, places=6)
        self.assertEqual(analysis.sun.best.lag_days, 0)
        # The full lag curve is available even away from the best lag.
        self.assertEqual(len(analysis.sun.by_lag), 11)

    def test_missing_water_is_reported(self):
        analysis = build_thermal_analysis({}, {START: 10.0}, {START: 4.0})
        self.assertEqual(analysis.water_days, 0)
        self.assertIsNone(analysis.air.best)
        self.assertIn("No daily water", analysis.error)


class ConfidenceTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(confidence_label(0.8, 40), "strong")
        self.assertEqual(confidence_label(0.5, 20), "moderate")
        self.assertEqual(confidence_label(0.2, 40), "weak")
        self.assertEqual(confidence_label(0.9, 4), "too few days")
        self.assertEqual(confidence_label(math.nan, 20), "too few days")


class SensorConversionTest(unittest.TestCase):
    def test_fahrenheit_converted_to_celsius(self):
        day = datetime(2025, 1, 2, 15, tzinfo=timezone.utc)
        series = Series(
            "temperature",
            "Water temperature",
            "\u00b0F",
            (Sample(day, 50.0), Sample(day + timedelta(hours=1), 68.0)),
            "Monitor My Watershed",
        )
        daily = series_water_c(series)
        self.assertAlmostEqual(daily[day.date()], 15.0, places=5)

    def test_recent_weather_overrides_archive(self):
        archive_air = {START: 1.0, START + timedelta(days=1): 2.0}
        archive_sun = {START: 3.0}
        weather = (
            WeatherDay(START + timedelta(days=1), mean_c=9.0, sunshine_hours=8.0),
        )
        air, sun = merge_weather(archive_air, archive_sun, weather)
        self.assertEqual(air[START + timedelta(days=1)], 9.0)
        self.assertEqual(sun[START + timedelta(days=1)], 8.0)
        self.assertEqual(air[START], 1.0)


if __name__ == "__main__":
    unittest.main()
