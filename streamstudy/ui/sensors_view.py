"""Sensors tab: nearby Monitor My Watershed / EnviroDIY stations.

These stations usually publish water temperature and a *relative* water depth
(not an absolute stage, no flow), so the tab compares them with the USGS gage
rather than presenting the depth as a datum-referenced value.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from ..analysis import daily_means, format_value, trend_label, trend_per_hour
from ..correlation import lagged_correlation
from ..models import DataBundle, utc_now
from .charts import ChartCanvas, ChartSeries
from .theme import SERIES_COLORS
from .widgets import StatCard


class SensorsView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self._url = ""
        self._build()

    # -- construction --------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Sensors", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.caption = ttk.Label(
            header,
            text="Looking for nearby EnviroDIY stations\u2026",
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        )
        self.caption.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.link = ttk.Label(header, text="", style="Link.TLabel", cursor="hand2")
        self.link.grid(row=0, column=1, rowspan=2, sticky="e")
        self.link.bind("<Button-1>", self._open_site)

        cards = ttk.Frame(self)
        cards.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(4):
            cards.columnconfigure(column, weight=1, uniform="sensors")
        self.temp_card = StatCard(cards, "Water temperature", accent=SERIES_COLORS["temperature"])
        self.depth_card = StatCard(cards, "Relative water depth", accent=SERIES_COLORS["gage"])
        self.cond_card = StatCard(cards, "Specific conductance")
        self.fresh_card = StatCard(cards, "Last report")
        for index, card in enumerate(
            (self.temp_card, self.depth_card, self.cond_card, self.fresh_card)
        ):
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 10) if index < 3 else 0)

        body = ttk.Frame(self)
        body.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        body.columnconfigure(0, weight=3, uniform="sensors")
        body.columnconfigure(1, weight=2, uniform="sensors")
        body.rowconfigure(0, weight=1)

        charts = ttk.Frame(body)
        charts.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        charts.columnconfigure(0, weight=1)
        charts.rowconfigure(0, weight=1)
        charts.rowconfigure(1, weight=1)

        self.depth_chart = ChartCanvas(
            charts,
            height=180,
            title="Relative water depth",
            empty_text="No water-depth sensor reported",
        )
        self.depth_chart.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.temp_chart = ChartCanvas(
            charts,
            height=180,
            title="Water temperature",
            empty_text="No temperature sensor reported",
        )
        self.temp_chart.grid(row=1, column=0, sticky="nsew")

        comparison = ttk.Frame(body, style="Card.TFrame", padding=(14, 12))
        comparison.grid(row=0, column=1, sticky="nsew")
        comparison.columnconfigure(0, weight=1)
        ttk.Label(
            comparison, text="Compared with the USGS gage", style="Card.TLabel",
            font=("TkDefaultFont", 11, "bold")
        ).grid(row=0, column=0, sticky="w")
        self.comparison_var = tk.StringVar(value="")
        ttk.Label(
            comparison,
            textvariable=self.comparison_var,
            style="MutedCard.TLabel",
            wraplength=360,
            justify="left",
        ).grid(row=1, column=0, sticky="nw", pady=(8, 0))
        ttk.Label(
            comparison,
            text="Daily means, best lag within \u00b12 days. Depth is relative to the sensor: "
            "offsets and datum differences are not modelled, so compare shapes and timing, "
            "not absolute levels.",
            style="MutedCard.TLabel",
            wraplength=360,
            justify="left",
        ).grid(row=2, column=0, sticky="sw", pady=(14, 0))

        for row in range(3):
            comparison.rowconfigure(row, weight=1 if row == 2 else 0)

        self.note = ttk.Label(
            self,
            text="Monitor My Watershed is WikiWatershed's public ODM2 portal for EnviroDIY sensors. "
            "Stations report at their own intervals and are provisional; temperature is water "
            "temperature, depth is relative (in or mm as reported).",
            style="Muted.TLabel",
            wraplength=1000,
            justify="left",
        )
        self.note.grid(row=3, column=0, sticky="w", pady=(8, 0))

    # -- rendering -----------------------------------------------------
    def render(self, bundle: DataBundle) -> None:
        site = bundle.mmw_site
        series = bundle.mmw_series or {}
        if site is None or not series:
            self._clear(
                "No Monitor My Watershed sensors within 60 km of this gage."
                if site is None
                else f"{site.name} has no usable sensor series in this window."
            )
            return

        distance = (
            f"  \u00b7  {site.distance_km:.1f} km"
            if site.distance_km == site.distance_km
            else ""
        )
        organization = f"  \u00b7  {site.organization}" if site.organization else ""
        extra = ""
        others = [station.name for station in bundle.mmw_sites[1:]]
        if others:
            extra = "  \u00b7  plus " + ", ".join(others)
        self.caption.configure(
            text=f"{site.name} ({site.identifier}){distance}{organization}{extra}"
        )
        self._url = site.url
        self.link.configure(text="Open on Monitor My Watershed  \u2197")

        depth = series.get("depth")
        temperature = series.get("temperature")
        conductance = series.get("conductance")

        self._render_card(self.depth_card, depth, note="relative")
        self._render_card(self.temp_card, temperature)
        if conductance is not None and conductance.latest is not None:
            self.cond_card.set(
                format_value(conductance.latest.value, 0),
                conductance.units,
                trend_label(trend_per_hour(conductance), conductance.units),
            )
        else:
            self.cond_card.set("\u2014", "", "not reported")

        latest_times = [s.latest.time for s in series.values() if s.latest is not None]
        if latest_times:
            age = utc_now() - max(latest_times)
            minutes = int(age.total_seconds() // 60)
            if minutes < 90:
                label = f"{minutes} min ago"
            elif minutes < 48 * 60:
                label = f"{minutes / 60:.1f} h ago"
            else:
                label = f"{minutes / 1440:.1f} d ago"
            self.fresh_card.set(label, "", f"{len(series)} series")
        else:
            self.fresh_card.set("\u2014", "", "no timestamps")

        if depth is not None:
            self.depth_chart.set_series(
                [
                    ChartSeries(
                        "Relative depth",
                        [(sample.time, float(sample.value)) for sample in depth.valid],
                        SERIES_COLORS["gage"],
                    )
                ],
                title="Relative water depth",
                unit=depth.units,
            )
        else:
            self.depth_chart.set_series([], title="Relative water depth", unit="")

        if temperature is not None:
            self.temp_chart.set_series(
                [
                    ChartSeries(
                        "Water temperature",
                        [(sample.time, float(sample.value)) for sample in temperature.valid],
                        SERIES_COLORS["temperature"],
                    )
                ],
                title="Water temperature",
                unit=temperature.units,
            )
        else:
            self.temp_chart.set_series([], title="Water temperature", unit="")

        self.comparison_var.set(self._comparison(bundle, series))

    def _render_card(self, card: StatCard, series, *, note: str = "") -> None:
        if series is None or series.latest is None:
            card.set("\u2014", "", "not reported")
            return
        if self._is_constant(series):
            card.set(
                format_value(series.latest.value, 2),
                series.units,
                "constant \u2014 sensor may be stuck",
                tone="warn",
            )
            return
        detail = trend_label(trend_per_hour(series), series.units)
        if note:
            detail = f"{detail}  \u00b7  {note}"
        card.set(format_value(series.latest.value, 2), series.units, detail)

    @staticmethod
    def _is_constant(series) -> bool:
        values = [sample.value for sample in series.valid]
        if len(values) < 3:
            return False
        return max(values) - min(values) < 1e-9

    def _comparison(self, bundle: DataBundle, series: dict) -> str:
        rows: list[str] = []

        def add(label: str, sensor_series, usgs_series, *, logarithmic: bool) -> None:
            if sensor_series is None or usgs_series is None:
                return
            if self._is_constant(sensor_series):
                rows.append(f"{label}: no variation in the sensor record")
                return
            correlation = lagged_correlation(
                daily_means(sensor_series.samples),
                daily_means(usgs_series.samples),
                max_lag=2,
                min_pairs=5,
                logarithmic=logarithmic,
            )
            if correlation is None:
                return
            rows.append(
                f"{label}: r {correlation.r:+.2f} at {correlation.lag_days:+d} d "
                f"(n {correlation.n})"
            )

        add(
            "Depth \u2194 USGS gage height",
            series.get("depth"),
            bundle.usgs.get("00065"),
            logarithmic=True,
        )
        add(
            "Depth \u2194 USGS discharge",
            series.get("depth"),
            bundle.usgs.get("00060"),
            logarithmic=True,
        )
        add(
            "Temperature \u2194 USGS water temp",
            series.get("temperature"),
            bundle.usgs.get("00010"),
            logarithmic=False,
        )
        return "\n".join(rows) if rows else "Not enough overlapping daily values yet."

    def _clear(self, message: str) -> None:
        self.caption.configure(text=message)
        self.link.configure(text="")
        self._url = ""
        for card in (self.temp_card, self.depth_card, self.cond_card, self.fresh_card):
            card.set("\u2014", "", "")
        self.depth_chart.set_series([], empty_text=message)
        self.temp_chart.set_series([], empty_text=message)
        self.comparison_var.set("")

    def _open_site(self, _event: tk.Event) -> None:
        if self._url:
            webbrowser.open(self._url)
