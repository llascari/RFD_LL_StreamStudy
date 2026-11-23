import unittest
from datetime import date, datetime, time, timedelta, timezone

from streamstudy.analysis_window import TimeWindow
from streamstudy.loader import BundleLoader, ReportCancelled, _haversine_km
from streamstudy.models import HistoryBundle, MmwSite, Sample, Series, Site
from streamstudy.providers.openmeteo import ArchiveData

START = date(2025, 1, 1)
WINDOW = TimeWindow(START, START + timedelta(days=29))


def make_site(number: str, lat: float, lon: float) -> Site:
    return Site(number=number, name=f"SITE {number}", latitude=lat, longitude=lon)


def make_history(site: Site, days: int = 30) -> HistoryBundle:
    flow = {START + timedelta(days=i): 20.0 + i for i in range(days)}
    return HistoryBundle(
        start=START,
        end=START + timedelta(days=days - 1),
        precip_source="synthetic",
        precip_days=days,
        flow_days=len(flow),
        flow_daily=flow,
    )


class FakeUsgs:
    def __init__(self, sites=()) -> None:
        self.sites = list(sites)
        self.calls = []

    def search_sites(self, *, bbox=None, limit=400):
        self.calls.append(bbox)
        return list(self.sites)


class ArchiveStub:
    def fetch_archive(self, *args, **kwargs):
        return ArchiveData(daily=(), timezone="UTC", weather=())


class FakeReportLoader(BundleLoader):
    def __init__(self, sites=(), *, fail_times: int = 0) -> None:
        self.usgs = FakeUsgs(sites)
        self.openmeteo = ArchiveStub()
        self.fail_times = fail_times
        self.history_calls = 0

    def load_history(
        self, site, *, window=None, years=None, coco_station=None, stage=None
    ):
        if stage is not None:
            stage("USGS daily flow and water temperature")
        self.history_calls += 1
        if self.history_calls <= self.fail_times:
            raise RuntimeError("temporary network failure")
        return make_history(site)


class FakeMmw:
    def nearest_sites(self, *args, **kwargs):
        return [
            MmwSite(
                identifier="TEST_SENSOR",
                name="TEST SENSOR",
                latitude=43.0,
                longitude=-77.0,
                distance_km=1.0,
            )
        ]

    def sensors_for_site(self, site_code, *, days=30):
        samples = []
        for offset in range(10):
            day = START + timedelta(days=offset)
            samples.append(
                Sample(
                    datetime.combine(day, time(12), tzinfo=timezone.utc),
                    10.0 + offset,
                )
            )
        return {
            "temperature": Series(
                "temperature", "Water temperature", "\u00b0C", tuple(samples), "MMW"
            )
        }


class HaversineTest(unittest.TestCase):
    def test_zero_and_known_distance(self):
        self.assertEqual(_haversine_km(43.0, -77.0, 43.0, -77.0), 0.0)
        distance = _haversine_km(43.14, -77.51, 43.15, -77.52)
        self.assertGreater(distance, 0.5)
        self.assertLess(distance, 3.0)


class ReportSiteTest(unittest.TestCase):
    def test_retries_then_succeeds(self):
        loader = FakeReportLoader(fail_times=1)
        report = loader.load_report_site(
            make_site("1", 43.0, -77.0), WINDOW, retries=1
        )
        self.assertEqual(report.site.number, "1")
        self.assertEqual(loader.history_calls, 2)

    def test_gives_up_after_retries(self):
        loader = FakeReportLoader(fail_times=5)
        with self.assertRaises(RuntimeError):
            loader.load_report_site(make_site("1", 43.0, -77.0), WINDOW, retries=1)
        self.assertEqual(loader.history_calls, 2)

    def test_report_site_includes_mmw_temperature(self):
        loader = FakeReportLoader()
        loader.mmw = FakeMmw()
        report = loader.load_report_site(
            make_site("1", 43.0, -77.0), WINDOW, include_mmw=True
        )
        self.assertTrue(report.mmw_name.startswith("TEST SENSOR"))
        self.assertTrue(report.mmw_temp_daily)

    def test_cancel_is_checked_before_work(self):
        loader = FakeReportLoader()
        with self.assertRaises(ReportCancelled):
            loader.load_report_site(
                make_site("1", 43.0, -77.0),
                WINDOW,
                retries=2,
                cancel=lambda: True,
            )
        self.assertEqual(loader.history_calls, 0)


