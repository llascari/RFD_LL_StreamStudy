import math
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from streamstudy.analysis_window import TimeWindow
from streamstudy.models import FlowEvent, HistoryBundle, ResponseFit, Site
from streamstudy.report import (
    ReportData,
    ReportSite,
    extreme_days,
    summarise_flow,
    summarise_temperature,
    write_report,
)

START = date(2025, 1, 1)


def make_site(number: str, name: str, lat: float, lon: float) -> Site:
    return Site(number=number, name=name, latitude=lat, longitude=lon, state="NY")


def make_history(
    site: Site, days: int = 60, *, with_temperature: bool = True
) -> HistoryBundle:
    flow = {}
    water = {}
    rain = {}
    for offset in range(days):
        day = START + timedelta(days=offset)
        flow[day] = (
            40.0 + 10.0 * math.sin(offset / 5.0) + (80.0 if offset % 15 == 0 else 0.0)
        )
        if with_temperature:
            water[day] = 14.0 + 8.0 * math.sin(offset / 30.0)
        rain[day] = 0.4 if offset % 15 == 0 else 0.0
    events = (
        FlowEvent(
            start=START,
            end=START,
            rain_in=0.4,
            rain_days=1,
            baseline_cfs=40.0,
            peak_cfs=120.0,
            peak_date=START + timedelta(days=1),
            rise_cfs=80.0,
            lag_hours=24.0,
            half_life_days=1.5,
        ),
    )
    fit = ResponseFit(
        events=1,
        slope=200.0,
        ratio_p10=120.0,
        ratio_p50=200.0,
        ratio_p90=300.0,
        r_squared=0.7,
        lag_p50_hours=24.0,
        lag_p10_hours=12.0,
        lag_p90_hours=36.0,
        half_life_days=1.5,
        confidence="low",
    )
    return HistoryBundle(
        start=START,
        end=START + timedelta(days=days - 1),
        precip_source="synthetic",
        precip_days=len(rain),
        flow_days=len(flow),
        events=events,
        fit=fit,
        precip=tuple(sorted(rain.items())),
        water_temp_daily=water,
        flow_daily=flow,
    )


def make_report(region: bool = False) -> ReportData:
    primary_site = make_site(
        "0423205010", "IRONDEQUOIT CR ABOVE BLOSSOM RD", 43.14, -77.51
    )
    primary = ReportSite(
        site=primary_site,
        history=make_history(primary_site),
        air_mean={
            START + timedelta(days=i): 5.0 + 12.0 * math.sin(i / 30.0)
            for i in range(60)
        },
        sunshine={START + timedelta(days=i): 6.0 for i in range(60)},
    )
    sites = ()
    if region:
        other_site = make_site("04232050", "NEARBY CREEK", 43.20, -77.60)
        sites = (
            ReportSite(
                site=other_site,
                history=make_history(other_site, days=45, with_temperature=False),
                air_mean={START + timedelta(days=i): 7.0 for i in range(45)},
                distance_km=8.4,
            ),
        )
    return ReportData(
        primary=primary,
        window=TimeWindow(START, START + timedelta(days=59)),
        radius_km=10.0 if region else 0.0,
        threshold_c=20.0,
        generated=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        region=sites,
    )


class SummaryTest(unittest.TestCase):
    def test_flow_summary(self):
        flow = {START + timedelta(days=i): float(10 + i) for i in range(10)}
        summary = summarise_flow(flow, START, START + timedelta(days=9))
        self.assertEqual(summary.days, 10)
        self.assertEqual(summary.lowest, 10.0)
        self.assertEqual(summary.highest, 19.0)
        self.assertEqual(summary.lowest_day, START)
        self.assertAlmostEqual(summary.mean, 14.5)
        self.assertAlmostEqual(summary.median, 14.5)

    def test_flow_summary_clips_window(self):
        flow = {START + timedelta(days=i): float(i) for i in range(10)}
        summary = summarise_flow(
            flow, START + timedelta(days=2), START + timedelta(days=4)
        )
        self.assertEqual(summary.days, 3)
        self.assertEqual(summary.lowest, 2.0)
        self.assertEqual(summary.highest, 4.0)

    def test_empty_summary_is_nan(self):
        summary = summarise_flow({}, START, START)
        self.assertEqual(summary.days, 0)
        self.assertTrue(math.isnan(summary.mean))

    def test_temperature_longest_run(self):
        values = {
            START + timedelta(days=offset): (22.0 if offset in (0, 1, 2, 5) else 15.0)
            for offset in range(7)
        }
        summary = summarise_temperature(
            values, START, START + timedelta(days=6), 20.0
        )
        self.assertEqual(summary.days, 7)
        self.assertEqual(summary.days_above, 4)
        self.assertEqual(summary.hours_above, 96.0)
        self.assertEqual(summary.longest_run, 3)
        self.assertEqual(summary.highest, 22.0)

    def test_temperature_without_data(self):
        summary = summarise_temperature({}, START, START, 20.0)
        self.assertEqual(summary.days, 0)
        self.assertIsNone(summary.mean)

    def test_extreme_days_order(self):
        values = {START + timedelta(days=i): float(i) for i in range(10)}
        high = extreme_days(values, START, START + timedelta(days=9), 3)
        low = extreme_days(
            values, START, START + timedelta(days=9), 3, highest=False
        )
        self.assertEqual([value for _day, value in high], [9.0, 8.0, 7.0])
        self.assertEqual([value for _day, value in low], [0.0, 1.0, 2.0])


class PdfReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, data: ReportData, name: str = "report.pdf"):
        path = Path(self.tmp.name) / name
        written = write_report(data, path)
        return written, written.read_bytes()

    def test_single_site_report_is_a_pdf(self):
        written, payload = self._write(make_report())
        self.assertTrue(written.exists())
        self.assertTrue(payload.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", payload)
        # cover, flow, temperature, references
        self.assertEqual(payload.count(b"/Type /Page "), 4)
        self.assertIn(b"0423205010", payload)

    def test_region_report_adds_pages_and_site(self):
        _written, payload = self._write(make_report(region=True), "region.pdf")
        self.assertEqual(payload.count(b"/Type /Page "), 6)
        self.assertIn(b"04232050", payload)
        self.assertIn(b"Region report", payload)

    def test_report_survives_missing_temperature_and_flow(self):
        site = make_site("00000001", "DRY CREEK", 43.0, -77.0)
        history = HistoryBundle(
            start=START,
            end=START,
            precip_source="unavailable",
            precip_days=0,
            flow_days=0,
        )
        data = ReportData(
            primary=ReportSite(site=site, history=history),
            window=TimeWindow(START, START),
            threshold_c=20.0,
        )
        written, payload = self._write(data, "empty.pdf")
        self.assertTrue(written.exists())
        self.assertIn(b"/Type /Page ", payload)


if __name__ == "__main__":
    unittest.main()
