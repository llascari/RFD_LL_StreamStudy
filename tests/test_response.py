import math
import unittest
from datetime import date, datetime, timedelta, timezone

from streamstudy.response import (
    Scenario,
    analyse_history,
    baseflow,
    detect_events,
    fit_response,
    forecast_scenario,
    percentile,
    predict,
    scale_scenario,
)

START = date(2025, 1, 1)


def synthetic_history(ratio: float = 150.0, half_life: float = 1.5):
    """Five one-day storms on a 50 cfs base with an exponential recession."""
    storms = {10: 0.6, 30: 0.4, 50: 0.8, 70: 0.5, 90: 1.0}
    days = [START + timedelta(days=offset) for offset in range(140)]
    precip = {day: storms.get(offset, 0.0) for offset, day in enumerate(days)}
    flow = {}
    for offset, day in enumerate(days):
        value = 50.0
        for storm_day, rain in storms.items():
            if offset > storm_day:
                elapsed = offset - storm_day
                value += ratio * rain * math.exp(-(elapsed - 1) * math.log(2) / half_life)
        flow[day] = value
    return flow, precip


class PercentileTest(unittest.TestCase):
    def test_interpolates(self):
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(percentile([5], 0.9), 5)
        self.assertTrue(math.isnan(percentile([], 0.5)))


class BaseflowTest(unittest.TestCase):
    def test_never_exceeds_flow(self):
        flow = {START + timedelta(days=i): 100.0 - i for i in range(20)}
        base = baseflow(flow)
        for day, value in flow.items():
            self.assertLessEqual(base[day], value)


class EventDetectionTest(unittest.TestCase):
    def setUp(self):
        self.flow, self.precip = synthetic_history()
        self.events = detect_events(self.flow, self.precip)

    def test_finds_each_storm(self):
        self.assertEqual(len(self.events), 5)
        self.assertEqual([event.rain_in for event in self.events], [0.6, 0.4, 0.8, 0.5, 1.0])

    def test_rise_and_lag(self):
        biggest = max(self.events, key=lambda event: event.rain_in)
        self.assertAlmostEqual(biggest.rise_cfs, 150.0, delta=2.0)
        self.assertAlmostEqual(biggest.lag_hours, 24.0, delta=1.0)
        self.assertGreater(biggest.half_life_days, 0)

    def test_ignores_drizzle(self):
        flow, precip = synthetic_history()
        precip[START + timedelta(days=5)] = 0.03
        self.assertEqual(len(detect_events(flow, precip)), 5)

    def test_needs_paired_history(self):
        self.assertEqual(detect_events({}, {}), [])


class FitTest(unittest.TestCase):
    def setUp(self):
        self.flow, self.precip = synthetic_history()
        self.events, self.fit = analyse_history(self.flow, self.precip)

    def test_slope_recovers_known_response(self):
        self.assertIsNotNone(self.fit)
        self.assertAlmostEqual(self.fit.slope, 150.0, delta=5.0)
        self.assertAlmostEqual(self.fit.ratio_p50, 150.0, delta=5.0)
        self.assertGreaterEqual(self.fit.ratio_p10, 0)
        self.assertGreaterEqual(self.fit.ratio_p90, self.fit.ratio_p50)
        self.assertAlmostEqual(self.fit.lag_p50_hours, 24.0, delta=1.0)
        self.assertGreater(self.fit.half_life_days, 0.5)

    def test_small_samples_have_no_fit(self):
        self.assertIsNone(fit_response(self.events[:2]))


class ScenarioTest(unittest.TestCase):
    def test_scale_preserves_timing(self):
        now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
        base = Scenario(((now, 0.2), (now + timedelta(hours=6), 0.3)), 0.5)
        scaled = scale_scenario(base, 1.0)
        self.assertAlmostEqual(scaled.total_in, 1.0)
        self.assertAlmostEqual(scaled.increments[0][1], 0.4)
        self.assertAlmostEqual(scaled.increments[1][1], 0.6)

    def test_centroid_weights_rain(self):
        now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
        scenario = Scenario(((now, 1.0), (now + timedelta(hours=10), 1.0)), 2.0)
        self.assertAlmostEqual(
            scenario.centroid().timestamp(), (now + timedelta(hours=5)).timestamp(), delta=1
        )


class PredictionTest(unittest.TestCase):
    def test_prediction_matches_ratio_and_lag(self):
        flow, precip = synthetic_history()
        events, fit = analyse_history(flow, precip)
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        scenario = Scenario(((now, 1.0),), 1.0)
        prediction = predict(
            scenario, fit, tuple(events), current_cfs=50.0, baseflow_cfs=50.0, now=now
        )
        self.assertIsNotNone(prediction)
        self.assertAlmostEqual(prediction.peak_cfs, 200.0, delta=8.0)
        self.assertLessEqual(prediction.low_peak_cfs, prediction.peak_cfs)
        self.assertGreaterEqual(prediction.high_peak_cfs, prediction.peak_cfs)
        hours = (prediction.peak_time - now).total_seconds() / 3600
        self.assertAlmostEqual(hours, 24.0, delta=1.5)
        self.assertAlmostEqual(prediction.curve[0][1], 50.0, delta=0.5)
        self.assertAlmostEqual(prediction.curve[-1][1], 50.0, delta=3.0)
        self.assertGreater(len(prediction.curve), 10)
        self.assertGreater(prediction.rise_pct_base, 0)
        self.assertGreater(prediction.rise_pct_peak, 0)
        self.assertGreaterEqual(prediction.decay_24h_pct, 0)
        self.assertLessEqual(prediction.decay_24h_pct, 100)

    def test_no_rain_means_no_prediction(self):
        flow, precip = synthetic_history()
        events, fit = analyse_history(flow, precip)
        self.assertIsNone(
            predict(Scenario((), 0.0), fit, tuple(events), current_cfs=50, baseflow_cfs=50)
        )

    def test_similar_storms(self):
        flow, precip = synthetic_history()
        events, fit = analyse_history(flow, precip)
        now = datetime.now(timezone.utc)
        prediction = predict(
            Scenario(((now, 0.82),), 0.82),
            fit,
            tuple(events),
            current_cfs=50,
            baseflow_cfs=50,
            now=now,
        )
        self.assertIsNotNone(prediction)
        self.assertIn(0.8, [round(event.rain_in, 2) for event in prediction.similar])

    def test_forecast_scenario_prefers_qpf(self):
        from streamstudy.models import DataBundle, Site

        now = datetime.now(timezone.utc)
        site = Site("0423205010", "Irondequoit", 43.14, -77.51)
        bundle = DataBundle(
            site=site,
            nws_qpf=((now + timedelta(hours=3), 0.4), (now + timedelta(hours=9), 0.1)),
            openmeteo_hourly=((now + timedelta(hours=1), 12.7, 80),),
        )
        scenario, source = forecast_scenario(bundle, now=now)
        self.assertEqual(source, "NWS QPF")
        self.assertAlmostEqual(scenario.total_in, 0.5)

        bundle.nws_qpf = ()
        scenario, source = forecast_scenario(bundle, now=now)
        self.assertEqual(source, "Open-Meteo")
        self.assertAlmostEqual(scenario.total_in, 0.5)


if __name__ == "__main__":
    unittest.main()
