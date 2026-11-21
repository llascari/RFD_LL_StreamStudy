import math
import unittest
from datetime import date, timedelta

from streamstudy.correlation import build_regional, lagged_correlation
from streamstudy.models import Site

START = date(2025, 1, 1)


def wave(days: int = 240, phase: float = 0.0) -> dict[date, float]:
    return {
        START + timedelta(days=index): 50.0
        + 20.0 * math.sin((index + phase) / 5.0)
        + (index % 7) * 0.5
        for index in range(days)
    }


class LagTest(unittest.TestCase):
    def test_finds_positive_lag(self):
        base = wave()
        delayed = {
            day + timedelta(days=2): value for day, value in base.items()
        }
        result = lagged_correlation(base, delayed, max_lag=5)
        self.assertIsNotNone(result)
        self.assertEqual(result.lag_days, 2)
        self.assertGreater(result.r, 0.99)
        self.assertGreater(result.n, 200)

    def test_finds_negative_lag(self):
        base = wave()
        earlier = {day - timedelta(days=3): value for day, value in base.items()}
        result = lagged_correlation(base, earlier, max_lag=5)
        self.assertEqual(result.lag_days, -3)
        self.assertGreater(result.r, 0.99)

    def test_short_overlap_is_rejected(self):
        small = {START + timedelta(days=i): 1.0 for i in range(10)}
        self.assertIsNone(lagged_correlation(small, small, min_pairs=30))

    def test_flat_series_scores_zero(self):
        flat = {START + timedelta(days=i): 5.0 for i in range(60)}
        result = lagged_correlation(flat, wave(), max_lag=2)
        self.assertIsNotNone(result)
        self.assertEqual(result.r, 0.0)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.sites = (
            Site("0423205010", "Irondequoit", 43.14, -77.51),
            Site("04232050", "Allen Creek", 43.10, -77.60),
            Site("04232060", "Red Creek", 43.25, -77.40),
        )
        self.flow_a = wave(phase=0.0)
        self.flow_b = wave(phase=15.0)  # ~3-day phase shift
        self.rain = {
            START + timedelta(days=index): max(0.0, 0.5 + 0.5 * math.sin(index / 9.0))
            for index in range(240)
        }
        self.flows = {
            "0423205010": self.flow_a,
            "04232050": self.flow_b,
            "04232060": dict(self.flow_a),
        }

    def test_pairs_and_rain(self):
        analysis = build_regional(
            self.sites,
            self.flows,
            {"ERA5": self.rain},
            start=START,
            end=START + timedelta(days=239),
        )
        self.assertEqual(len(analysis.flow_pairs), 3)
        identical = analysis.flow_pairs[("0423205010", "04232060")]
        self.assertAlmostEqual(identical.r, 1.0, places=3)
        self.assertEqual(identical.lag_days, 0)

        self.assertIn(("0423205010", "ERA5"), analysis.rain_pairs)
        rain_corr = analysis.rain_pairs[("0423205010", "ERA5")]
        self.assertLessEqual(abs(rain_corr.r), 1.0)
        self.assertLessEqual(abs(rain_corr.lag_days), 5)

        strongest = analysis.strongest_pairs(2)
        self.assertEqual(len(strongest), 2)
        self.assertGreaterEqual(abs(strongest[0][2].r), abs(strongest[1][2].r))

    def test_missing_flow_is_skipped(self):
        flows = {"0423205010": self.flow_a}
        analysis = build_regional(
            self.sites, flows, {}, start=START, end=START + timedelta(days=239)
        )
        self.assertEqual(analysis.flow_pairs, {})
        self.assertEqual(analysis.rain_pairs, {})
        self.assertEqual(analysis.short_label("0423205010"), "0423205010")


if __name__ == "__main__":
    unittest.main()
