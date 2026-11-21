"""Temperature tab: water vs air, sunshine, and time above a threshold."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, time, timezone
from tkinter import ttk

from ..analysis import daily_means, format_value, trend_label, trend_per_hour
from ..correlation import lagged_correlation
from ..models import DataBundle
from ..temperature_stats import clear_days, threshold_windows
from .charts import ChartCanvas, ChartSeries
from .theme import SERIES_COLORS
from .widgets import StatCard


class TemperatureView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self._bundle: DataBundle | None = None
        self._build()

    # -- construction --------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Temperature", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.caption = ttk.Label(
            header,
            text="Loading water and air temperature\u2026",
            style="Muted.TLabel",
            wraplength=800,
            justify="left",
        )
        self.caption.grid(row=1, column=0, sticky="w", pady=(2, 0))

        cards = ttk.Frame(self)
        cards.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(4):
            cards.columnconfigure(column, weight=1, uniform="temperature")
        self.water_card = StatCard(
            cards, "Water temperature", accent=SERIES_COLORS["temperature"]
        )
        self.air_card = StatCard(cards, "Air temperature", accent=SERIES_COLORS["nws"])
        self.sun_card = StatCard(cards, "Sunshine today", accent=SERIES_COLORS["openmeteo"])
        self.clear_card = StatCard(cards, "Clear days (14 d)")
        for index, card in enumerate(
            (self.water_card, self.air_card, self.sun_card, self.clear_card)
        ):
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 10) if index < 3 else 0)

        body = ttk.Frame(self)
        body.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        body.columnconfigure(0, weight=3, uniform="temperature")
        body.columnconfigure(1, weight=2, uniform="temperature")
        body.rowconfigure(0, weight=1)

        charts = ttk.Frame(body)
        charts.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        charts.columnconfigure(0, weight=1)
        charts.rowconfigure(0, weight=1)
        charts.rowconfigure(1, weight=1)

        self.temp_chart = ChartCanvas(
            charts,
            height=180,
            title="Water and air temperature",
            unit="\u00b0C",
            empty_text="No temperature data for this site",
        )
        self.temp_chart.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.sun_chart = ChartCanvas(
            charts,
            height=130,
            title="Sunshine",
            unit="hours/day",
            empty_text="No sunshine data",
        )
        self.sun_chart.grid(row=1, column=0, sticky="nsew")

        panel = ttk.Frame(body)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        comparison = ttk.Frame(panel, style="Card.TFrame", padding=(12, 10))
        comparison.grid(row=0, column=0, sticky="ew")
        comparison.columnconfigure(0, weight=1)
        ttk.Label(
            comparison,
            text="Water vs weather",
            style="Card.TLabel",
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.compare_var = tk.StringVar(value="")
        ttk.Label(
            comparison,
            textvariable=self.compare_var,
            style="MutedCard.TLabel",
            wraplength=360,
            justify="left",
        ).grid(row=1, column=0, sticky="nw", pady=(8, 0))
        ttk.Label(
            comparison,
            text="Daily means; best lag \u00b12 d. Sunshine = daily duration; clear = cloud \u2264 25 %.",
            style="MutedCard.TLabel",
            wraplength=360,
            justify="left",
        ).grid(row=2, column=0, sticky="sw", pady=(12, 0))

        stats = ttk.Frame(panel, style="Card.TFrame", padding=(10, 8))
        stats.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        stats.columnconfigure(1, weight=1)
        ttk.Label(
            stats,
            text="Time above",
            style="Card.TLabel",
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.threshold_var = tk.StringVar(value=f"{self.app.temperature_threshold:g}")
        spin = ttk.Spinbox(
            stats,
            from_=0.0,
            to=40.0,
            increment=0.5,
            width=5,
            justify="right",
            textvariable=self.threshold_var,
            command=self._apply_threshold,
        )
        spin.grid(row=0, column=1, sticky="e", padx=(8, 4))
        spin.bind("<Return>", lambda _event: self._apply_threshold())
        spin.bind("<FocusOut>", lambda _event: self._apply_threshold())
        ttk.Label(stats, text="\u00b0C", style="MutedCard.TLabel").grid(
            row=0, column=2, sticky="w"
        )

        self.window_vars = {
            label: tk.StringVar(value="\u2014")
            for label in ("24 h", "7 days", "30 days", "1 year")
        }
        for row, (label, variable) in enumerate(self.window_vars.items(), start=1):
            ttk.Label(stats, text=label, style="MutedCard.TLabel").grid(
                row=row, column=0, sticky="w", pady=1
            )
            ttk.Label(
                stats,
                textvariable=variable,
                style="Card.TLabel",
                anchor="e",
            ).grid(row=row, column=1, columnspan=2, sticky="e", pady=1)

        self.note = ttk.Label(
            self,
            text="Water temperature: USGS 00010 where available, else a nearby Monitor My Watershed "
            "sensor. Air/sunshine: Open-Meteo daily. Durations: 15-minute samples for 24 h and 7 d, "
            "daily means for 30 d and 1 y.",
            style="Muted.TLabel",
            wraplength=1000,
            justify="left",
        )
        self.note.grid(row=3, column=0, sticky="w", pady=(8, 0))

    # -- actions -------------------------------------------------------
    def _apply_threshold(self) -> None:
        try:
            value = float(self.threshold_var.get())
        except ValueError:
            return
        self.app.set_temperature_threshold(value)

    # -- rendering -----------------------------------------------------
    def render(self, bundle: DataBundle) -> None:
        self._bundle = bundle
        self.threshold_var.set(f"{self.app.temperature_threshold:g}")

        water = bundle.usgs.get("00010")
        if water is None and "temperature" in bundle.mmw_series:
            water = bundle.mmw_series["temperature"]
        water_daily = dict(bundle.water_temp_daily)
        weather = bundle.weather_days

        source_bits = []
        if bundle.usgs.get("00010") is not None:
            source_bits.append("USGS 00010")
        elif "temperature" in bundle.mmw_series:
            source_bits.append("Monitor My Watershed")
        if weather:
            source_bits.append(f"Open-Meteo ({bundle.weather_zone or 'daily'})")
        self.caption.configure(
            text=(
                f"{bundle.site.name}  \u00b7  " + " + ".join(source_bits)
                if source_bits
                else "No temperature sources available for this site"
            )
        )

        self._render_cards(water, weather, water_daily)
        self._render_charts(water, weather)
        self._render_comparison(water, water_daily, weather)
        self._render_stats(water, water_daily)

    def _render_cards(self, water, weather, water_daily: dict) -> None:
        if water is not None and water.latest is not None:
            self.water_card.set(
                format_value(water.latest.value, 1),
                water.units,
                trend_label(trend_per_hour(water), water.units),
            )
        elif water_daily:
            day = max(water_daily)
            self.water_card.set(
                format_value(water_daily[day], 1), "\u00b0C", f"daily mean \u00b7 {day:%b %d}"
            )
        else:
            self.water_card.set("\u2014", "", "not reported at this site")

        if weather:
            latest = next(
                (day for day in reversed(weather) if day.mean_c is not None), None
            )
            if latest is not None:
                self.air_card.set(
                    format_value(latest.mean_c, 1),
                    "\u00b0C",
                    f"daily mean \u00b7 {latest.day:%b %d}",
                )
            else:
                self.air_card.set("\u2014", "", "no daily means")
            today = next((day for day in weather if day.day == date.today()), None)
            sunshine = today.sunshine_hours if today is not None else None
            if sunshine is None:
                sunshine = next(
                    (day.sunshine_hours for day in reversed(weather) if day.sunshine_hours),
                    None,
                )
            self.sun_card.set(
                format_value(sunshine, 1), "h", "today" if today is not None else "latest"
            )
            self.clear_card.set(
                str(clear_days(weather, 14)), "days", "cloud cover \u2264 25 %"
            )
        else:
            self.air_card.set("\u2014", "", "Open-Meteo unavailable")
            self.sun_card.set("\u2014", "", "")
            self.clear_card.set("\u2014", "", "")

    def _render_charts(self, water, weather) -> None:
        series: list[ChartSeries] = []
        if water is not None:
            series.append(
                ChartSeries(
                    "Water",
                    [(sample.time, float(sample.value)) for sample in water.valid],
                    SERIES_COLORS["temperature"],
                )
            )
        if weather:
            air_points = []
            for day in weather:
                if day.mean_c is None:
                    continue
                moment = datetime.combine(day.day, time(12), tzinfo=timezone.utc)
                air_points.append((moment, day.mean_c))
            series.append(
                ChartSeries("Air (daily mean)", air_points, SERIES_COLORS["nws"], dashed=True)
            )
        self.temp_chart.set_series(
            series,
            title="Water and air temperature",
            unit="\u00b0C",
            empty_text="No temperature data for this site",
        )

        sunshine = []
        for day in weather:
            if day.sunshine_hours is None:
                continue
            moment = datetime.combine(day.day, time(12), tzinfo=timezone.utc)
            sunshine.append((moment, day.sunshine_hours))
        self.sun_chart.set_series(
            [ChartSeries("Sunshine", sunshine, SERIES_COLORS["openmeteo"], kind="bar")]
            if sunshine
            else [],
            title="Sunshine",
            unit="hours/day",
            empty_text="No sunshine data",
        )

    def _render_comparison(self, water, water_daily: dict, weather) -> None:
        if water_daily:
            water_means = water_daily
        elif water is not None:
            water_means = daily_means(water.samples)
        else:
            water_means = {}

        air_means = {
            day.day: day.mean_c for day in weather if day.mean_c is not None
        }
        sun_days = {
            day.day: day.sunshine_hours
            for day in weather
            if day.sunshine_hours is not None
        }

        rows: list[str] = []

        def add(label: str, other: dict) -> None:
            correlation = lagged_correlation(
                water_means,
                other,
                max_lag=2,
                min_pairs=5,
                logarithmic=False,
            )
            if correlation is None:
                return
            rows.append(
                f"{label}: r {correlation.r:+.2f} at {correlation.lag_days:+d} d "
                f"(n {correlation.n})"
            )

        if water_means:
            add("Water \u2194 air", air_means)
            add("Water \u2194 sunshine", sun_days)
        self.compare_var.set(
            "\n".join(rows) if rows else "Not enough overlapping daily values yet."
        )

    def _render_stats(self, water, water_daily: dict) -> None:
        samples = water.samples if water is not None else ()
        daily = water_daily or (
            daily_means(water.samples) if water is not None else {}
        )
        windows = threshold_windows(
            samples, daily, self.app.temperature_threshold
        )
        for window in windows:
            if window.hours <= 0 and not daily:
                text = "\u2014"
            else:
                text = f"{window.hours:.0f} h  \u00b7  {window.percent:.0f}%"
            variable = self.window_vars.get(window.label)
            if variable is not None:
                variable.set(text)
