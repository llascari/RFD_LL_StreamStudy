"""StreamStudy application shell: header, tabs, background loading."""

from __future__ import annotations

import math
import queue
import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .credits import ABOUT_TEXT
from .http import HttpClient
from .loader import BundleLoader, LoadOptions
from .models import DataBundle
from .providers import build_providers
from .settings import (
    ALLOWED_DAYS,
    DEFAULTS,
    DEFAULT_SITE,
    load_settings,
    remember_site,
    save_settings,
)
from .ui.forecast_view import ForecastView
from .ui.home_view import HomeView
from .ui.hydro_view import HydroView
from .ui.map_view import (
    MapView,
    fetch_tiles,
    tiles_for_bbox,
    view_bbox,
    zoom_for_radius,
)
from .ui.precip_view import PrecipView
from .ui.response_view import ResponseView
from .ui.sensors_view import SensorsView
from .ui.sites_view import SitesView
from .ui.temperature_view import TemperatureView
from .ui.theme import (
    ACCENT,
    BAD,
    BG,
    GOOD,
    MUTED,
    SURFACE,
    TEXT,
    WARN,
    apply_theme,
    font_family,
)

APP_NAME = "StreamStudy"
USER_AGENT = "RFD-StreamStudy/0.1 (+https://github.com/llascari/RFD_StreamStudy)"
SOURCE_LABELS = (
    ("usgs", "USGS"),
    ("nws", "NWS"),
    ("openmeteo", "Open-Meteo"),
    ("cocorahs", "CoCoRaHS"),
    ("mmw", "MMW"),
)
STATUS_COLORS = {"muted": MUTED, "good": GOOD, "warn": WARN, "bad": BAD, "accent": ACCENT}


