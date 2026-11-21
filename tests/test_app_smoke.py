"""Headless smoke tests for the Tk shell, driven entirely by fixtures."""

import tempfile
import time
import unittest
from pathlib import Path

try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None

from streamstudy.app import StreamStudyApp, normalize_site, parse_site_number
from streamstudy.loader import LoadOptions
from streamstudy.providers import (
    CoCoRaHSProvider,
    NwsProvider,
    OpenMeteoProvider,
    UsgsProvider,
)
from tests.support import StaticClient


class NormalizeSiteTest(unittest.TestCase):
    def test_prefixes_and_whitespace(self):
        self.assertEqual(normalize_site("USGS-0423205010"), "0423205010")
        self.assertEqual(normalize_site(" usgs 0423205010 "), "0423205010")
        self.assertEqual(normalize_site("0423205010"), "0423205010")
        self.assertEqual(normalize_site(""), "")

    def test_parse_picker_label(self):
        self.assertEqual(
            parse_site_number(
                "0423205010 \u2014 IRONDEQUOIT CR ABOVE BLOSSOM RD NEAR ROCHESTER NY"
            ),
            "0423205010",
        )
        self.assertEqual(parse_site_number("USGS-0423205010"), "0423205010")
        self.assertEqual(parse_site_number(" 0423205010 "), "0423205010")
        self.assertEqual(parse_site_number("Irondequoit"), "")


