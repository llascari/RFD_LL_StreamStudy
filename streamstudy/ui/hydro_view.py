"""Hydrograph tab: discharge and gage height for the selected window."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk

from ..analysis import format_value, series_stats, trend_label, trend_per_hour
from ..models import DataBundle, Series
from .charts import ChartCanvas, ChartSeries
from .theme import SERIES_COLORS


class HydroView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self.discharge: Series | None = None
        self.gage: Series | None = None
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(4, weight=2)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Hydrograph", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.caption = ttk.Label(header, text="", style="Muted.TLabel")
        self.caption.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.log_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            header,
            text="Log scale (discharge)",
            variable=self.log_var,
            command=self._apply_scale,
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        self.discharge_chart = ChartCanvas(
            self,
            height=260,
            title="Discharge",
            empty_text="No discharge data reported for this site",
        )
        self.discharge_chart.grid(row=1, column=0, sticky="nsew")

        self.discharge_stats = ttk.Label(self, text="", style="Muted.TLabel")
        self.discharge_stats.grid(row=2, column=0, sticky="w", pady=(4, 10))

        self.gage_chart = ChartCanvas(
            self,
            height=190,
            title="Gage height",
            empty_text="No gage-height data reported for this site",
        )
        self.gage_chart.grid(row=4, column=0, sticky="nsew")

        self.gage_stats = ttk.Label(self, text="", style="Muted.TLabel")
        self.gage_stats.grid(row=5, column=0, sticky="w", pady=(4, 0))

    # -- rendering -----------------------------------------------------
    def render(self, bundle: DataBundle) -> None:
        self.discharge = bundle.usgs.get("00060")
        self.gage = bundle.usgs.get("00065")
        self.caption.configure(
            text=f"{bundle.site.name}  \u00b7  last {self.app.days} days  \u00b7  instant values"
        )
        self._update_charts()

    def _points(self, series: Series | None) -> list[tuple[datetime, float]]:
        if series is None:
            return []
        return [(sample.time, float(sample.value)) for sample in series.valid]

    def _update_charts(self) -> None:
        if self.discharge and self.discharge.valid:
            self.discharge_chart.set_series(
                [
                    ChartSeries(
                        "Discharge",
                        self._points(self.discharge),
                        SERIES_COLORS["discharge"],
                    )
                ],
                title="Discharge",
                unit=self.discharge.units,
            )
            self.discharge_stats.configure(text=self._stats_text(self.discharge))
        else:
            self.discharge_chart.set_series([], title="Discharge", unit="")
            self.discharge_stats.configure(text="")

        if self.gage and self.gage.valid:
            self.gage_chart.set_series(
                [
                    ChartSeries(
                        "Gage height",
                        self._points(self.gage),
                        SERIES_COLORS["gage"],
                    )
                ],
                title="Gage height",
                unit=self.gage.units,
            )
            self.gage_stats.configure(text=self._stats_text(self.gage))
        else:
            self.gage_chart.set_series([], title="Gage height", unit="")
            self.gage_stats.configure(text="")

        self._apply_scale()

    def _apply_scale(self) -> None:
        self.discharge_chart.set_log(self.log_var.get())

    def _stats_text(self, series: Series) -> str:
        stats = series_stats(series)
        if stats is None:
            return ""
        latest = series.valid[-1]
        peak = max(series.valid, key=lambda sample: sample.value)
        rate = trend_per_hour(series)
        parts = [
            f"Latest {format_value(stats.latest, 2)} {series.units}",
            f"median {format_value(stats.median, 2)}",
            f"range {format_value(stats.minimum, 2)}\u2013{format_value(stats.maximum, 2)}",
            f"peak {format_value(peak.value, 2)} on {peak.time.astimezone():%b %d %H:%M}",
            trend_label(rate, series.units),
            f"{stats.count} readings",
        ]
        if series.provisional:
            parts.append("provisional")
        return "  \u00b7  ".join(parts)
