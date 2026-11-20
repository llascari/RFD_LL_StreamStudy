"""StreamStudy application shell: header, tabs, background loading."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .http import HttpClient
from .loader import BundleLoader, LoadOptions
from .models import DataBundle
from .providers import build_providers
from .settings import (
    ALLOWED_DAYS,
    DEFAULT_SITE,
    load_settings,
    remember_site,
    save_settings,
)
from .ui.forecast_view import ForecastView
from .ui.home_view import HomeView
from .ui.hydro_view import HydroView
from .ui.precip_view import PrecipView
from .ui.sites_view import SitesView
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
)
STATUS_COLORS = {"muted": MUTED, "good": GOOD, "warn": WARN, "bad": BAD, "accent": ACCENT}


def normalize_site(value: str) -> str:
    text = (value or "").strip().upper()
    for prefix in ("USGS-", "USGS "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.strip()


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
        self.days = int(self.settings.get("days", 14))
        self.bundle: DataBundle | None = None
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
        self.root.geometry("1180x820")
        self.root.minsize(980, 700)
        apply_theme(self.root)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # -- header
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(20, 12, 16, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        brand = ttk.Frame(header, style="Header.TFrame")
        brand.grid(row=0, column=0, sticky="w")
        tk.Label(
            brand, text=APP_NAME, bg=SURFACE, fg=TEXT, font=(family, 16, "bold")
        ).pack(anchor="w")
        tk.Label(
            brand,
            text="USGS stream gages  \u00b7  NWS weather  \u00b7  rainfall",
            bg=SURFACE,
            fg=MUTED,
            font=(family, 9),
        ).pack(anchor="w")

        controls = ttk.Frame(header, style="Header.TFrame")
        controls.grid(row=0, column=2, sticky="e")
        ttk.Label(controls, text="USGS site", style="HeaderMuted.TLabel").pack(
            side="left", padx=(0, 6)
        )
        self.site_var = tk.StringVar(value=str(self.settings.get("last_site", DEFAULT_SITE)))
        self.site_combo = ttk.Combobox(
            controls,
            textvariable=self.site_var,
            width=14,
            values=self.settings.get("recent_sites", []),
        )
        self.site_combo.pack(side="left")
        self.site_combo.bind("<Return>", lambda _event: self.reload())
        ttk.Button(
            controls, text="Load", style="Accent.TButton", command=self.reload
        ).pack(side="left", padx=(8, 4))

        self.days_var = tk.StringVar(value=f"{self.days} days")
        days_box = ttk.Combobox(
            controls,
            textvariable=self.days_var,
            width=8,
            state="readonly",
            values=[f"{days} days" for days in ALLOWED_DAYS],
        )
        days_box.pack(side="left", padx=4)
        days_box.bind("<<ComboboxSelected>>", self._on_days_changed)
        ttk.Button(controls, text="Refresh", command=self.refresh).pack(
            side="left", padx=(4, 0)
        )

        self.title_label = tk.Label(
            header,
            text="Loading\u2026",
            bg=SURFACE,
            fg=TEXT,
            font=(family, 12, "bold"),
            anchor="w",
        )
        self.title_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.sub_label = tk.Label(
            header, text="", bg=SURFACE, fg=MUTED, font=(family, 9), anchor="w"
        )
        self.sub_label.grid(row=2, column=0, columnspan=2, sticky="w")
        self.fetched_label = tk.Label(
            header, text="", bg=SURFACE, fg=MUTED, font=(family, 8), anchor="e"
        )
        self.fetched_label.grid(row=1, column=2, rowspan=2, sticky="e", pady=(10, 0))

        # -- tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=(10, 6))
        self.home_view = HomeView(self.notebook, self)
        self.hydro_view = HydroView(self.notebook, self)
        self.precip_view = PrecipView(self.notebook, self)
        self.forecast_view = ForecastView(self.notebook, self)
        self.sites_view = SitesView(self.notebook, self)
        for view, label in (
            (self.home_view, "Overview"),
            (self.hydro_view, "Hydrograph"),
            (self.precip_view, "Precipitation"),
            (self.forecast_view, "Forecast"),
            (self.sites_view, "Site finder"),
        ):
            self.notebook.add(view, text=label)

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
        dots = ttk.Frame(footer)
        dots.grid(row=0, column=2, sticky="e")
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
        self.settings["days"] = self.days
        save_settings(self.settings, self.settings_path)
        self.root.destroy()

    def load_site(self, site_number: str, days: int | None = None) -> None:
        number = normalize_site(site_number)
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

        self.site_var.set(site.number)
        for view in (self.home_view, self.hydro_view, self.precip_view, self.forecast_view):
            view.render(bundle)
        self._update_source_dots(bundle)

        self.set_status(
            f"Loaded USGS {site.number} \u00b7 {bundle.ok_sources}/4 sources \u00b7 "
            f"{self.days}-day window",
            tone="warn" if bundle.errors else "muted",
        )

        self.settings = remember_site(self.settings, site.number)
        self.settings["days"] = self.days
        self.site_combo.configure(values=self.settings["recent_sites"])
        save_settings(self.settings, self.settings_path)

    def _update_source_dots(self, bundle: DataBundle) -> None:
        availability = {
            "usgs": bool(bundle.usgs),
            "nws": bool(bundle.nws_station and (bundle.nws_daily or bundle.nws_precip)),
            "openmeteo": bool(bundle.openmeteo_hourly or bundle.openmeteo_daily),
            "cocorahs": bool(bundle.coco_daily),
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
