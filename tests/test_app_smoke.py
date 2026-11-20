"""Headless smoke tests for the Tk shell, driven entirely by fixtures."""

import tempfile
import time
import unittest
from pathlib import Path

try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None

from streamstudy.app import StreamStudyApp, normalize_site
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


@unittest.skipIf(tk is None, "tkinter is not available")
class AppSmokeTest(unittest.TestCase):
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

    def test_tabs(self):
        labels = [self.app.notebook.tab(tab, "text") for tab in self.app.notebook.tabs()]
        self.assertEqual(
            labels, ["Overview", "Hydrograph", "Precipitation", "Forecast", "Site finder"]
        )

    def test_header_and_status(self):
        self.assertIn("IRONDEQUOIT", self.app.title_label.cget("text"))
        self.assertIn("0423205010", self.app.sub_label.cget("text"))
        self.assertIn("4/4", self.app.status_label.cget("text"))

    def test_overview_cards(self):
        self.assertEqual(self.app.home_view.gage_card.value_var.get(), "2.92")
        self.assertEqual(self.app.home_view.discharge_card.value_var.get(), "74")
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

    def test_site_search(self):
        sites = self.app.providers["usgs"].search_sites(state="NY")
        self.assertEqual(sites[0].number, "0423205010")


if __name__ == "__main__":
    unittest.main()
