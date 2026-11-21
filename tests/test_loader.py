import unittest

from streamstudy.loader import BundleLoader, LoadOptions
from streamstudy.providers import (
    CoCoRaHSProvider,
    NwsProvider,
    OpenMeteoProvider,
    UsgsProvider,
)
from tests.support import StaticClient, default_mapping


def build_loader(client: StaticClient) -> BundleLoader:
    return BundleLoader(
        UsgsProvider(client),
        NwsProvider(client),
        OpenMeteoProvider(client),
        CoCoRaHSProvider(client),
    )


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.client = StaticClient()
        self.loader = build_loader(self.client)

    def test_full_bundle(self):
        bundle = self.loader.load("0423205010", LoadOptions(days=14))
        self.assertEqual(bundle.site.number, "0423205010")
        self.assertIn("00060", bundle.usgs)
        self.assertIn("00065", bundle.usgs)
        self.assertEqual(bundle.nws_station.identifier, "KGVQ")
        self.assertEqual(len(bundle.nws_daily), 4)
        self.assertGreaterEqual(len(bundle.nws_qpf), 8)
        self.assertEqual(len(bundle.openmeteo_daily), 3)
        self.assertEqual(bundle.coco_station.identifier, "NY-MR-90")
        self.assertEqual(len(bundle.coco_daily), 10)
        self.assertEqual(bundle.errors, [])
        self.assertEqual(bundle.ok_sources, 4)

    def test_partial_failure_is_collected(self):
        mapping = default_mapping()
        mapping["open-meteo.com"] = "<html>service unavailable</html>"
        client = StaticClient(mapping)
        bundle = build_loader(client).load("0423205010", LoadOptions(days=7))
        self.assertTrue(any("Open-Meteo" in error for error in bundle.errors))
        self.assertEqual(bundle.openmeteo_hourly, ())
        self.assertEqual(bundle.ok_sources, 3)
        self.assertTrue(bundle.usgs)

    def test_unknown_site_raises_lookup_error(self):
        client = StaticClient({"/nwis/site/": "# empty\n"})
        with self.assertRaises(LookupError):
            build_loader(client).load("00000000")

    def test_regional_analysis(self):
        site = self.loader.load("0423205010", LoadOptions(days=7)).site
        other = type(site)(
            number="04232050", name="Nearby Creek", latitude=43.10, longitude=-77.60
        )
        analysis = self.loader.load_regional([site, other], years=2)
        self.assertEqual(len(analysis.sites), 2)
        self.assertIn("0423205010", analysis.flow)
        self.assertEqual(analysis.errors, [])
        self.assertGreaterEqual(len(analysis.precip_labels), 1)

    def test_history_carries_precip_series(self):
        site = self.loader.load("0423205010", LoadOptions(days=7)).site
        history = self.loader.load_history(site, years=3)
        self.assertTrue(history.precip)
        self.assertEqual(history.precip, tuple(sorted(history.precip)))

    def test_explicit_coco_station(self):
        bundle = self.loader.load(
            "0423205010", LoadOptions(days=7, coco_station="NY-MR-90")
        )
        self.assertEqual(bundle.coco_station.identifier, "NY-MR-90")
        _url, params = self.client.calls[-1]
        self.assertEqual(params["Station"], "NY-MR-90")


if __name__ == "__main__":
    unittest.main()
