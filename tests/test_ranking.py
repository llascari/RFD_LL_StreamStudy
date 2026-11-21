import unittest
from datetime import date, timedelta

from streamstudy.models import ResponseFit, Site
from streamstudy.ranking import build_ranking

START = date(2025, 1, 1)


def flow(offset: float = 0.0) -> dict:
    return {
        START + timedelta(days=index): 50.0 + offset + (index % 9)
        for index in range(120)
    }


def fit(r_squared: float, events: int) -> ResponseFit:
    return ResponseFit(
        events=events,
        slope=120.0,
        ratio_p10=60.0,
        ratio_p50=120.0,
        ratio_p90=200.0,
        r_squared=r_squared,
        lag_p50_hours=18.0,
        lag_p10_hours=8.0,
        lag_p90_hours=30.0,
        half_life_days=1.5,
        confidence="moderate",
    )


class RankingTest(unittest.TestCase):
    def setUp(self):
        self.base = Site("0423205010", "Base", 43.1448, -77.5120)
        self.sites = (
            Site("04232050", "Near strong", 43.10, -77.60),
            Site("04232060", "Far strong", 43.40, -78.00),
            Site("04232070", "Near weak", 43.13, -77.50),
        )

    def test_orders_by_usefulness(self):
        flows = {site.number: flow(index) for index, site in enumerate(self.sites)}
        temps = {"04232050": flow()}
        fits = {
            "04232050": fit(0.6, 120),
            "04232060": fit(0.55, 100),
            "04232070": fit(0.05, 8),
        }
        ranking = build_ranking(self.sites, flows, temps, fits, self.base)
        self.assertEqual(len(ranking.scores), 3)
        self.assertEqual(ranking.scores[0].site.number, "04232050")
        self.assertEqual(ranking.scores[-1].site.number, "04232070")
        self.assertTrue(ranking.scores[0].has_temperature)
        self.assertIsNotNone(ranking.hub)
        self.assertLessEqual(ranking.hub.score, ranking.scores[0].score)
        self.assertIn("storms", ranking.scores[0].reasons)

    def test_missing_flow_is_skipped(self):
        flows = {"04232050": flow()}
        ranking = build_ranking(self.sites, flows, {}, {}, self.base)
        self.assertEqual(len(ranking.scores), 1)
        self.assertEqual(ranking.hub.site.number, "04232050")


if __name__ == "__main__":
    unittest.main()
