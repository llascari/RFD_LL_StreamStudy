import unittest
from datetime import date

from streamstudy.providers.cocorahs import (
    CoCoRaHSProvider,
    parse_amount,
    parse_nearest,
    parse_station_history,
)
from tests.support import StaticClient, fixture


class ParsingTest(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(parse_amount("0.45"), 0.45)
        self.assertEqual(parse_amount(" 0.00 "), 0.0)
        self.assertEqual(parse_amount("T"), 0.0)  # trace
        self.assertIsNone(parse_amount("NA"))
        self.assertIsNone(parse_amount(""))

    def test_station_history(self):
        history = parse_station_history(fixture("cocorahs_station.csv"))
        self.assertEqual(len(history), 10)
        self.assertEqual([day for day, _ in history], sorted(day for day, _ in history))
        values = dict(history)
        for day in (date(2026, 11, 15), date(2026, 11, 13), date(2026, 11, 12)):
            self.assertIn(day, values)
            self.assertGreaterEqual(values[day], 0.0)
            self.assertLess(values[day], 5.0)

    def test_nearest_station(self):
        nearest = parse_nearest(fixture("cocorahs_station.csv"), 43.144833, -77.511972)
        self.assertEqual(len(nearest), 1)
        station = nearest[0]
        self.assertEqual(station.identifier, "NY-MR-90")
        self.assertLess(station.distance_km, 10.0)
        self.assertEqual(station.network, "CoCoRaHS")


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.client = StaticClient()
        self.provider = CoCoRaHSProvider(self.client)

    def test_history_request(self):
        history = self.provider.daily_history("NY-MR-90", days=10)
        self.assertEqual(len(history), 10)
        _url, params = self.client.calls[-1]
        self.assertEqual(params["Station"], "NY-MR-90")
        self.assertEqual(params["State"], "NY")
        self.assertEqual(params["Format"], "CSV")
        self.assertEqual(params["ReportType"], "Daily")

    def test_nearest_request(self):
        stations = self.provider.nearest_stations(43.144833, -77.511972, "NY")
        self.assertTrue(stations)
        _url, params = self.client.calls[-1]
        self.assertEqual(params["State"], "NY")
        self.assertNotIn("Station", params)


if __name__ == "__main__":
    unittest.main()
