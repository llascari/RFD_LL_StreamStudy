import unittest
from datetime import date

from streamstudy.providers.usgs import (
    UsgsProvider,
    parse_dv_json,
    parse_iv_json,
    parse_site_rdb,
)
from tests.support import StaticClient, fixture


class SiteParsingTest(unittest.TestCase):
    def test_expanded_site_rdb(self):
        sites = parse_site_rdb(fixture("usgs_site.rdb"))
        self.assertEqual(len(sites), 1)
        site = sites[0]
        self.assertEqual(site.number, "0423205010")
        self.assertIn("IRONDEQUOIT", site.name)
        self.assertAlmostEqual(site.latitude, 43.144833)
        self.assertAlmostEqual(site.longitude, -77.511972)
        self.assertEqual(site.state, "NY")
        self.assertEqual(site.huc, "041401010705")
        self.assertEqual(site.site_type, "Stream")
        self.assertAlmostEqual(site.drainage_area_sq_mi, 142.0)
        self.assertAlmostEqual(site.altitude_ft, 247.51)
        self.assertIn("USGS-0423205010", site.url)

    def test_empty_response_yields_no_sites(self):
        self.assertEqual(parse_site_rdb("# nothing here\n"), [])


class InstantaneousValuesTest(unittest.TestCase):
    def test_parses_both_series(self):
        series = parse_iv_json(fixture("usgs_iv.json"))
        self.assertEqual(sorted(series), ["00060", "00065"])

        discharge = series["00060"]
        self.assertEqual(discharge.name, "Discharge")
        self.assertEqual(discharge.units, "ft\u00b3/s")
        self.assertEqual(len(discharge.valid), 12)
        self.assertAlmostEqual(discharge.latest.value, 74.0)
        self.assertTrue(discharge.provisional)
        self.assertEqual(
            [sample.time for sample in discharge.samples],
            sorted(sample.time for sample in discharge.samples),
        )

        gage = series["00065"]
        self.assertEqual(gage.name, "Gage height")
        self.assertAlmostEqual(gage.latest.value, 2.92)

    def test_times_are_timezone_aware(self):
        series = parse_iv_json(fixture("usgs_iv.json"))["00060"]
        for sample in series.samples:
            self.assertIsNotNone(sample.time.tzinfo)


class DailyValuesTest(unittest.TestCase):
    def test_parses_daily_means(self):
        daily = parse_dv_json(fixture("usgs_dv.json"))
        self.assertIn("00060", daily)
        flow = daily["00060"]
        self.assertEqual(len(flow), 21)
        self.assertEqual(flow[date(2024, 1, 1)], 152)
        self.assertEqual(flow[date(2024, 1, 3)], 113)

    def test_fetch_daily_request(self):
        client = StaticClient()
        provider = UsgsProvider(client)
        provider.fetch_daily(
            "0423205010", date(2024, 1, 1), date(2024, 1, 31), ("00060",)
        )
        url, params = client.calls[-1]
        self.assertIn("/nwis/dv/", url)
        self.assertEqual(params["statCd"], "00003")
        self.assertEqual(params["parameterCd"], "00060")
        self.assertEqual(params["startDT"], "2024-01-01")
        self.assertEqual(params["endDT"], "2024-01-31")


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.client = StaticClient()
        self.provider = UsgsProvider(self.client)

    def test_fetch_site(self):
        site = self.provider.fetch_site("0423205010")
        self.assertEqual(site.number, "0423205010")

    def test_fetch_series_requests_period(self):
        series = self.provider.fetch_series("0423205010", days=14)
        self.assertIn("00060", series)
        url, params = self.client.calls[-1]
        self.assertIn("/nwis/iv/", url)
        self.assertEqual(params["period"], "P14D")
        self.assertEqual(params["sites"], "0423205010")

    def test_search_by_state(self):
        sites = self.provider.search_sites(state="ny")
        self.assertEqual(sites[0].number, "0423205010")
        self.assertEqual(sites[0].state, "NY")
        _url, params = self.client.calls[-1]
        self.assertEqual(params["stateCd"], "NY")
        self.assertEqual(params["parameterCd"], "00060")
        self.assertEqual(params["siteType"], "ST")

    def test_search_by_bounding_box(self):
        self.provider.search_sites(bbox=(-77.6, 43.0, -77.4, 43.3))
        _url, params = self.client.calls[-1]
        self.assertEqual(params["bBox"], "-77.6000,43.0000,-77.4000,43.3000")

    def test_unknown_site_raises(self):
        client = StaticClient({"/nwis/site/": "# empty\n"})
        with self.assertRaises(LookupError):
            UsgsProvider(client).fetch_site("00000000")


if __name__ == "__main__":
    unittest.main()