def normalize_site(value: str) -> str:
    text = (value or "").strip().upper()
    for prefix in ("USGS-", "USGS "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.strip()


_SITE_ID = re.compile(r"(\d{4,15})")


def parse_site_number(value: str) -> str:
    """Pull the USGS site number out of a picker label or a typed entry."""
    text = (value or "").strip()
    match = _SITE_ID.search(text)
    if match:
        return match.group(1)
    return text if text.isdigit() else ""


class StreamStudyApp:
    def __init__(
        self,
        root: tk.Tk,
        providers: dict | None = None,
        settings_path: str | None = None,
        auto_load: bool = True,
    ) -> None:
        self.root = root
        self.client = HttpClient(USER_AGENT)
        self.providers = providers if providers is not None else build_providers(self.client)
        self.loader = BundleLoader.from_dict(self.providers)
        self.settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.site_names = {
            str(number): str(name)
            for number, name in (self.settings.get("site_names") or {}).items()
        }
        self.temperature_threshold = float(
            self.settings.get("temperature_threshold_c", 20.0)
        )
        self.store_flow_metrics = bool(self.settings.get("store_flow_metrics", True))
        self.flow_metrics = {
            str(site): dict(values)
            for site, values in (self.settings.get("flow_metrics") or {}).items()
            if isinstance(values, dict)
        }
        self.days = int(self.settings.get("days", 14))
        self.bundle: DataBundle | None = None
        self.history_years = int(self.settings.get("history_years", 3))
        self.history_loading = False
        self._history_site: str | None = None
        self._history_token = 0
        self.map_radius = float(self.settings.get("map_radius", 0.5))
        self.map_years = int(self.settings.get("map_years", 2))
        self.map_loading = False
        self._map_site: str | None = None
        self._map_sites: list = []
        self._map_center: tuple[float, float] | None = None
        self._map_zoom = 10
        self._map_token = 0
        self._regional_token = 0
        self._regional_gauge = False
        self._token = 0
        self._busy = False
        self._alive = True
        self._results: queue.Queue = queue.Queue()
        self._drain_id: str | None = None

        self._build_window()
        self._drain_id = self.root.after(60, self._drain_results)
        if auto_load:
            self.root.after(120, lambda: self.load_site(str(self.settings.get("last_site", DEFAULT_SITE))))

    # -- window --------------------------------------------------------
    def _build_window(self) -> None:
        family = font_family(self.root)
        self.root.title(f"{APP_NAME} \u2014 stream gage & precipitation explorer")
        self.root.geometry("1180x900")
        self.root.minsize(1000, 720)
        apply_theme(self.root)

        menubar = tk.Menu(self.root)
        settings_menu = tk.Menu(menubar, tearoff=False)
        settings_menu.add_command(
            label="Reset settings to defaults\u2026", command=self.reset_settings
        )
        menubar.add_cascade(label="Settings", menu=settings_menu)
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="About StreamStudy", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menubar)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # -- header
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(20, 10, 16, 10))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        brand = ttk.Frame(header, style="Header.TFrame")
        brand.grid(row=0, column=0, sticky="w")
        tk.Label(
            brand, text=APP_NAME, bg=SURFACE, fg=TEXT, font=(family, 16, "bold")
        ).pack(anchor="w")
        tk.Label(
            brand,
            text="experimental  \u00b7  AI-built  \u00b7  USGS stream gages  \u00b7  NWS weather  \u00b7  rainfall",
            bg=SURFACE,
            fg=MUTED,
            font=(family, 9),
        ).pack(anchor="w")

        right_controls = ttk.Frame(header, style="Header.TFrame")
        right_controls.grid(row=0, column=2, sticky="e")
        self.days_var = tk.StringVar(value=f"{self.days} days")
        days_box = ttk.Combobox(
            right_controls,
            textvariable=self.days_var,
            width=8,
            state="readonly",
            values=[f"{days} days" for days in ALLOWED_DAYS],
        )
        days_box.pack(side="left", padx=4)
        days_box.bind("<<ComboboxSelected>>", self._on_days_changed)
        ttk.Button(right_controls, text="Refresh", command=self.refresh).pack(
            side="left", padx=(4, 0)
        )

        picker = ttk.Frame(header, style="Header.TFrame")
        picker.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        picker.columnconfigure(1, weight=1)
        ttk.Label(picker, text="USGS site", style="HeaderMuted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        last_site = str(self.settings.get("last_site", DEFAULT_SITE))
        self.site_var = tk.StringVar(value=self._site_label(last_site))
        self.site_combo = ttk.Combobox(
            picker,
            textvariable=self.site_var,
            width=70,
            values=self._recent_labels(),
        )
        self.site_combo.grid(row=0, column=1, sticky="ew")
        self.site_combo.bind("<Return>", lambda _event: self.reload())
        ttk.Button(
            picker, text="Load", style="Accent.TButton", command=self.reload
        ).grid(row=0, column=2, padx=(8, 0))

        self.title_label = tk.Label(
            header,
            text="Loading\u2026",
            bg=SURFACE,
            fg=TEXT,
            font=(family, 12, "bold"),
            anchor="w",
        )
        self.title_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.sub_label = tk.Label(
            header, text="", bg=SURFACE, fg=MUTED, font=(family, 9), anchor="w"
        )
        self.sub_label.grid(row=3, column=0, columnspan=2, sticky="w")
        self.fetched_label = tk.Label(
            header, text="", bg=SURFACE, fg=MUTED, font=(family, 8), anchor="e"
        )
        self.fetched_label.grid(row=2, column=2, rowspan=2, sticky="e", pady=(10, 0))

        # -- tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=(10, 6))
        self.home_view = HomeView(self.notebook, self)
        self.hydro_view = HydroView(self.notebook, self)
        self.sensors_view = SensorsView(self.notebook, self)
        self.temperature_view = TemperatureView(self.notebook, self)
        self.precip_view = PrecipView(self.notebook, self)
        self.response_view = ResponseView(self.notebook, self)
        self.map_view = MapView(self.notebook, self)
        self.forecast_view = ForecastView(self.notebook, self)
        self.sites_view = SitesView(self.notebook, self)
        for view, label in (
            (self.home_view, "Overview"),
            (self.hydro_view, "Hydrograph"),
            (self.sensors_view, "Sensors"),
            (self.temperature_view, "Temperature"),
            (self.precip_view, "Precipitation"),
            (self.response_view, "Rainfall \u2192 Flow"),
            (self.map_view, "Map & Correlation"),
            (self.forecast_view, "Forecast"),
            (self.sites_view, "Site finder"),
        ):
            self.notebook.add(view, text=label)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # -- footer
        footer = ttk.Frame(self.root, padding=(18, 6))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            footer, text="Starting\u2026", bg=BG, fg=MUTED, font=(family, 9), anchor="w"
        )
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(
            footer, mode="indeterminate", length=120, style="Status.Horizontal.TProgressbar"
        )
        self.progress.grid(row=0, column=1, padx=(0, 14))
        self.progress.grid_remove()
        ttk.Button(footer, text="About", command=self.show_about).grid(
            row=0, column=2, padx=(0, 12)
        )
        dots = ttk.Frame(footer)
        dots.grid(row=0, column=3, sticky="e")
        self.source_dots: dict[str, tk.Label] = {}
        for key, label in SOURCE_LABELS:
            widget = tk.Label(
                dots, text=f"\u25cf {label}", bg=BG, fg=MUTED, font=(family, 8)
            )
            widget.pack(side="left", padx=(10, 0))
            self.source_dots[key] = widget
        self.source_dots_widget = dots

        self.root.bind("<Control-r>", lambda _event: self.refresh())
        self.root.bind("<Control-l>", lambda _event: self.site_combo.focus_set())
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # -- public API ----------------------------------------------------
    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        self._alive = False
        if self._drain_id is not None:
            try:
                self.root.after_cancel(self._drain_id)
            except tk.TclError:  # pragma: no cover
                pass
            self._drain_id = None
        try:
            self.progress.stop()
        except tk.TclError:  # pragma: no cover
            pass
        self.settings["days"] = self.days
        save_settings(self.settings, self.settings_path)
        self.root.destroy()

    def load_site(self, site_number: str, days: int | None = None) -> None:
        number = parse_site_number(site_number)
        if not number:
            messagebox.showwarning(
                APP_NAME, "Enter a USGS site number, e.g. 0423205010.", parent=self.root
            )
            return
        if days is not None:
            self.days = int(days)
            self.days_var.set(f"{self.days} days")

        self._token += 1
        token = self._token
        self._set_busy(
            True,
            f"Loading USGS {number} \u2014 querying USGS NWIS, NWS, Open-Meteo and CoCoRaHS\u2026",
        )
        options = LoadOptions(
            days=self.days,
            coco_station=(self.settings.get("coco_station") or None),
        )

        def work() -> DataBundle:
            return self.loader.load(number, options)

        self.run_async(work, lambda bundle, error: self._finish_load(token, number, bundle, error))

    def reload(self) -> None:
        self.load_site(self.site_var.get())

    def refresh(self) -> None:
        clear = getattr(self.client, "clear_cache", None)
        if callable(clear):
            clear()
        self._history_site = None
        self._map_site = None
        site = self.bundle.site.number if self.bundle else self.site_var.get()
        self.load_site(site)

    def set_days(self, days: int) -> None:
        self.days = int(days)
        self.days_var.set(f"{self.days} days")
        if self.bundle is not None:
            self.load_site(self.bundle.site.number)

    def show_overview(self) -> None:
        self.notebook.select(self.home_view)

    def show_hydrograph(self) -> None:
        self.notebook.select(self.hydro_view)

    def show_precipitation(self) -> None:
        self.notebook.select(self.precip_view)

    def show_forecast(self) -> None:
        self.notebook.select(self.forecast_view)

    def show_site_finder(self) -> None:
        self.notebook.select(self.sites_view)

    def show_response(self) -> None:
        self.notebook.select(self.response_view)

    def _on_tab_changed(self, _event: tk.Event) -> None:
        selected = self.notebook.select()
        if selected == str(self.response_view):
            self._ensure_history()
        elif selected == str(self.map_view):
            self._ensure_map()


    def run_async(self, work, callback) -> None:
        """Run ``work()`` off the UI thread and invoke ``callback(result, error)``.

        Tk is not thread-safe, so workers only push results into a queue that
        the UI thread drains every 60 ms.
        """

        def runner() -> None:
            try:
                result, error = work(), None
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                result, error = None, exc
            self._results.put((callback, result, error))

        threading.Thread(target=runner, daemon=True).start()

    def _drain_results(self) -> None:
        try:
            while True:
                callback, result, error = self._results.get_nowait()
                callback(result, error)
        except queue.Empty:
            pass
        if self._alive:
            try:
                self._drain_id = self.root.after(60, self._drain_results)
            except tk.TclError:  # pragma: no cover - window already gone
                pass

    # -- internals -----------------------------------------------------
    def _on_days_changed(self, _event: tk.Event) -> None:
        try:
            days = int(self.days_var.get().split()[0])
        except (ValueError, IndexError):
            return
        self.set_days(days)

    def _finish_load(self, token: int, number: str, bundle, error) -> None:
        if token != self._token:
            return
        self._set_busy(False, "")
        if error is not None:
            self.set_status(f"Could not load USGS {number}: {error}", tone="bad")
            messagebox.showerror(
                APP_NAME, f"Could not load USGS site {number}.\n\n{error}", parent=self.root
            )
            return
        self.apply_bundle(bundle)

    # -- rainfall-runoff history ---------------------------------------
    def _ensure_history(self) -> None:
        if self.bundle is None:
            return
        self.response_view.render(self.bundle)
        if self._history_site == self.bundle.site.number or self.history_loading:
            return
        self.load_history()

    def load_history(self, years: int | None = None) -> None:
        if self.bundle is None:
            return
        if years is not None:
            self.history_years = max(1, min(int(years), 15))
        site = self.bundle.site
        self._history_token += 1
        token = self._history_token
        self.history_loading = True
        self._history_site = None
        self.response_view.render(self.bundle)
        coco = self.bundle.coco_station.identifier if self.bundle.coco_station else None
        span = self.history_years

        def work():
            return self.loader.load_history(site, years=span, coco_station=coco)

        self.run_async(
            work, lambda result, error: self._finish_history(token, result, error)
        )

    def _finish_history(self, token: int, result, error) -> None:
        if token != self._history_token:
            return
        self.history_loading = False
        if error is not None:
            self.set_status(f"History analysis failed: {error}", tone="bad")
            return
        if self.bundle is None:
            return
        self.bundle.history = result
        self._history_site = self.bundle.site.number
        self.settings["history_years"] = self.history_years
        save_settings(self.settings, self.settings_path)
        self.response_view.render(self.bundle)
        fit = result.fit
        if self.notebook.select() != str(self.map_view):
            if fit is not None:
                self.set_status(
                    f"Rainfall response: {fit.events} storms \u00b7 {fit.slope:,.0f} cfs/in "
                    f"\u00b7 lag {fit.lag_p50_hours:.0f} h \u00b7 {result.precip_source}",
                    tone="muted",
                )
            else:
                self.set_status(
                    f"Rainfall response: only {len(result.events)} usable storms in "
                    f"{self.history_years} years \u2014 try a longer history.",
                    tone="warn",
                )
        if self._map_sites and not self._regional_gauge:
            self.request_regional(force=True)

    # -- regional map and correlations ---------------------------------
    @staticmethod
    def _distance_km(first, second) -> float:
        mean_lat = math.radians((first.latitude + second.latitude) / 2.0)
        dx = (second.longitude - first.longitude) * 111.0 * math.cos(mean_lat)
        dy = (second.latitude - first.latitude) * 111.0
        return math.hypot(dx, dy)

    def _ensure_map(self) -> None:
        if self.bundle is None:
            return
        self.map_view.set_site(self.bundle.site)
        if self._map_site == self.bundle.site.number or self.map_loading:
            return
        self.request_map()

    def request_map(self, force: bool = False) -> None:
        if self.bundle is None:
            return
        site = self.bundle.site
        if not force and self._map_site == site.number:
            return
        self.map_view.show_map_loading()
        self._request_map_view(
            (site.latitude, site.longitude),
            zoom_for_radius(self.map_radius),
            rerun_regional=True,
        )

    def request_map_view(
        self, latitude: float, longitude: float, zoom: int, force: bool = False
    ) -> None:
        """Pan/zoom/resize callback: reload tiles and gages for the area."""
        center = (float(latitude), float(longitude))
        zoom = max(4, min(15, int(zoom)))
        if (
            not force
            and self._map_center is not None
            and abs(center[0] - self._map_center[0]) < 1e-5
            and abs(center[1] - self._map_center[1]) < 1e-5
            and zoom == self._map_zoom
        ):
            return
        self._request_map_view(center, zoom, rerun_regional=False)

    def recenter_map(self) -> None:
        self.request_map(force=True)

    def _request_map_view(
        self, center: tuple[float, float], zoom: int, *, rerun_regional: bool
    ) -> None:
        if self.bundle is None:
            return
        site = self.bundle.site
        self._map_token += 1
        token = self._map_token
        self.map_loading = True
        self._map_center = center
        self._map_zoom = zoom
        width, height = self.map_view.map_size()
        west, south, east, north = view_bbox(center, zoom, width, height)

        def work():
            sites = self.providers["usgs"].search_sites(
                bbox=(west, south, east, north), limit=250
            )
            ordered = []
            seen = set()
            for candidate in (site, *sites):
                if candidate.number in seen:
                    continue
                seen.add(candidate.number)
                ordered.append(candidate)
            tiles = fetch_tiles(
                self.client,
                tiles_for_bbox(west, south, east, north, zoom),
            )
            return ordered, tiles

        self.run_async(
            work,
            lambda result, error: self._finish_map(
                token, site, center, zoom, rerun_regional, result, error
            ),
        )

    def _finish_map(
        self,
        token: int,
        site,
        center: tuple[float, float],
        zoom: int,
        rerun_regional: bool,
        result,
        error,
    ) -> None:
        if token != self._map_token:
            return
        self.map_loading = False
        if error is not None:
            self.set_status(f"Map: {error}", tone="bad")
            return
        sites, tiles = result
        self._map_sites = list(sites)
        self._map_site = site.number
        self._map_center = center
        self._map_zoom = zoom
        self.map_view.set_map(center, zoom, self._map_sites, tiles, site.number)
        if rerun_regional:
            self.request_regional()

    def request_regional(self, force: bool = False) -> None:
        if not self._map_sites or self.bundle is None:
            return
        site = self.bundle.site
        chosen = sorted(
            self._map_sites,
            key=lambda candidate: self._distance_km(site, candidate),
        )[:6]
        if all(candidate.number != site.number for candidate in chosen):
            chosen[-1] = site
        self._regional_token += 1
        token = self._regional_token
        self.map_view.show_correlation_loading()
        history = self.bundle.history
        # Only pass a *gauge* record as an extra source; ERA5 is already the
        # regional series and would otherwise appear twice.
        gauge = None
        label = "CoCoRaHS gauge"
        if history and history.precip and not history.precip_source.startswith("Open-Meteo"):
            gauge = dict(history.precip)
            label = history.precip_source
        self._regional_gauge = gauge is not None
        years = self.map_years

        def work():
            return self.loader.load_regional(
                chosen,
                years=years,
                gauge_series=gauge,
                gauge_label=label,
                max_gages=6,
            )

        self.run_async(
            work, lambda result, error: self._finish_regional(token, result, error)
        )

    def _finish_regional(self, token: int, result, error) -> None:
        if token != self._regional_token:
            return
        if error is not None:
            self.set_status(f"Correlation: {error}", tone="bad")
            return
        self.map_view.set_correlation(result)
        if self.notebook.select() == str(self.map_view):
            tail = ""
            strongest = result.strongest_pairs(1)
            if strongest:
                first, second, correlation = strongest[0]
                tail = (
                    f" \u00b7 strongest {result.short_label(first)}"
                    f"\u2194{result.short_label(second)} r {correlation.r:+.2f}"
                )
            self.set_status(
                f"Regional: {len(result.flow)} gages \u00b7 "
                f"{len(result.rain_pairs)} rain pairs{tail}",
                tone="muted",
            )

    def set_map_radius(self, radius: float) -> None:
        self.map_radius = float(radius)
        self.settings["map_radius"] = self.map_radius
        save_settings(self.settings, self.settings_path)
        self._map_site = None
        self.request_map(force=True)

    def set_temperature_threshold(self, value: float) -> None:
        self.temperature_threshold = max(0.0, min(40.0, float(value)))
        self.settings["temperature_threshold_c"] = self.temperature_threshold
        save_settings(self.settings, self.settings_path)
        if self.bundle is not None:
            self.temperature_view.render(self.bundle)

    def set_store_flow_metrics(self, enabled: bool) -> None:
        self.store_flow_metrics = bool(enabled)
        self.settings["store_flow_metrics"] = self.store_flow_metrics
        save_settings(self.settings, self.settings_path)

    def save_flow_metrics(self, site_number: str, metrics: dict) -> None:
        if not self.store_flow_metrics:
            return
        cleaned = {
            key: round(value, 2) if isinstance(value, float) else value
            for key, value in metrics.items()
        }
        if self.flow_metrics.get(site_number) == cleaned:
            return
        self.flow_metrics[site_number] = cleaned
        self.settings["flow_metrics"] = dict(self.flow_metrics)
        save_settings(self.settings, self.settings_path)

    def set_map_years(self, years: int) -> None:
        self.map_years = int(years)
        self.settings["map_years"] = self.map_years
        save_settings(self.settings, self.settings_path)
        self.request_regional(force=True)

    def show_map(self) -> None:
        self.notebook.select(self.map_view)

    def rank_nearby(self) -> None:
        """Find the most useful nearby gage (data quality + correlations)."""
        if self.bundle is None:
            return
        site = self.bundle.site
        radius = max(0.5, self.map_radius)
        bbox = (
            site.longitude - radius,
            site.latitude - radius,
            site.longitude + radius,
            site.latitude + radius,
        )
        rain = (
            dict(self.bundle.history.precip)
            if self.bundle.history and self.bundle.history.precip
            else {}
        )

        def work():
            sites = self.providers["usgs"].search_sites(bbox=bbox, limit=80)
            candidates = [
                candidate for candidate in sites if candidate.number != site.number
            ]
            candidates.sort(key=lambda candidate: self._distance_km(site, candidate))
            if not candidates:
                return None
            return self.loader.rank_sites(
                candidates[:5], years=2, rain=rain, base_site=site, max_sites=5
            )

        self.set_status("Ranking nearby gages by data value\u2026", tone="accent")
        self.run_async(work, self._finish_rank)

    def _finish_rank(self, result, error) -> None:
        if error is not None:
            self.set_status(f"Ranking failed: {error}", tone="bad")
            return
        if result is None or not result.scores:
            self.set_status("No nearby gages with daily flow were found.", tone="warn")
            return
        self.sites_view.show_ranking(result)
        hub = result.hub
        if hub is not None:
            self.set_status(
                f"Suggested hub: {hub.site.number} \u2014 {hub.reasons}", tone="good"
            )

    def show_about(self) -> None:
        messagebox.showinfo(f"About {APP_NAME}", ABOUT_TEXT, parent=self.root)

    def reset_settings(self) -> None:
        if not messagebox.askyesno(
            "Reset settings",
            "Reset all settings to defaults?\n\nRecent sites and saved flow metrics "
            "will be cleared; the current site stays loaded.",
            parent=self.root,
        ):
            return
        current = self.bundle.site if self.bundle else None
        self.settings = dict(DEFAULTS)
        if current is not None:
            self.settings["last_site"] = current.number
            self.settings["recent_sites"] = [current.number]
            self.settings["site_names"] = {current.number: current.name}
        self.site_names = dict(self.settings["site_names"])
        self.temperature_threshold = float(DEFAULTS["temperature_threshold_c"])
        self.store_flow_metrics = bool(DEFAULTS["store_flow_metrics"])
        self.flow_metrics = {}
        self.history_years = int(DEFAULTS["history_years"])
        self.map_radius = float(DEFAULTS["map_radius"])
        self.map_years = int(DEFAULTS["map_years"])
        self.days = int(DEFAULTS["days"])
        save_settings(self.settings, self.settings_path)

        self.days_var.set(f"{self.days} days")
        self.site_combo.configure(values=self._recent_labels())
        if current is not None:
            self.site_var.set(self._site_label(current.number))
        self.map_view.years_var.set(f"{self.map_years} years")
        self.map_view.radius_var.set(self.map_view._label_for(self.map_radius))
        self.response_view.metrics_var.set(self.store_flow_metrics)
        self.temperature_view.threshold_var.set(f"{self.temperature_threshold:g}")
        if self.bundle is not None:
            self.temperature_view.render(self.bundle)
            self.load_site(current.number if current else self.bundle.site.number)
        else:
            self.set_status("Settings reset to defaults.", tone="good")

    # -- site picker ---------------------------------------------------
    def _site_label(self, number: str) -> str:
        name = self.site_names.get(number, "")
        return f"{number} \u2014 {name}" if name else number

    def _recent_labels(self) -> list[str]:
        return [
            self._site_label(str(number))
            for number in self.settings.get("recent_sites", [])
        ]

    def apply_bundle(self, bundle: DataBundle) -> None:
        self.bundle = bundle
        site = bundle.site

        self.title_label.configure(text=site.name or f"USGS {site.number}")
        meta = [f"USGS {site.number}", site.coordinates]
        if site.state:
            meta.append(site.state)
        if site.site_type:
            meta.append(site.site_type)
        if site.drainage_area_sq_mi:
            meta.append(f"{site.drainage_area_sq_mi:,.1f} mi\u00b2 drainage")
        self.sub_label.configure(text="  \u00b7  ".join(meta))

        stamp = bundle.fetched_at.astimezone().strftime("%b %d, %H:%M")
        warning = f"  \u00b7  {len(bundle.errors)} warning(s)" if bundle.errors else ""
        self.fetched_label.configure(text=f"Updated {stamp}{warning}")

        if site.name:
            self.site_names[site.number] = site.name
        self.settings["site_names"] = dict(self.site_names)
        self.site_var.set(self._site_label(site.number))
        for view in (
            self.home_view,
            self.hydro_view,
            self.sensors_view,
            self.temperature_view,
            self.precip_view,
            self.forecast_view,
        ):
            view.render(bundle)
        self._update_source_dots(bundle)

        self.set_status(
            f"Loaded USGS {site.number} \u00b7 {bundle.ok_sources}/4 sources \u00b7 "
            f"{self.days}-day window",
            tone="warn" if bundle.errors else "muted",
        )

        self.settings = remember_site(self.settings, site.number)
        self.settings["days"] = self.days
        self.settings["site_names"] = dict(self.site_names)
        self.site_combo.configure(values=self._recent_labels())
        save_settings(self.settings, self.settings_path)
        self._ensure_history()
        self._ensure_map()

    def _update_source_dots(self, bundle: DataBundle) -> None:
        availability = {
            "usgs": bool(bundle.usgs),
            "nws": bool(bundle.nws_station and (bundle.nws_daily or bundle.nws_precip)),
            "openmeteo": bool(bundle.openmeteo_hourly or bundle.openmeteo_daily),
            "cocorahs": bool(bundle.coco_daily),
            "mmw": bool(bundle.mmw_series),
        }
        for key, widget in self.source_dots.items():
            widget.configure(fg=GOOD if availability.get(key) else MUTED)

    def _set_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        if busy:
            self.progress.grid()
            self.progress.start(14)
            self.set_status(message, tone="accent")
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def set_status(self, message: str, tone: str = "muted") -> None:
        self.status_label.configure(text=message, fg=STATUS_COLORS.get(tone, MUTED))
