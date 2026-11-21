"""Map canvas, heatmap and click-to-load tests (no network, no tiles required)."""

import math
import unittest
from datetime import date, timedelta

try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None

from streamstudy.correlation import build_regional
from streamstudy.models import Site
from streamstudy.ui.map_view import MapView

START = date(2025, 1, 1)

# 1x1 transparent-ish PNG, enough to exercise PhotoImage decoding.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)


class StubApp:
    map_zoom = 10
    map_years = 2

    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.view_changes: list[tuple[float, float, int]] = []

    def load_site(self, number: str) -> None:
        self.loaded.append(number)

    def zoom_map(self, delta: int) -> None:  # pragma: no cover
        self.map_zoom += delta

    def fit_map_to_sites(self, sites) -> None:  # pragma: no cover
        return None

    def set_map_years(self, years: int) -> None:  # pragma: no cover
        self.map_years = years

    def request_map(self, force: bool = False) -> None:  # pragma: no cover
        return None

    def request_regional(self, force: bool = False) -> None:  # pragma: no cover
        return None

    def request_map_view(
        self, latitude: float, longitude: float, zoom: int, force: bool = False
    ) -> None:
        self.view_changes.append((latitude, longitude, zoom))

    def recenter_map(self) -> None:  # pragma: no cover
        return None


def wave(days: int = 240, phase: float = 0.0) -> dict[date, float]:
    return {
        START + timedelta(days=index): 50.0 + 20.0 * math.sin((index + phase) / 5.0)
        for index in range(days)
    }


@unittest.skipIf(tk is None, "tkinter is not available")
class MapWidgetTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover
            self.skipTest(f"no display available: {exc}")
        self.root.geometry("1100x800")
        self.root.deiconify()
        self.app = StubApp()
        self.view = MapView(self.root, self.app)
        self.view.pack(fill="both", expand=True)
        self.site = Site(
            "0423205010",
            "IRONDEQUOIT CR ABOVE BLOSSOM RD",
            43.1448,
            -77.5120,
            state="NY",
            site_type="Stream",
            drainage_area_sq_mi=142.0,
        )
        self.other = Site(
            "04232050", "ALLEN CREEK AT ROCHESTER", 43.10, -77.60, state="NY"
        )
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_markers_and_tiles_draw(self):
        self.view.set_map(
            (self.site.latitude, self.site.longitude),
            10,
            [self.site, self.other],
            {(10, 1, 1): TINY_PNG},
            self.site.number,
        )
        self.root.update()
        items = self.view.map.find_all()
        self.assertGreater(len(items), 0)
        self.assertEqual(len(self.view._sites), 2)
        self.assertEqual(self.view.map._nearest(*self.view.map._site_pixel(self.other)), self.other)

    def test_marker_click_loads_site(self):
        self.view.set_map(
            (self.site.latitude, self.site.longitude),
            10,
            [self.site, self.other],
            {},
            self.site.number,
        )
        self.root.update()
        x, y = self.view.map._site_pixel(self.other)
        event = self._event(x, y)
        self.view.map._on_press(event)
        self.view.map._on_release(event)
        self.assertEqual(self.app.loaded, [self.other.number])

    @staticmethod
    def _event(x: float, y: float):
        class Event:
            pass

        event = Event()
        event.x, event.y = x, y
        return event

    def test_drag_pans_and_requests_a_new_view(self):
        self.view.set_map(
            (self.site.latitude, self.site.longitude),
            10,
            [self.site, self.other],
            {},
            self.site.number,
        )
        self.root.update()
        start = self._event(400, 300)
        end = self._event(470, 330)
        self.view.map._on_press(start)
        self.view.map._on_drag(end)
        self.view.map._on_release(end)
        self.assertTrue(self.app.view_changes)
        latitude, longitude, zoom = self.app.view_changes[-1]
        self.assertEqual(zoom, 10)
        self.assertLess(longitude, self.site.longitude)  # dragged east -> view moves west
        self.assertGreater(latitude, self.site.latitude)  # dragged down -> view moves north
        # Optimistic move: the canvas already shows the new centre instead of
        # snapping back while tiles/gages load.
        self.assertAlmostEqual(self.view.map._center[0], latitude)
        self.assertAlmostEqual(self.view.map._center[1], longitude)

    def test_name_filter(self):
        self.view.set_map(
            (self.site.latitude, self.site.longitude),
            10,
            [self.site, self.other],
            {},
            self.site.number,
        )
        self.root.update()
        self.view.map.set_filter("allen")
        self.assertEqual(self.view.map.visible_sites(), [self.other])
        self.view.map.set_filter("0423")
        self.assertEqual(len(self.view.map.visible_sites()), 2)
        self.view.map.set_filter("nothing-matches")
        self.assertEqual(self.view.map.visible_sites(), [])

    def test_resize_requests_a_fresh_view(self):
        self.view.set_map(
            (self.site.latitude, self.site.longitude),
            10,
            [self.site],
            {},
            self.site.number,
        )
        self.root.update()

        class SizeEvent:
            pass

        first = SizeEvent()
        first.width, first.height = 600, 400
        self.view.map._on_configure(first)
        second = SizeEvent()
        second.width, second.height = 760, 520
        self.view.map._on_configure(second)
        self.view.map._notify_resize()
        self.assertTrue(self.app.view_changes)
        self.assertEqual(self.app.view_changes[-1][2], 10)

    def test_wheel_zooms(self):
        self.view.set_map(
            (self.site.latitude, self.site.longitude),
            10,
            [self.site],
            {},
            self.site.number,
        )
        self.root.update()
        self.view.map._on_wheel(self._event(400, 300), 1)
        self.assertEqual(self.app.view_changes[-1][2], 11)
        self.view.map._on_wheel(self._event(400, 300), -1)
        self.assertEqual(self.app.view_changes[-1][2], 9)

    def test_heatmap_and_rain_table(self):
        sites = (
            self.site,
            self.other,
            Site("04232060", "RED CREEK", 43.25, -77.40),
        )
        flows = {
            "0423205010": wave(phase=0),
            "04232050": wave(phase=15),
            "04232060": wave(phase=0),
        }
        rain = {
            START + timedelta(days=index): max(
                0.0, 0.3 + 0.3 * math.sin(index / 7.0)
            )
            for index in range(240)
        }
        analysis = build_regional(
            sites,
            flows,
            {"ERA5": rain, "CoCoRaHS NY-MR-61": rain},
            start=START,
            end=START + timedelta(days=239),
        )
        self.view.set_correlation(analysis)
        self.root.update()
        self.assertGreater(len(self.view.heatmap.find_all()), 0)
        self.assertGreaterEqual(len(self.view.rain_tree.get_children()), 3)
        self.assertIn("Strongest pairs", self.view.pairs_var.get())


if __name__ == "__main__":
    unittest.main()
