"""Headless smoke tests for the Tk shell, driven entirely by fixtures."""

import tempfile
import time
import unittest
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover
    tk = None
    ttk = None

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
            auto_update_check=False,
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

    def test_update_banner(self):
        from streamstudy.updates import UpdateStatus

        status = UpdateStatus(
            available=True,
            method="git",
            local="a" * 40,
            remote="b" * 40,
            remote_date="2026-11-21T12:00:00Z",
            url="https://github.com/llascari/RFD_LL_StreamStudy",
        )
        self.app._finish_update_check(status, None, False)
        self.assertIn("Update available", self.app.update_label.cget("text"))
        self.assertIn("Update available", self.app.status_label.cget("text"))

        current = UpdateStatus(
            available=False, method="git", local="b" * 40, remote="b" * 40
        )
        self.app._finish_update_check(current, None, False)
        self.assertEqual(self.app.update_label.cget("text"), "")

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
                "Temperature",
                "Temp Drivers",
                "Precipitation",
                "Rainfall \u2192 Flow",
                "Map & Correlation",
                "Forecast",
                "Flow forecast",
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

    def test_chart_hover_tooltip_draws_text(self):
        from datetime import datetime, timezone

        from streamstudy.ui.theme import font_family

        chart = self.app.hydro_view.discharge_chart
        chart._draw_tooltip(
            datetime.now(timezone.utc),
            [("Observed", 73.0), ("Predicted", 90.0)],
            120,
            20,
            800,
            font_family(self.root),
        )
        texts = [
            item for item in chart.find_all() if chart.type(item) == "text"
        ]
        rendered = "\n".join(chart.itemcget(item, "text") for item in texts)
        self.assertIn("Observed: 73.00", rendered)
        self.assertIn("Predicted: 90.00", rendered)

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
        self.app.response_view.render(bundle)

        self.assertEqual(self.app.response_view.response_card.value_var.get(), "120")
        self.assertEqual(len(self.app.response_view.table.get_children()), 5)
        self.assertGreaterEqual(len(self.app.response_view.prediction_chart._all_series), 4)
        self.assertIn("peak", self.app.response_view.outlook.cget("text"))
        metrics = self.app.response_view.metrics_text.get()
        self.assertIn("% of baseflow", metrics)
        self.assertIn("% of peak", metrics)
        self.assertIn("decay", metrics)
        self.assertIn("0423205010", self.app.flow_metrics)
        stored = self.app.flow_metrics["0423205010"]
        self.assertIn("rise_pct_base", stored)
        self.assertIn("decay_24h_pct", stored)

    def test_temperature_view_renders(self):
        from datetime import date, timedelta

        from streamstudy.models import Sample, Series, WeatherDay, utc_now

        now = utc_now()
        self.app.bundle.weather_days = tuple(
            WeatherDay(
                day=date.today() - timedelta(days=index),
                mean_c=10.0 + index,
                sunshine_hours=5.0 + index * 0.2,
                cloud_pct=15.0 if index < 3 else 60.0,
            )
            for index in range(10)
        )
        self.app.bundle.weather_zone = "America/New_York"
        self.app.bundle.water_temp_daily = {
            date.today() - timedelta(days=index): 18.0 + index * 0.5
            for index in range(10)
        }
        self.app.bundle.usgs["00010"] = Series(
            "00010",
            "Water temperature",
            "\u00b0C",
            tuple(
                Sample(now - timedelta(hours=index), 21.0) for index in range(48)
            ),
            "USGS NWIS",
        )
        self.app.temperature_view.render(self.app.bundle)
        view = self.app.temperature_view
        self.assertNotEqual(view.water_card.value_var.get(), "\u2014")
        self.assertNotEqual(view.air_card.value_var.get(), "\u2014")
        self.assertGreaterEqual(len(view.temp_chart._all_series), 2)
        self.assertIn("%", view.stat_vars["above"].get())
        self.assertIn("r ", view.compare_var.get())

    def test_thermal_view_renders_correlations(self):
        from datetime import date, timedelta

        from streamstudy.models import WeatherDay

        if self.app.bundle.history is not None:
            self.app.bundle.history.water_temp_daily = {}
            self.app.bundle.history.air_mean = {}
            self.app.bundle.history.sunshine = {}
        days = [date.today() - timedelta(days=index) for index in range(20)]
        self.app.bundle.water_temp_daily = {
            day: 9.0 + 0.4 * (19 - index) for index, day in enumerate(days)
        }
        self.app.bundle.weather_days = tuple(
            WeatherDay(
                day,
                mean_c=4.0 + 0.6 * (19 - index),
                sunshine_hours=3.0 + 0.3 * (19 - index),
            )
            for index, day in enumerate(days)
        )
        self.app.thermal_view.render(self.app.bundle)
        view = self.app.thermal_view
        self.assertIn("USGS", view.source_var.get())
        self.assertIsNotNone(view._analysis)
        self.assertGreaterEqual(len(view.air_scatter.find_all()), 1)
        self.assertGreaterEqual(len(view.sun_scatter.find_all()), 1)
        self.assertEqual(len(view.table.get_children()), 11)
        # Rise over normal is the default basis and shows slopes; absolute shows r.
        self.assertEqual(view.basis_var.get(), "Rise over normal")
        self.assertTrue(view.sun_card.value_var.get().startswith("+"))
        view.basis_var.set("Absolute")
        view._render_selected()
        self.assertTrue(view.sun_card.value_var.get().startswith("r "))
        view.basis_var.set("Rise over normal")
        view._render_selected()

    def test_thermal_peer_dialog_lists_rows(self):
        from streamstudy.thermal import SunlightPeer

        rows = (
            SunlightPeer(
                "A", "SUN CREEK", 0.0, water_days=30,
                sun_r=0.7, air_r=0.5, slope_c_per_hour=1.4,
                lag_days=0, pairs=28, confidence="moderate", this_site=True,
            ),
            SunlightPeer("B", "SHADY CREEK", 9.0, water_days=25, error="boom"),
        )
        self.app.thermal_view.show_peer_comparison(rows)
        self.root.update()

        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)

        try:
            toplevels = [
                child
                for child in self.root.winfo_children()
                if isinstance(child, tk.Toplevel)
            ]
            self.assertTrue(toplevels)
            dialog = toplevels[-1]
            trees = [
                widget for widget in walk(dialog) if isinstance(widget, ttk.Treeview)
            ]
            self.assertEqual(len(trees), 1)
            self.assertEqual(len(trees[0].get_children()), 2)
        finally:
            for child in self.root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()
        self.root.update()

    def test_reset_settings(self):
        from unittest.mock import patch

        self.app.set_temperature_threshold(25.0)
        self.app.set_days(30)
        self.app.flow_metrics["x"] = {"rise_pct_base": 1.0}
        with patch("streamstudy.app.messagebox.askyesno", return_value=True):
            self.app.reset_settings()
        self.assertEqual(self.app.temperature_threshold, 20.0)
        self.assertEqual(self.app.days, 14)
        self.assertEqual(self.app.flow_metrics, {})
        self.assertEqual(self.app.settings["temperature_threshold_c"], 20.0)
        self.assertEqual(self.app.settings["days"], 14)

    def test_ranking_view(self):
        from streamstudy.ranking import Ranking, SiteScore

        site = self.app.bundle.site
        score = SiteScore(
            site=site,
            score=6.4,
            r_squared=0.4,
            events=90,
            mean_peer_r=0.8,
            has_temperature=True,
            distance_km=0.0,
            reasons="90 storms \u00b7 r\u00b2 0.40",
        )
        self.app.sites_view.show_ranking(Ranking(scores=(score,), hub=score))
        rows = self.app.sites_view.tree.get_children()
        self.assertEqual(len(rows), 1)
        values = self.app.sites_view.tree.item(rows[0], "values")
        self.assertEqual(values[-1], "6.4")
        self.assertIn("Suggested:", self.app.sites_view.status_var.get())

    def test_analysis_window_setting(self):
        from streamstudy.analysis_window import preset_window
        from streamstudy.settings import load_settings

        self.app.set_analysis_window(preset_window("30d"))
        self.assertEqual(self.app.analysis_window.days, 30)
        reloaded = load_settings(str(self.app.settings_path))
        self.assertEqual(reloaded["analysis_window"]["mode"], "30d")
        self.assertIn("30 days", self.app.response_view.window_var.get())

    def test_temperature_threshold_persists(self):
        self.app.set_temperature_threshold(18.5)
        self.assertEqual(self.app.settings["temperature_threshold_c"], 18.5)
        from streamstudy.settings import load_settings

        reloaded = load_settings(str(self.app.settings_path))
        self.assertEqual(reloaded["temperature_threshold_c"], 18.5)

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

    def test_file_menu_has_report_command(self):
        menubar = self.root.nametowidget(self.root.cget("menu"))
        entries = {
            menubar.entrycget(index, "label"): index
            for index in range(menubar.index("end") + 1)
            if menubar.type(index) != "tearoff"
        }
        self.assertIn("File", entries)
        file_menu = self.root.nametowidget(
            menubar.entrycget(entries["File"], "menu")
        )
        commands = [
            file_menu.entrycget(index, "label")
            for index in range(file_menu.index("end") + 1)
            if file_menu.type(index) != "separator"
        ]
        self.assertIn("Generate PDF report\u2026", commands)

    def test_report_dialog_opens_for_loaded_site(self):
        from streamstudy.ui.report_dialog import ReportDialog

        dialog = ReportDialog(self.app)
        self.root.update()
        self.assertIn("StreamStudy_0423205010_", dialog.path_var.get())
        self.assertEqual(str(dialog.open_button.cget("state")), "disabled")
        self.assertEqual(str(dialog.cancel_button.cget("state")), "disabled")
        self.assertEqual(dialog.elapsed_var.get(), "Elapsed 00:00")
        dialog._on_close()

    def test_report_dialog_progress_polls_to_completion(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from streamstudy.ui.report_dialog import ReportDialog

        dialog = ReportDialog(self.app)
        output = Path(self.tmp.name) / "progress.pdf"
        output.write_bytes(b"%PDF-1.4\n%%EOF\n")
        dialog.path_var.set(str(output))
        fake = SimpleNamespace(region=(), failures=())
        with patch.object(
            self.app.loader, "load_report_region", return_value=fake
        ):
            with patch(
                "streamstudy.ui.report_dialog.write_report", return_value=output
            ):
                dialog._start()
                self.assertIsNotNone(dialog._poll_id)
                deadline = time.time() + 5
                while dialog._running and time.time() < deadline:
                    self.root.update()
                    time.sleep(0.02)
        self.assertFalse(dialog._running)
        self.assertIn("Report written", dialog.progress_var.get())
        self.assertIn("Finished in", dialog.elapsed_var.get())
        dialog._on_close()

    def test_site_search(self):
        sites = self.app.providers["usgs"].search_sites(state="NY")
        self.assertEqual(sites[0].number, "0423205010")


if __name__ == "__main__":
    unittest.main()
