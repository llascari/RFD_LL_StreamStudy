"""Forecast tab: official NWS forecast plus modelled hourly rainfall."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta, timezone
from tkinter import ttk

from ..analysis import mm_to_inches
from ..models import DataBundle
from .charts import ChartCanvas, ChartSeries
from .theme import SERIES_COLORS, SURFACE, TEXT
from .widgets import clear_tree, treeview


class ForecastView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Forecast", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.caption = ttk.Label(
            header, text="", style="Muted.TLabel", wraplength=980, justify="left"
        )
        self.caption.grid(row=1, column=0, sticky="w", pady=(2, 0))

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3, uniform="split")
        body.columnconfigure(1, weight=2, uniform="split")
        body.rowconfigure(0, weight=1)

        tree_frame, self.tree = treeview(
            body,
            {
                "period": ("Period", 120, "w"),
                "temp": ("Temp", 70, "e"),
                "pop": ("Precip", 70, "e"),
                "outlook": ("Outlook", 220, "w"),
            },
            height=8,
        )
        tree_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.detail = tk.Text(
            body,
            height=8,
            wrap="word",
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            font=("TkDefaultFont", 9),
        )
        self.detail.grid(row=0, column=1, sticky="nsew")
        self.detail.configure(state="disabled")

        self.chart = ChartCanvas(
            self,
            height=170,
            title="Modelled precipitation, next 48 hours",
            unit="inches",
            empty_text="No hourly precipitation forecast available",
        )
        self.chart.grid(row=2, column=0, sticky="ew", pady=(10, 4))

        self.note = ttk.Label(
            self,
            text="Forecast periods and the 6-hourly precipitation bars come from the National Weather Service "
            "(api.weather.gov quantitative precipitation forecast). When NWS QPF is unavailable, "
            "Open-Meteo's hourly model is shown instead.",
            style="Muted.TLabel",
            wraplength=950,
            justify="left",
        )
        self.note.grid(row=3, column=0, sticky="w", pady=(4, 0))

    # -- rendering -----------------------------------------------------
    def render(self, bundle: DataBundle) -> None:
        station = bundle.nws_station
        caption = bundle.site.name
        if station is not None:
            caption += f"  \u00b7  NWS {station.identifier} \u2014 {station.name}"
        self.caption.configure(text=caption)

        clear_tree(self.tree)
        for period in bundle.nws_daily:
            temperature = (
                f"{period.temperature:.0f}{period.temperature_unit}"
                if period.temperature is not None
                else "\u2014"
            )
            probability = (
                f"{period.precip_probability}%"
                if period.precip_probability is not None
                else "\u2014"
            )
            self.tree.insert(
                "", "end", values=(period.name, temperature, probability, period.short)
            )
        if not bundle.nws_daily:
            self.tree.insert("", "end", values=("\u2014", "", "", "Forecast unavailable"))

        details = [period.detailed for period in bundle.nws_daily if period.detailed][:3]
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n\n".join(details) or "No detailed forecast available.")
        self.detail.configure(state="disabled")

        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=54)
        qpf = [
            (moment, amount)
            for moment, amount in bundle.nws_qpf
            if now - timedelta(hours=6) <= moment <= horizon
        ]
        modelled = [
            (moment, mm_to_inches(amount))
            for moment, amount, _probability in bundle.openmeteo_hourly
            if now - timedelta(hours=1) <= moment <= now + timedelta(hours=48)
        ]
        probabilities = [
            probability
            for moment, _amount, probability in bundle.openmeteo_hourly
            if now <= moment <= now + timedelta(hours=48) and probability is not None
        ]

        if any(amount > 0 for _moment, amount in qpf):
            series = [ChartSeries("NWS QPF", qpf, SERIES_COLORS["nws"], kind="bar")]
            title = "NWS precipitation forecast, next 48 hours"
        elif any(amount > 0 for _moment, amount in modelled):
            series = [
                ChartSeries("Open-Meteo", modelled, SERIES_COLORS["openmeteo"], kind="bar")
            ]
            title = "Modelled precipitation, next 48 hours"
        else:
            series = []
            title = "Precipitation forecast, next 48 hours"

        self.chart.set_series(
            series,
            title=title,
            unit="inches",
            empty_text="No precipitation expected in the next 48 hours",
        )

        notes = [f"modelled 48 h total {sum(value for _m, value in modelled):.2f} in"]
        if probabilities:
            notes.insert(0, f"peak precipitation probability {max(probabilities)}%")
        self.caption.configure(text=caption + "  \u00b7  " + "  \u00b7  ".join(notes))
