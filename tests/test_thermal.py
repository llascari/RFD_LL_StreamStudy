import math
import random
import unittest
from datetime import date, datetime, timedelta, timezone

from streamstudy.models import Sample, Series, WeatherDay
from streamstudy.thermal import (
    anomalies,
    build_thermal_analysis,
    confidence_label,
    joint_anomaly_fit,
    linear_fit,
    merge_weather,
    partial_pearson,
    rolling_nominal,
    series_water_c,
    sunlight_peers,
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


class RollingNominalTest(unittest.TestCase):
    def test_constant_series_maps_to_itself(self):
        values = random_days([5.0] * 30)
        nominal = rolling_nominal(values)
        self.assertEqual(len(nominal), 30)
        for value in anomalies(values, nominal).values():
            self.assertAlmostEqual(value, 0.0, places=9)

    def test_spike_survives_as_anomaly(self):
        values = random_days([0.0] * 29 + [10.0])
        anom = anomalies(values, rolling_nominal(values))
        self.assertGreater(abs(anom[START + timedelta(days=29)]), 8.0)

    def test_short_series_has_no_nominal(self):
        self.assertEqual(rolling_nominal(random_days([1.0, 2.0, 3.0])), {})


class AnomalyFitTest(unittest.TestCase):
    def test_anomaly_fit_recovers_coupling_hidden_by_the_seasons(self):
        # Water follows its own (phase-shifted) seasonal cycle plus 0.8 of
        # yesterday's AIR ANOMALY. The absolute fit is dominated by the
        # seasons; the anomaly fit should recover the coupling.
        rng = random.Random(3)
        noise = [rng.uniform(-6.0, 6.0) for _ in range(120)]
        air = {}
        water = {}
        for index in range(120):
            day = START + timedelta(days=index)
            air[day] = 12.0 + 9.0 * math.sin(2 * math.pi * index / 120) + noise[index]
            if index:
                water[day] = (
                    9.0
                    - 5.0 * math.sin(2 * math.pi * index / 120)
                    + 0.8 * noise[index - 1]
                )
        analysis = build_thermal_analysis(water, air, {}, max_lag=5, min_pairs=5)
        self.assertIsNotNone(analysis.air_anomaly)
        fit = analysis.air_anomaly
        self.assertIsNotNone(fit.best)
        self.assertEqual(fit.best.lag_days, 1)
        self.assertGreater(fit.best.r, 0.95)
        self.assertGreater(fit.slope, 0.75)
        self.assertLess(fit.slope, 0.85)
        # The anomaly view must beat the absolute view at this game.
        self.assertGreater(fit.best.r, analysis.air.best.r)
        self.assertGreater(analysis.anomaly_days, 90)

    def test_sun_anomaly_slope_is_exact_for_linear_water(self):
        sun_values = [6.0 + 4.0 * math.sin(2 * math.pi * i / 90) + (i % 7) - 3 for i in range(90)]
        sun = random_days(sun_values)
        water = {day: 5.0 + 2.0 * value for day, value in sun.items()}
        analysis = build_thermal_analysis(water, {}, sun, max_lag=5, min_pairs=5)
        fit = analysis.sun_anomaly
        self.assertIsNotNone(fit)
        self.assertIsNotNone(fit.best)
        self.assertAlmostEqual(fit.slope, 2.0, places=6)
        self.assertAlmostEqual(fit.best.r, 1.0, places=6)


class SunlightPeersTest(unittest.TestCase):
    def test_peers_ranked_by_partial_sunlight_slope(self):
        sun_values = [5.0 + ((index * 7) % 11) * 0.8 for index in range(40)]
        air_values = [12.0 + ((index * 5) % 13) * 0.7 for index in range(40)]
        sun = random_days(sun_values)
        air = random_days(air_values)
        base_water = {day: 2.0 * value for day, value in sun.items()}
        flat_water = random_days([8.0] * 40)
        rows = sunlight_peers(
            "A",
            "BASE CREEK",
            base_water,
            air,
            sun,
            [("B", "FLAT CREEK", 3.0, flat_water, air, sun, "")],
        )
        self.assertEqual(rows[0].site_number, "A")
        self.assertTrue(rows[0].this_site)
        # Water is exactly 2x sunshine, so the held-constant sun slope is exact.
        self.assertAlmostEqual(rows[0].slope_c_per_hour, 2.0, places=6)
        self.assertAlmostEqual(rows[0].sun_r, 1.0, places=6)
        self.assertEqual(rows[1].site_number, "B")
        # A flat creek has no anomaly signal, so it gets no slope.
        self.assertIsNone(rows[1].slope_c_per_hour)

    def test_peer_errors_keep_their_slot(self):
        rows = sunlight_peers(
            "A", "BASE", {}, {}, {}, [("B", "X", 2.0, {}, {}, {}, "boom")]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].error, "boom")
        self.assertEqual(rows[0].this_site, True)

    def test_gage_without_water_temperature_is_explained(self):
        sun = random_days([5.0 + (index % 9) for index in range(40)])
        air = random_days([12.0 + (index % 7) for index in range(40)])
        rows = sunlight_peers(
            "A", "BASE", {day: 10.0 + v * 0.1 for day, v in sun.items()}, air, sun,
            [("B", "DRY GAGE", 40.0, {}, air, sun, "")],
        )
        self.assertEqual(rows[1].error, "no water temperature in window")
        self.assertIsNone(rows[1].slope_c_per_hour)


