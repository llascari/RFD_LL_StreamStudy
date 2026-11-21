import json
import unittest
from datetime import date

from streamstudy.providers.monitormywatershed import (
    MonitorMyWatershedProvider,
    choose_results,
    parse_metadata,
    parse_sites,
    parse_timeseries,
)
from tests.support import FakeMmwClient, fixture


class SiteParsingTest(unittest.TestCase):
    def test_parses_browse_block(self):
        sites = parse_sites(fixture("mmw_sites.html"))
        self.assertEqual(len(sites), 3)
        by_code = {site.identifier: site for site in sites}
        self.assertIn("LL_SGTU_TEST2", by_code)
        station = by_code["LL_SGTU_TEST2"]
        self.assertEqual(station.name, "Seth Green TU Test #2")
        self.assertAlmostEqual(station.latitude, 43.13232, places=4)
        self.assertAlmostEqual(station.longitude, -77.55477, places=4)
        self.assertEqual(station.organization, "Trout Unlimited")
        self.assertTrue(station.url.startswith("https://monitormywatershed.org/sites/"))

    def test_invalid_page_returns_empty(self):
        self.assertEqual(parse_sites("<html>no data</html>"), [])


class MetadataTest(unittest.TestCase):
    def test_results_and_selection(self):
        results = parse_metadata(fixture("mmw_metadata.json"))
        self.assertEqual(len(results), 9)
        chosen = choose_results(results)
        self.assertEqual(chosen["depth"]["resultid"], 8061)
        self.assertEqual(chosen["temperature"]["unitsabbreviation"], "degC")
        self.assertEqual(chosen["conductance"]["resultid"], 8062)

    def test_equipment_temperature_is_ignored(self):
        results = [
            {
                "resultid": 1,
                "variablenamecv": "Temperature",
                "unitsabbreviation": "degF",
                "sampledmediumcv": "Equipment",
                "variablecode": "Batt_Temp",
            }
        ]
        self.assertEqual(choose_results(results), {})


class TimeseriesTest(unittest.TestCase):
    def test_parses_epoch_milliseconds(self):
        samples = parse_timeseries(fixture("mmw_depth.json"))
        self.assertEqual(len(samples), 20)
        self.assertEqual([s.time for s in samples], sorted(s.time for s in samples))
        self.assertIsNotNone(samples[0].time.tzinfo)
        self.assertTrue(all(s.value is not None for s in samples))

    def test_filters_odm2_missing_sentinel(self):
        payload = {
            "valuedatetime": {"0": 1794942000000, "1": 1794942900000},
            "datavalue": {"0": -9999.0, "1": 12.3},
        }
        samples = parse_timeseries(json.dumps(payload))
        self.assertEqual(len(samples), 1)
        self.assertAlmostEqual(samples[0].value, 12.3)


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeMmwClient()
        self.provider = MonitorMyWatershedProvider(self.client)

    def test_nearest_sites(self):
        nearby = self.provider.nearest_sites(43.1448, -77.5120, limit=3, max_km=60)
        self.assertEqual(len(nearby), 3)
        self.assertEqual(nearby[0].identifier, "LL_SGTU_TEST2")
        self.assertLess(nearby[0].distance_km, 10.0)
        distances = [site.distance_km for site in nearby]
        self.assertEqual(distances, sorted(distances))

    def test_sensor_series(self):
        series = self.provider.sensors_for_site("LL_SGTU_TEST2", days=14)
        self.assertIn("depth", series)
        self.assertIn("temperature", series)
        self.assertEqual(series["depth"].units, "in")
        self.assertEqual(series["temperature"].units, "\u00b0C")
        self.assertEqual(series["depth"].source, "Monitor My Watershed")
        self.assertTrue(series["depth"].valid)

    def test_series_request_shape(self):
        self.provider.series(8061, date(2026, 11, 18), date(2026, 11, 20))
        request = self.client.calls[-1]
        self.assertEqual(request["method"], "get_result_timeseries")
        self.assertEqual(request["resultid"], 8061)
        self.assertEqual(request["start_date"], "2026-11-18")
        self.assertEqual(request["end_date"], "2026-11-20")


if __name__ == "__main__":
    unittest.main()
