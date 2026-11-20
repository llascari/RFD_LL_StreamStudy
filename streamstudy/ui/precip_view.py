"""Precipitation tab: compare gauges and models day by day."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta, timezone
from tkinter import ttk

from ..analysis import bundle_precip_sources, precip_table, totals_for_window
from ..models import DataBundle
from .charts import ChartCanvas, ChartSeries
from .theme import SERIES_COLORS
from .widgets import clear_tree, treeview

LABELS = {
    "usgs": "USGS",
    "cocorahs": "CoCoRaHS",
    "openmeteo": "Open-Meteo",
    "nws": "NWS obs",
}


class PrecipView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self._sources: dict[str, dict] = {}
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Precipitation", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.caption = ttk.Label(header, text="", style="Muted.TLabel")
        self.caption.grid(row=1, column=0, sticky="w", pady=(2, 0))

        summary_frame, self.summary = treeview(
            self,
            {
                "source": ("Source", 120, "w"),
                "station": ("Station / grid", 320, "w"),
                "day": ("Last 24 h", 90, "e"),
                "week": ("Last 7 days", 100, "e"),
                "window": ("Window total", 100, "e"),
            },
            height=4,
        )
        summary_frame.grid(row=1, column=0, sticky="ew")
        self.summary.column("station", stretch=False)

        body = ttk.Frame(self)
        body.grid(row=2, column=0, sticky="nsew", pady=(10, 4))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        self.chart = ChartCanvas(
            body,
            height=240,
            title="Daily precipitation",
            unit="inches",
            empty_text="No precipitation data available yet",
        )
        self.chart.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        table_frame, self.table = treeview(
            body, {"day": ("Day", 110, "w")}, height=10
        )
        table_frame.grid(row=0, column=1, sticky="nsew")

        self.note = ttk.Label(
            self,
            text="CoCoRaHS and USGS gauge totals are 24-hour accumulations at the observer's reading time; "
            "Open-Meteo is a gridded model, and NWS values are summed from hourly ASOS reports. "
            "Missing cells mean the source had no report.",
            style="Muted.TLabel",
            wraplength=950,
            justify="left",
        )
        self.note.grid(row=3, column=0, sticky="w", pady=(8, 0))

    # -- rendering -----------------------------------------------------
    def render(self, bundle: DataBundle) -> None:
        sources = bundle_precip_sources(bundle)
        self._sources = sources
        window = max(7, min(self.app.days, 21))
        self.caption.configure(
            text=f"{bundle.site.name}  \u00b7  daily rainfall in inches  \u00b7  last {window} days"
        )

        clear_tree(self.summary)
        if not sources:
            self.summary.insert(
                "", "end", values=("\u2014", "No precipitation source returned data", "", "", "")
            )
        for key, daily in sources.items():
            self.summary.insert(
                "",
                "end",
                values=(
                    LABELS[key],
                    self._station_label(bundle, key),
                    f"{totals_for_window(daily, 1):.2f}",
                    f"{totals_for_window(daily, 7):.2f}",
                    f"{totals_for_window(daily, window):.2f}",
                ),
            )

        end = date.today()
        start = end - timedelta(days=window - 1)
        bars = []
        for key, daily in sources.items():
            points = [
                (datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc), inches)
                for day, inches in sorted(daily.items())
                if start <= day <= end
            ]
            bars.append(
                ChartSeries(LABELS[key], points, SERIES_COLORS[key], kind="bar")
            )
        self.chart.set_series(
            bars,
            title="Daily precipitation",
            unit="inches",
            empty_text="No precipitation source returned data",
        )

        self._fill_table(sources, window)

    def _station_label(self, bundle: DataBundle, key: str) -> str:
        if key == "cocorahs" and bundle.coco_station:
            station = bundle.coco_station
            suffix = (
                f" ({station.distance_km:.1f} km)"
                if station.distance_km == station.distance_km
                else ""
            )
            return f"{station.identifier} \u2014 {station.name}{suffix}"
        if key == "nws" and bundle.nws_station:
            return f"{bundle.nws_station.identifier} \u2014 {bundle.nws_station.name}"
        if key == "usgs":
            return f"USGS {bundle.site.number}"
        if key == "openmeteo":
            return bundle.openmeteo_zone or "model grid"
        return "\u2014"

    def _fill_table(self, sources: dict[str, dict], window: int) -> None:
        keys = list(sources)
        columns = ["day"] + keys
        self.table.configure(columns=columns, show="headings")
        self.table.heading("day", text="Day")
        self.table.column("day", width=130, anchor="w", stretch=False)
        for key in keys:
            self.table.heading(key, text=LABELS[key])
            self.table.column(key, width=100, anchor="e", stretch=False)
        clear_tree(self.table)

        rows = precip_table(sources, window)
        for day, values in rows:
            cells = [day.strftime("%a %b %d")]
            for key in keys:
                value = values.get(key)
                cells.append(f"{value:.2f}" if value is not None else "\u2014")
            self.table.insert("", "end", values=tuple(cells))