class ReportRegionTest(unittest.TestCase):
    def setUp(self):
        self.primary = make_site("0423205010", 43.14, -77.51)
        self.near = make_site("04232050", 43.15, -77.52)
        self.nearer = make_site("04232060", 43.145, -77.515)
        self.far = make_site("04232070", 44.50, -77.51)

    def test_radius_filters_and_sorts(self):
        loader = FakeReportLoader([self.near, self.nearer, self.far, self.primary])
        data = loader.load_report_region(
            self.primary, WINDOW, radius_km=5.0, max_sites=4
        )
        numbers = [site.site.number for site in data.region]
        self.assertEqual(numbers, ["04232060", "04232050"])
        self.assertLess(data.region[0].distance_km, data.region[1].distance_km)
        self.assertNotIn("04232070", numbers)
        self.assertEqual(data.window.start, WINDOW.start)

    def test_max_sites_limits_neighbours(self):
        loader = FakeReportLoader([self.near, self.nearer, self.far])
        data = loader.load_report_region(
            self.primary, WINDOW, radius_km=20.0, max_sites=2
        )
        self.assertEqual(len(data.region), 1)
        self.assertEqual(data.region[0].site.number, "04232060")

    def test_region_can_be_disabled(self):
        loader = FakeReportLoader([self.near])
        data = loader.load_report_region(
            self.primary, WINDOW, radius_km=20.0, include_region=False
        )
        self.assertEqual(data.region, ())
        self.assertEqual(data.radius_km, 0.0)
        self.assertEqual(loader.usgs.calls, [])

    def test_progress_finishes_at_one(self):
        loader = FakeReportLoader([self.near])
        seen = []
        data = loader.load_report_region(
            self.primary,
            WINDOW,
            radius_km=10.0,
            max_sites=3,
            threshold_c=18.5,
            progress=lambda fraction, message: seen.append((fraction, message)),
        )
        self.assertAlmostEqual(seen[-1][0], 1.0)
        fractions = [fraction for fraction, _message in seen]
        self.assertEqual(fractions, sorted(fractions))
        messages = [message for _fraction, message in seen]
        self.assertTrue(any("Site 1 of 2" in message for message in messages))
        self.assertTrue(any("USGS daily" in message for message in messages))
        self.assertTrue(any("Site ready" in message for message in messages))
        self.assertEqual(data.threshold_c, 18.5)

    def test_failing_neighbour_is_recorded_and_report_continues(self):
        class PartlyFlaky(FakeReportLoader):
            def load_history(
                self,
                site,
                *,
                window=None,
                years=None,
                coco_station=None,
                stage=None,
            ):
                if site.number == "04232050":
                    raise RuntimeError("no daily values")
                if stage is not None:
                    stage("USGS daily flow and water temperature")
                return make_history(site)

        loader = PartlyFlaky([self.near, self.nearer])
        data = loader.load_report_region(
            self.primary, WINDOW, radius_km=10.0, max_sites=3, retries=0
        )
        self.assertEqual([site.site.number for site in data.region], ["04232060"])
        self.assertTrue(
            any(self.near.number in failure for failure in data.failures)
        )

    def test_cancel_stops_region(self):
        loader = FakeReportLoader([self.near])
        with self.assertRaises(ReportCancelled):
            loader.load_report_region(
                self.primary, WINDOW, radius_km=10.0, cancel=lambda: True
            )


if __name__ == "__main__":
    unittest.main()