class PartialPearsonTest(unittest.TestCase):
    def test_formula(self):
        # (0.6 - 0.5*0.6) / sqrt((1-0.25)*(1-0.36))
        self.assertAlmostEqual(partial_pearson(0.6, 0.5, 0.6), 0.3 / math.sqrt(0.75 * 0.64))

    def test_degenerate_inputs_return_none(self):
        self.assertIsNone(partial_pearson(0.9, 1.0, 0.5))


class JointAnomalyFitTest(unittest.TestCase):
    def test_recovers_both_slopes_and_lags(self):
        # Water = 5 + 2.0*sun (lag 0) + 0.5*air (lag 1); drivers independent.
        # The rolling normal is linear, so the anomaly fit recovers exactly.
        sun_values = [6.0 + ((index * 7) % 11) * 0.9 for index in range(60)]
        air_values = [12.0 + ((index * 5) % 13) * 0.8 for index in range(60)]
        sun = random_days(sun_values)
        air = random_days(air_values)
        water = {}
        for day, value in air.items():
            target = day + timedelta(days=1)
            sunshine = sun.get(target)
            if sunshine is None:
                continue
            water[target] = 5.0 + 0.5 * value + 2.0 * sunshine
        joint = joint_anomaly_fit(water, air, sun, max_lag=5, min_pairs=5)
        self.assertIsNotNone(joint)
        # Near-exact: the rolling normal is linear, but each series' window is
        # clipped at its own edges, so edge days contribute small residuals.
        self.assertAlmostEqual(joint.air_slope, 0.5, delta=0.02)
        self.assertAlmostEqual(joint.sun_slope, 2.0, delta=0.02)
        self.assertAlmostEqual(joint.air_partial_r, 1.0, delta=0.03)
        self.assertAlmostEqual(joint.sun_partial_r, 1.0, delta=0.03)
        self.assertAlmostEqual(joint.r_squared, 1.0, delta=0.03)
        self.assertEqual(joint.air_lag, 1)
        self.assertEqual(joint.sun_lag, 0)

    def test_partial_removes_the_sun_air_confound(self):
        # Water follows AIR only; air strongly tracks sunshine. The univariate
        # sun fit looks convincing, but with air held constant sun adds nothing.
        rng = random.Random(9)
        sun_values = [6.0 + rng.uniform(-3.0, 3.0) for _ in range(90)]
        sun = random_days(sun_values)
        air = {
            day: 12.0 + 0.9 * (value - 6.0) + rng.uniform(-0.5, 0.5)
            for day, value in sun.items()
        }
        water = {
            day: 5.0 + 1.0 * (value - 12.0) + rng.uniform(-0.4, 0.4)
            for day, value in air.items()
        }
        analysis = build_thermal_analysis(water, air, sun, max_lag=5, min_pairs=5)
        joint = joint_anomaly_fit(water, air, sun, max_lag=5, min_pairs=5)
        self.assertIsNotNone(joint)
        self.assertIsNotNone(analysis.sun_anomaly.best)
        univariate_sun_r = abs(analysis.sun_anomaly.best.r)
        self.assertGreater(univariate_sun_r, 0.8)
        self.assertLess(abs(joint.sun_partial_r), 0.3)
        self.assertGreater(abs(joint.air_partial_r), 0.8)

    def test_collinear_or_missing_inputs_return_none(self):
        days = random_days([5.0] * 40)
        # Flat sunshine: anomalies vanish, nothing to regress.
        self.assertIsNone(joint_anomaly_fit(days, days, days))
        self.assertIsNone(joint_anomaly_fit({}, days, days))


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
