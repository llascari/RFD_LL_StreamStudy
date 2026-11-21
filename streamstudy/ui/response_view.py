"""Rainfall -> flow tab: historical storm response and a forecast-driven estimate."""

from __future__ import annotations

import tkinter as tk
from datetime import timedelta
from tkinter import ttk

from ..models import DataBundle, HistoryBundle, utc_now
from ..response import Prediction, forecast_scenario, predict, recent_baseflow, scale_scenario
from .charts import ChartCanvas, ChartSeries, ScatterChart
from .theme import SERIES_COLORS
from .widgets import StatCard, clear_tree, treeview


class ResponseView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self._bundle: DataBundle | None = None
        self._override: float | None = None
        self._prediction: Prediction | None = None
        self._build()

    # -- construction --------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=3)
        self.rowconfigure(3, weight=2)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Rainfall \u2192 Flow", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.caption = ttk.Label(
            header,
            text="Analysing rainfall-runoff history\u2026",
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        )
        self.caption.grid(row=1, column=0, sticky="w", pady=(2, 0))

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(controls, text="History", style="Muted.TLabel").pack(
            side="left", padx=(0, 6)
        )
        self.years_var = tk.StringVar(value=f"{self.app.history_years} years")
        years_box = ttk.Combobox(
            controls,
            textvariable=self.years_var,
            width=9,
            state="readonly",
            values=["2 years", "3 years", "5 years", "10 years"],
        )
        years_box.pack(side="left")
        years_box.bind("<<ComboboxSelected>>", self._on_years)
        ttk.Button(controls, text="Reload history", command=self._reload).pack(
            side="left", padx=(8, 0)
        )

        stats = ttk.Frame(self)
        stats.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(4):
            stats.columnconfigure(column, weight=1, uniform="response")
        self.response_card = StatCard(stats, "Response rate")
        self.lag_card = StatCard(stats, "Time to peak")
        self.half_card = StatCard(stats, "Recession half-life")
        self.events_card = StatCard(stats, "Events analysed")
        for index, card in enumerate(
            (self.response_card, self.lag_card, self.half_card, self.events_card)
        ):
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 10) if index < 3 else 0)

        body = ttk.Frame(self)
        body.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        body.columnconfigure(0, weight=1, uniform="charts")
        body.columnconfigure(1, weight=1, uniform="charts")
        body.rowconfigure(0, weight=1)

        self.scatter = ScatterChart(
            body,
            height=200,
            title="Storm rainfall vs peak rise",
            x_unit="rain (in)",
            y_unit="rise (cfs)",
        )
        self.scatter.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        scenario_row = ttk.Frame(right)
        scenario_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(scenario_row, text="Rain scenario", style="Muted.TLabel").pack(
            side="left"
        )
        self.scenario_var = tk.StringVar(value="0.00")
        spin = ttk.Spinbox(
            scenario_row,
            from_=0.0,
            to=15.0,
            increment=0.05,
            width=6,
            textvariable=self.scenario_var,
            justify="right",
            command=self._recalculate,
        )
        spin.pack(side="left", padx=(6, 4))
        spin.bind("<Return>", lambda _event: self._recalculate())
        spin.bind("<FocusOut>", lambda _event: self._recalculate())
        ttk.Label(scenario_row, text="in", style="Muted.TLabel").pack(side="left")
        ttk.Button(
            scenario_row, text="Use forecast", command=self._use_forecast
        ).pack(side="left", padx=(8, 0))
        self.metrics_var = tk.BooleanVar(value=self.app.store_flow_metrics)
        ttk.Checkbutton(
            scenario_row,
            text="Remember",
            variable=self.metrics_var,
            command=lambda: self.app.set_store_flow_metrics(self.metrics_var.get()),
        ).pack(side="left", padx=(10, 0))
        self.scenario_source = ttk.Label(scenario_row, text="", style="Muted.TLabel")
        self.scenario_source.pack(side="right")

        self.outlook = ttk.Label(right, text="", style="Muted.TLabel", wraplength=520)
        self.outlook.grid(row=2, column=0, sticky="w", pady=(4, 0))

        self.prediction_chart = ChartCanvas(
            right,
            height=170,
            title="Response outlook",
            unit="cfs",
            empty_text="No scenario yet",
        )
        self.prediction_chart.grid(row=1, column=0, sticky="nsew")

        table_frame, self.table = treeview(
            self,
            {
                "date": ("Storm start", 120, "w"),
                "rain": ("Rain (in)", 82, "e"),
                "days": ("Days", 55, "e"),
                "base": ("Base (cfs)", 90, "e"),
                "peak": ("Peak (cfs)", 90, "e"),
                "rise": ("Rise (cfs)", 90, "e"),
                "lag": ("Lag (h)", 75, "e"),
                "half": ("Half-life (d)", 100, "e"),
            },
            height=5,
        )
        table_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))

        self.note = ttk.Label(
            self,
            text="First-order estimate from daily means: rolling 7-day-minimum baseflow, storms = grouped rain "
            "days, response = least-squares fit of peak rise per inch, timing = median lag + exponential "
            "recession. Soil moisture, snowmelt and routing are not modelled \u2014 treat the band as a range, "
            "not a forecast.",
            style="Muted.TLabel",
            wraplength=1000,
            justify="left",
        )
        self.note.grid(row=4, column=0, sticky="w", pady=(8, 0))

    # -- actions -------------------------------------------------------
    def _on_years(self, _event: tk.Event | None = None) -> None:
        try:
            years = int(self.years_var.get().split()[0])
        except (ValueError, IndexError):
            return
        self.app.load_history(years=years)

    def _reload(self) -> None:
        self.app.load_history()

    def _use_forecast(self) -> None:
        self._override = None
        if self._bundle is not None:
            self.render(self._bundle)

    def _recalculate(self) -> None:
        try:
            total = max(0.0, float(self.scenario_var.get()))
        except ValueError:
            return
        self._override = total
        if self._bundle is not None:
            self.render(self._bundle)

    # -- rendering -----------------------------------------------------
    def render(self, bundle: DataBundle) -> None:
        self._bundle = bundle
        history = bundle.history
        if history is None:
            self._show_message(
                "Analysing rainfall-runoff history\u2026"
                if self.app.history_loading
                else "No historical analysis loaded yet.",
                history,
            )
            return
        if history.fit is None:
            self._show_message(
                "Not enough paired storm events to fit a response "
                f"(found {len(history.events)}, need 3).",
                history,
            )
            return
        self._render_fit(bundle, history)

    def _render_fit(self, bundle: DataBundle, history: HistoryBundle) -> None:
        fit = history.fit
        assert fit is not None
        self.caption.configure(
            text=(
                f"{bundle.site.name}  \u00b7  {history.start:%b %Y}\u2013{history.end:%b %Y}"
                f"  \u00b7  rain: {history.precip_source}"
                f"  \u00b7  {history.flow_days:,} daily flow values"
            )
        )
        self.years_var.set(f"{self.app.history_years} years")

        self.response_card.set(
            f"{fit.slope:,.0f}",
            "cfs/in",
            f"10\u201390th {fit.ratio_p10:,.0f}\u2013{fit.ratio_p90:,.0f}",
        )
        self.lag_card.set(
            f"{fit.lag_p50_hours:.0f}",
            "h",
            f"10\u201390th {fit.lag_p10_hours:.0f}\u2013{fit.lag_p90_hours:.0f} h",
        )
        self.half_card.set(
            f"{fit.half_life_days:.1f}", "days", "post-peak decay to half"
        )
        self.events_card.set(
            f"{fit.events}", "storms", f"r\u00b2 {fit.r_squared:.2f} \u00b7 {fit.confidence} confidence"
        )

        forecast, source = forecast_scenario(bundle)
        if self._override is None:
            self.scenario_var.set(f"{forecast.total_in:.2f}")
            scenario = forecast
        else:
            scenario = scale_scenario(forecast, self._override)
            self.scenario_var.set(f"{self._override:.2f}")
        self.scenario_source.configure(
            text=f"{source} {forecast.total_in:.2f} in"
        )

        flow = bundle.usgs.get("00060")
        current = (
            flow.latest.value if flow is not None and flow.latest is not None else 0.0
        )
        prediction = predict(
            scenario,
            fit,
            history.events,
            current_cfs=float(current or 0.0),
            baseflow_cfs=recent_baseflow(flow),
            source=source,
        )
        self._prediction = prediction

        points = [(event.rain_in, event.rise_cfs) for event in history.events]
        highlight = (
            (prediction.rain_in, prediction.rise_cfs) if prediction is not None else None
        )
        self.scatter.set_data(
            points,
            slope=fit.slope,
            highlight=highlight,
            title=f"Storm rainfall vs peak rise ({len(points)} storms)",
        )

        observed = []
        if flow is not None:
            cutoff = utc_now() - timedelta(days=5)
            observed = [
                (sample.time, float(sample.value))
                for sample in flow.valid
                if sample.time >= cutoff
            ]
        series = [ChartSeries("Observed", observed, SERIES_COLORS["discharge"], width=2)]

        if prediction is not None:
            series.extend(
                [
                    ChartSeries(
                        "Predicted",
                        list(prediction.curve),
                        "#6dc0ff",
                        width=2,
                        dashed=True,
                    ),
                    ChartSeries(
                        "10th pct", list(prediction.low_curve), "#5b7080", width=1, dashed=True
                    ),
                    ChartSeries(
                        "90th pct",
                        list(prediction.high_curve),
                        "#5b7080",
                        width=1,
                        dashed=True,
                    ),
                ]
            )
            title = (
                f"Outlook: peak {prediction.peak_cfs:,.0f} cfs "
                f"around {prediction.peak_time.astimezone():%a %H:%M}"
            )
            low_rise = prediction.low_peak_cfs - prediction.current_cfs
            high_rise = prediction.high_peak_cfs - prediction.current_cfs
            similar = (
                f"  \u00b7  {len(prediction.similar)} similar storm(s) in the record"
                if prediction.similar
                else ""
            )
            self.outlook.configure(
                text=(
                    f"{prediction.rain_in:.2f} in \u2192 peak {prediction.peak_cfs:,.0f} cfs "
                    f"(rise +{prediction.rise_cfs:,.0f}; range +{low_rise:,.0f} to +{high_rise:,.0f}) "
                    f"in about {(prediction.peak_time - utc_now()).total_seconds() / 3600:.0f} h"
                    f"  \u00b7  +{prediction.rise_pct_base:.0f}% of baseflow, "
                    f"{prediction.rise_pct_peak:.0f}% of peak; 24 h decay "
                    f"{prediction.decay_24h_pct:.0f}% of storm flow"
                    f"{similar}"
                )
            )
            self.app.save_flow_metrics(
                bundle.site.number,
                {
                    "rain_in": prediction.rain_in,
                    "peak_cfs": prediction.peak_cfs,
                    "rise_cfs": prediction.rise_cfs,
                    "rise_pct_base": prediction.rise_pct_base,
                    "rise_pct_peak": prediction.rise_pct_peak,
                    "decay_24h_pct": prediction.decay_24h_pct,
                    "peak_time": prediction.peak_time.astimezone().isoformat(
                        timespec="minutes"
                    ),
                    "confidence": prediction.confidence,
                },
            )
        else:
            title = "Response outlook"
            self.outlook.configure(
                text="No rain in the scenario, so no rise is predicted."
            )

        self.prediction_chart.set_series(
            series,
            title=title,
            unit="cfs",
            empty_text="No rain in the scenario \u2014 no rise expected",
        )

        clear_tree(self.table)
        for event in sorted(history.events, key=lambda e: e.start, reverse=True)[:40]:
            half = f"{event.half_life_days:.1f}" if event.half_life_days else "\u2014"
            self.table.insert(
                "",
                "end",
                values=(
                    event.start.strftime("%b %d, %Y"),
                    f"{event.rain_in:.2f}",
                    event.rain_days,
                    f"{event.baseline_cfs:,.0f}",
                    f"{event.peak_cfs:,.0f}",
                    f"{event.rise_cfs:,.0f}",
                    f"{event.lag_hours:.0f}",
                    half,
                ),
            )

    def _show_message(self, message: str, history: HistoryBundle | None) -> None:
        caption = "Rainfall \u2192 Flow"
        if history is not None:
            caption = (
                f"{history.start:%b %Y}\u2013{history.end:%b %Y}  \u00b7  "
                f"rain: {history.precip_source}  \u00b7  {history.flow_days:,} daily flow values"
            )
        self.caption.configure(text=caption)
        for card in (
            self.response_card,
            self.lag_card,
            self.half_card,
            self.events_card,
        ):
            card.set("\u2014", "", "")
        self.scatter.set_data([], slope=None, highlight=None, empty_text=message)
        self.prediction_chart.set_series([], empty_text=message)
        self.outlook.configure(text="")
        self.scenario_source.configure(text="")
        clear_tree(self.table)