@unittest.skipIf(tk is None, "tkinter is not available")
class AppSmokeTest(unittest.TestCase):
    # (tests defined below)

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - no display
            self.skipTest(f"no display available: {exc}")
        self.root.geometry("1180x820")
        self.root.withdraw()
        self.tmp = tempfile.TemporaryDirectory()
        self.client = StaticClient()
        providers = {
            "usgs": UsgsProvider(self.client),
            "nws": NwsProvider(self.client),
            "openmeteo": OpenMeteoProvider(self.client),
            "cocorahs": CoCoRaHSProvider(self.client),
        }
        self.app = StreamStudyApp(
            self.root,
            providers,
            settings_path=str(Path(self.tmp.name) / "settings.json"),
            auto_load=False,
        )
        self.bundle = self.app.loader.load("0423205010", LoadOptions(days=14))
        self.app.apply_bundle(self.bundle)
        self.root.update()

    def tearDown(self):
        try:
            self.app.close()
        except tk.TclError:  # pragma: no cover
            pass
        self.tmp.cleanup()

    def test_site_pulldown_shows_names(self):
        self.assertIn("IRONDEQUOIT", self.app.site_var.get())
        values = self.app.site_combo.cget("values")
        text = " ".join(values) if isinstance(values, tuple) else str(values)
        self.assertIn("0423205010", text)
        self.assertIn("IRONDEQUOIT", text)

    def test_tabs(self):
        labels = [self.app.notebook.tab(tab, "text") for tab in self.app.notebook.tabs()]
        self.assertEqual(
            labels,
            [
                "Overview",
                "Hydrograph",
                "Sensors",
                "Precipitation",
                "Rainfall \u2192 Flow",
                "Map & Correlation",
                "Forecast",
                "Site finder",
            ],
        )

    def test_header_and_status(self):
        self.assertIn("IRONDEQUOIT", self.app.title_label.cget("text"))
        self.assertIn("0423205010", self.app.sub_label.cget("text"))
        self.assertIn("4/4", self.app.status_label.cget("text"))

    def test_overview_cards(self):
        gage = self.app.home_view.gage_card.value_var.get().replace(",", "")
        discharge = self.app.home_view.discharge_card.value_var.get().replace(",", "")
        self.assertGreater(float(gage), 0)
        self.assertGreater(float(discharge), 0)
        self.assertNotEqual(self.app.home_view.precip_card.value_var.get(), "\u2014")

    def test_hydrograph_series(self):
        chart = self.app.hydro_view.discharge_chart
        self.assertEqual(len(chart._all_series), 1)
        self.assertIn("Latest", self.app.hydro_view.discharge_stats.cget("text"))

    def test_precipitation_tables(self):
        summary_rows = self.app.precip_view.summary.get_children()
        self.assertGreaterEqual(len(summary_rows), 2)
        table_rows = self.app.precip_view.table.get_children()
        self.assertEqual(len(table_rows), 14)

    def test_forecast_rows(self):
        rows = self.app.forecast_view.tree.get_children()
        self.assertEqual(len(rows), 4)
        self.assertTrue(self.app.forecast_view.detail.get("1.0", "end").strip())

    def test_charts_actually_draw(self):
        self.root.deiconify()
        self.app.show_hydrograph()
        self.root.update()
        self.app.hydro_view.discharge_chart.redraw()
        self.assertGreater(len(self.app.hydro_view.discharge_chart.find_all()), 0)

    def test_async_load_round_trip(self):
        self.app.bundle = None
        self.app.load_site("0423205010")
        deadline = time.time() + 5
        while self.app.bundle is None and time.time() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNotNone(self.app.bundle)
        self.assertEqual(self.app.bundle.site.number, "0423205010")

    def test_response_view_renders(self):
        from datetime import date, timedelta

        from streamstudy.models import FlowEvent, HistoryBundle, ResponseFit, utc_now

        bundle = self.app.bundle
        assert bundle is not None
        start = date(2023, 11, 20)
        events = tuple(
            FlowEvent(
                start=start + timedelta(days=30 * index),
                end=start + timedelta(days=30 * index),
                rain_in=0.4 + 0.1 * index,
                rain_days=1,
                baseline_cfs=50.0,
                peak_cfs=100.0 + 30 * index,
                peak_date=start + timedelta(days=30 * index + 1),
                rise_cfs=50.0 + 30 * index,
                lag_hours=18.0,
                half_life_days=1.8,
            )
            for index in range(5)
        )
        fit = ResponseFit(
            events=5,
            slope=120.0,
            ratio_p10=60.0,
            ratio_p50=120.0,
            ratio_p90=200.0,
            r_squared=0.62,
            lag_p50_hours=18.0,
            lag_p10_hours=10.0,
            lag_p90_hours=30.0,
            half_life_days=1.8,
            confidence="moderate",
        )
        bundle.history = HistoryBundle(
            start=start,
            end=date(2026, 11, 19),
            precip_source="CoCoRaHS NY-MR-90 (62% of days)",
            precip_days=600,
            flow_days=1000,
            events=events,
            fit=fit,
        )
        bundle.nws_qpf = ((utc_now() + timedelta(hours=4), 0.8),)
        self.app.history_years = 3
        self.app.response_view.render(bundle)

        self.assertEqual(self.app.response_view.response_card.value_var.get(), "120")
        self.assertEqual(len(self.app.response_view.table.get_children()), 5)
        self.assertGreaterEqual(len(self.app.response_view.prediction_chart._all_series), 4)
        self.assertIn("peak", self.app.response_view.outlook.cget("text"))

    def test_sensors_view_renders(self):
        from datetime import timedelta

        from streamstudy.models import MmwSite, Sample, Series, utc_now

        now = utc_now()
        samples = tuple(
            Sample(now - timedelta(hours=index), 2.0 + index * 0.01)
            for index in range(48)
        )
        self.app.bundle.mmw_site = MmwSite(
            identifier="LL_SGTU_TEST2",
            name="Seth Green TU Test #2",
            latitude=43.13232,
            longitude=-77.55477,
            organization="Trout Unlimited",
            distance_km=3.4,
            url="https://monitormywatershed.org/sites/LL_SGTU_TEST2/",
        )
        self.app.bundle.mmw_series = {
            "depth": Series("depth", "Relative water depth", "in", samples, "Monitor My Watershed"),
            "temperature": Series(
                "temperature", "Water temperature", "\u00b0C",
                tuple(Sample(s.time, 8.0 + s.value * 0.1) for s in samples),
                "Monitor My Watershed",
            ),
        }
        self.app.sensors_view.render(self.app.bundle)
        view = self.app.sensors_view
        self.assertIn("Seth Green", view.caption.cget("text"))
        self.assertNotEqual(view.depth_card.value_var.get(), "\u2014")
        self.assertGreaterEqual(len(view.depth_chart._all_series), 1)
        self.assertTrue(view.comparison_var.get())

    def test_site_finder_name_search(self):
        view = self.app.sites_view
        view.name_var.set("Irondequoit")
        view._search_name()
        deadline = time.time() + 5
        while not view._sites and time.time() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(view._sites)
        self.assertGreaterEqual(len(view.tree.get_children()), 1)

    def test_about_dialog(self):
        from unittest.mock import patch

        with patch("streamstudy.app.messagebox.showinfo") as showinfo:
            self.app.show_about()
        showinfo.assert_called_once()
        _title, message = showinfo.call_args.args
        self.assertIn("DeepSeek V4.1 Flash", message)

    def test_site_search(self):
        sites = self.app.providers["usgs"].search_sites(state="NY")
        self.assertEqual(sites[0].number, "0423205010")


if __name__ == "__main__":
    unittest.main()
