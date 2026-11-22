"""Flow forecast: 10-day streamflow response from forecast rain.

The curve is the forecast hyetograph convolved with the empirical response
shape (median lag + recession half-life), with 10-90 percentile bands from the
historical rise-per-inch ratios. The table is the evidence: similar storms.
"""

from __future__ import annotations

import tkinter as tk
from datetime import timedelta
from tkinter import ttk

from ..analysis import format_value
from ..models import DataBundle, utc_now
from ..response import (
    Prediction,
    forecast_scenario_horizon,
    predict_horizon,
    recent_baseflow,
)
from .charts import ChartCanvas, ChartSeries
from .theme import SERIES_COLORS
from .widgets import StatCard, clear_tree, treeview


class FlowForecastView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self._prediction: Prediction | None = None
        self._build()

    # -- construction --------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Flow forecast", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.caption = ttk.Label(
            header,
            text="Waiting for a fitted response and rainfall forecast\u2026",
            style="Muted.TLabel",
            wraplength=820,
            justify="left",
        )
        self.caption.grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(header, text="Refresh", command=self.app.refresh).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        cards = ttk.Frame(self)
        cards.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        for column in range(4):
            cards.columnconfigure(column, weight=1, uniform="forecast")
        self.peak_card = StatCard(cards, "Predicted peak")
        self.rise_card = StatCard(cards, "Rise")
        self.time_card = StatCard(cards, "Peak time")
        self.conf_card = StatCard(cards, "Confidence")
        for index, card in enumerate(
            (self.peak_card, self.rise_card, self.time_card, self.conf_card)
        ):
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 10) if index < 3 else 0)

        body = ttk.Frame(self)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3, uniform="forecast")
        body.columnconfigure(1, weight=2, uniform="forecast")
        body.rowconfigure(0, weight=1)

        self.chart = ChartCanvas(
            body,
            height=300,
            title="Predicted streamflow, next 10 days",
            unit="cfs",
            empty_text="No forecast rain or fitted response available",
        )
        self.chart.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        panel = ttk.Frame(body)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        confidence = ttk.Frame(panel, style="Card.TFrame", padding=(12, 10))
        confidence.grid(row=0, column=0, sticky="ew")
        confidence.columnconfigure(0, weight=1)
        ttk.Label(
            confidence,
            text="Confidence & evidence",
            style="Card.TLabel",
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.confidence_var = tk.StringVar(value="")
        ttk.Label(
            confidence,
            textvariable=self.confidence_var,
            style="MutedCard.TLabel",
            wraplength=380,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        evidence = ttk.Frame(panel)
        evidence.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        evidence.columnconfigure(0, weight=1)
        evidence.rowconfigure(1, weight=1)
        ttk.Label(
            evidence, text="Evidence: similar past storms", style="Subheading.TLabel"
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        table_frame, self.table = treeview(
            evidence,
            {
                "date": ("Date", 88, "w"),
                "rain": ("Rain", 40, "e"),
                "peak": ("Peak", 46, "e"),
                "rise": ("Rise", 44, "e"),
                "lag": ("Lag", 34, "e"),
                "half": ("Half", 38, "e"),
            },
            height=7,
        )
        table_frame.grid(row=1, column=0, sticky="nsew")

        self.note = ttk.Label(
            self,
            text="Rain: NWS QPF where available, Open-Meteo for the remainder of the 10-day horizon. "
            "The curve is a first-order convolution of forecast rain with the empirical response "
            "(median lag and recession); the band is the 10-90 % range of historical rise per inch. "
            "It is a screening estimate, not a flood forecast.",
            style="Muted.TLabel",
            wraplength=1000,
            justify="left",
        )
        self.note.grid(row=3, column=0, sticky="w", pady=(8, 0))

    # -- rendering -----------------------------------------------------
    def render(self, bundle: DataBundle) -> None:
        history = bundle.history
        flow = bundle.usgs.get("00060")
        fit = history.fit if history is not None else None
        if history is None or fit is None:
            self._clear(
                "The flow forecast needs the historical rainfall-runoff fit. "
                "Wait for history to load or open Rainfall \u2192 Flow."
            )
            return

        scenario, source = forecast_scenario_horizon(bundle)
        current = (
            flow.latest.value if flow is not None and flow.latest is not None else 0.0
        )
        prediction = predict_horizon(
            scenario,
            fit,
            history.events,
            current_cfs=float(current or 0.0),
            baseflow_cfs=recent_baseflow(flow),
            source=source,
            horizon_days=10,
        )
        self._prediction = prediction

        self.caption.configure(
            text=(
                f"{bundle.site.name}  \u00b7  {scenario.total_in:.2f} in forecast rain over 10 days "
                f"({source})  \u00b7  fit {fit.events} storms, r\u00b2 {fit.r_squared:.2f}"
            )
        )

        if prediction is None:
            self._clear(
                "No rain is forecast in the next 10 days, so no flow rise is predicted. "
                "Past storms are still listed below if available."
            )
            self._fill_evidence(history.events, None)
            return

        self.peak_card.set(
            format_value(prediction.peak_cfs, 0),
            "cfs",
            f"10\u201390th {prediction.low_peak_cfs:,.0f}\u2013{prediction.high_peak_cfs:,.0f}",
        )
        hours = (prediction.peak_time - utc_now()).total_seconds() / 3600
        self.rise_card.set(
            f"+{prediction.rise_cfs:,.0f}",
            "cfs",
            f"+{prediction.rise_pct_base:.0f}% of baseflow \u00b7 "
            f"{prediction.rise_pct_peak:.0f}% of peak",
        )
        self.time_card.set(
            prediction.peak_time.astimezone().strftime("%a %H:%M"),
            "",
            f"in about {hours:.0f} h",
        )
        self.conf_card.set(
            prediction.confidence,
            "",
            f"r\u00b2 {fit.r_squared:.2f} \u00b7 {fit.events} storms \u00b7 "
            f"{len(prediction.similar)} analogs",
        )

        observed = []
        if flow is not None:
            cutoff = utc_now() - timedelta(days=5)
            observed = [
                (sample.time, float(sample.value))
                for sample in flow.valid
                if sample.time >= cutoff
            ]
        series = [
            ChartSeries("Observed", observed, SERIES_COLORS["discharge"], width=2),
            ChartSeries("Predicted", list(prediction.curve), "#6dc0ff", width=2, dashed=True),
            ChartSeries("10th pct", list(prediction.low_curve), "#5b7080", width=1, dashed=True),
            ChartSeries("90th pct", list(prediction.high_curve), "#5b7080", width=1, dashed=True),
        ]
        self.chart.set_series(
            series,
            title="Predicted streamflow, next 10 days",
            unit="cfs",
            empty_text="No forecast rain or fitted response available",
        )

        low_rise = prediction.low_peak_cfs - prediction.current_cfs
        high_rise = prediction.high_peak_cfs - prediction.current_cfs
        self.confidence_var.set(
            f"Forecast rain {prediction.rain_in:.2f} in \u00b7 {source}\n"
            f"Predicted rise +{prediction.rise_cfs:,.0f} cfs "
            f"(range +{low_rise:,.0f} to +{high_rise:,.0f})\n"
            f"24 h decay {prediction.decay_24h_pct:.0f}% of storm flow \u00b7 "
            f"half-life {prediction.half_life_days:.1f} d\n"
            f"Model confidence: {fit.confidence} (r\u00b2 {fit.r_squared:.2f}, "
            f"{fit.events} storms)"
        )
        self._fill_evidence(history.events, prediction)

    def _fill_evidence(self, events, prediction: Prediction | None) -> None:
        clear_tree(self.table)
        rows = (
            prediction.similar
            if prediction is not None and prediction.similar
            else tuple(sorted(events, key=lambda event: event.rain_in, reverse=True)[:15])
        )
        for event in rows:
            half = f"{event.half_life_days:.1f}" if event.half_life_days else "\u2014"
            self.table.insert(
                "",
                "end",
                values=(
                    event.start.strftime("%Y-%m-%d"),
                    f"{event.rain_in:.2f}",
                    f"{event.peak_cfs:,.0f}",
                    f"+{event.rise_cfs:,.0f}",
                    f"{event.lag_hours:.0f}",
                    half,
                ),
            )
        if not rows:
            self.table.insert(
                "", "end", values=("\u2014", "no comparable events", "", "", "", "")
            )

    def _clear(self, message: str) -> None:
        self.caption.configure(text=message)
        for card in (self.peak_card, self.rise_card, self.time_card, self.conf_card):
            card.set("\u2014", "", "")
        self.chart.set_series([], empty_text=message)
        self.confidence_var.set("")
        clear_tree(self.table)
