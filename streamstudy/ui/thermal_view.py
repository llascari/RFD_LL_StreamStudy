"""Temp Drivers tab: how air temperature and sunshine track water temperature."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..analysis import daily_means
from ..models import DataBundle
from ..thermal import (
    JointDriverFit,
    SunlightPeer,
    ThermalAnalysis,
    WaterSource,
    build_thermal_analysis,
    joint_anomaly_fit,
    merge_weather,
    series_water_c,
)
from .charts import SignedScatterChart
from .theme import SERIES_COLORS
from .widgets import StatCard, clear_tree, set_row_tone, treeview

ABSOLUTE_BASIS = "Absolute"
ANOMALY_BASIS = "Rise over normal"
BASIS_CHOICES = (ABSOLUTE_BASIS, ANOMALY_BASIS)


class ThermalView(ttk.Frame):
    """Correlation analysis for USGS and Monitor My Watershed water temperature."""

    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(20, 14))
        self.app = app
        self._bundle: DataBundle | None = None
        self._sources: list[WaterSource] = []
        self._air: dict = {}
        self._sun: dict = {}
        self._analysis: ThermalAnalysis | None = None
        self._joint: JointDriverFit | None = None
        self._build()

    # -- construction --------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Temp Drivers", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.caption = ttk.Label(
            header,
            text="Loading water temperature and weather drivers\u2026",
            style="Muted.TLabel",
            wraplength=500,
            justify="left",
        )
        self.caption.grid(row=1, column=0, sticky="w", pady=(2, 0))

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(controls, text="Water source", style="Muted.TLabel").pack(
            side="left", padx=(0, 6)
        )
        self.source_var = tk.StringVar()
        self.source_box = ttk.Combobox(
            controls,
            textvariable=self.source_var,
            state="readonly",
            width=34,
            values=[],
        )
        self.source_box.pack(side="left")
        self.source_box.bind("<<ComboboxSelected>>", lambda _event: self._render_selected())
        ttk.Button(controls, text="Window\u2026", command=self.app.show_window_dialog).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(controls, text="Basis", style="Muted.TLabel").pack(
            side="left", padx=(12, 6)
        )
        self.basis_var = tk.StringVar(value=ANOMALY_BASIS)
        basis_box = ttk.Combobox(
            controls,
            textvariable=self.basis_var,
            state="readonly",
            width=16,
            values=list(BASIS_CHOICES),
        )
        basis_box.pack(side="left")
        basis_box.bind("<<ComboboxSelected>>", lambda _event: self._render_selected())
        ttk.Button(
            controls, text="Compare nearby\u2026", command=self.app.compare_thermal_nearby
        ).pack(side="left", padx=(8, 0))

        cards = ttk.Frame(self)
        cards.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        for column in range(4):
            cards.columnconfigure(column, weight=1, uniform="thermal")
        self.split_label = ttk.Label(
            self,
            text="",
            style="Muted.TLabel",
            wraplength=1050,
            justify="left",
        )
        self.split_label.grid(row=2, column=0, sticky="w", pady=(0, 8))
        self.air_card = StatCard(
            cards, "Air \u2192 water", accent=SERIES_COLORS["nws"]
        )
        self.sun_card = StatCard(
            cards, "Sunlight \u2192 water", accent=SERIES_COLORS["openmeteo"]
        )
        self.water_card = StatCard(
            cards, "Water days", accent=SERIES_COLORS["temperature"]
        )
        self.driver_card = StatCard(cards, "Paired drivers")
        for index, card in enumerate(
            (self.air_card, self.sun_card, self.water_card, self.driver_card)
        ):
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 10) if index < 3 else 0)

        body = ttk.Frame(self)
        body.grid(row=3, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1, uniform="thermal")
        body.columnconfigure(1, weight=1, uniform="thermal")
        body.rowconfigure(0, weight=3)
        body.rowconfigure(1, weight=2)

        self.air_scatter = SignedScatterChart(
            body,
            height=230,
            title="Water vs air temperature",
            x_unit="air C",
            y_unit="water C",
            empty_text="No paired water/air days",
        )
        self.air_scatter.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.sun_scatter = SignedScatterChart(
            body,
            height=230,
            title="Water vs sunshine",
            x_unit="sun h",
            y_unit="water C",
            empty_text="No paired water/sunshine days",
        )
        self.sun_scatter.grid(row=0, column=1, sticky="nsew")

        table_frame, self.table = treeview(
            body,
            {
                "lag": ("Lag (d)", 60, "center"),
                "air_r": ("Air r", 64, "e"),
                "air_n": ("Air n", 54, "e"),
                "sun_r": ("Sun r", 64, "e"),
                "sun_n": ("Sun n", 54, "e"),
            },
            height=6,
            stretch_last=False,
        )
        table_frame.grid(row=1, column=0, columnspan=2, sticky="nw", pady=(10, 0))

        self.note = ttk.Label(
            self,
            text=(
                "Air temperature and sunshine are Open-Meteo daily means; water temperature is "
                "USGS daily values or Monitor My Watershed sensor means. A positive lag means "
                "water temperature follows the driver (for example, today's air and tomorrow's "
                "water). Basis \u201crise over normal\u201d subtracts each series' centred 15-day "
                "rolling mean, so the fit describes day-to-day departures from the seasonal norm "
                "(the slope reads \u00b0C of water rise per unit of driver rise) instead of absolute "
                "temperature, which on long windows mostly reflects the seasons. The split line "
                "regresses both drivers together, so each slope holds the other constant \u2014 "
                "sunshine's effect on water rise, all else being equal. Correlation is not "
                "causation, and MMW sensors cover the portal's recent record only."
            ),
            style="Muted.TLabel",
            wraplength=1050,
            justify="left",
        )
        self.note.grid(row=4, column=0, sticky="w", pady=(8, 0))

    # -- rendering -----------------------------------------------------
    def render(self, bundle: DataBundle) -> None:
        self._bundle = bundle
        window = self.app.analysis_window.clipped()
        sources: list[WaterSource] = []

        history = bundle.history
        usgs = dict(history.water_temp_daily) if history is not None else {}
        if not usgs:
            usgs = dict(bundle.water_temp_daily)
        iv_water = bundle.usgs.get("00010")
        if iv_water is not None:
            usgs.update(daily_means(iv_water.samples))
        usgs = {
            day: value for day, value in usgs.items() if window.start <= day <= window.end
        }
        if usgs:
            sources.append(
                WaterSource(
                    key="usgs",
                    label="USGS 00010",
                    daily=usgs,
                    note="daily means; recent IV fills gaps",
                )
            )

        mmw_water = {}
        if "temperature" in bundle.mmw_series:
            mmw_water = series_water_c(bundle.mmw_series["temperature"])
            mmw_water = {
                day: value
                for day, value in mmw_water.items()
                if window.start <= day <= window.end
            }
        if mmw_water:
            site = bundle.mmw_site
            name = site.name if site is not None else "Monitor My Watershed"
            sources.append(
                WaterSource(
                    key="mmw",
                    label=f"MMW \u00b7 {name}",
                    daily=mmw_water,
                    note="sensor daily means; recent record only",
                    recent_only=True,
                )
            )

        air = dict(history.air_mean) if history is not None else {}
        sun = dict(history.sunshine) if history is not None else {}
        air, sun = merge_weather(air, sun, bundle.weather_days)
        air = {day: value for day, value in air.items() if window.start <= day <= window.end}
        sun = {day: value for day, value in sun.items() if window.start <= day <= window.end}

        self._sources = sources
        self._air = air
        self._sun = sun
        labels = [source.label for source in sources]
        self.source_box.configure(values=labels)
        if labels:
            if self.source_var.get() not in labels:
                self.source_var.set(labels[0])
        else:
            self.source_var.set("")

        driver_bits = []
        if air:
            driver_bits.append(f"air {len(air)} d")
        if sun:
            driver_bits.append(f"sun {len(sun)} d")
        source_text = (
            f"{len(sources)} sources" if sources else "no water temperature source"
        )
        window_text = window.label
        if window.label != window.range_label:
            window_text += f" ({window.range_label})"
        self.caption.configure(
            text=(
                f"{bundle.site.name}  \u00b7  {source_text}  \u00b7  "
                + (" + ".join(driver_bits) if driver_bits else "no weather drivers")
                + f"  \u00b7  {window_text}"
            )
        )
        if not sources:
            self._clear("No USGS or Monitor My Watershed water temperature for this window.")
            return
        self._render_selected()

    def _selected_source(self) -> WaterSource | None:
        label = self.source_var.get()
        return next((source for source in self._sources if source.label == label), None)

    def _render_selected(self) -> None:
        source = self._selected_source()
        if source is None:
            self._clear("Choose a water-temperature source.")
            return
        analysis = build_thermal_analysis(
            source.daily,
            self._air,
            self._sun,
            max_lag=5,
            min_pairs=5,
        )
        self._analysis = analysis
        self._joint = joint_anomaly_fit(
            source.daily,
            self._air,
            self._sun,
            max_lag=5,
            min_pairs=5,
        )
        self.split_label.configure(text=self._split_text(self._joint))
        anomaly = self.basis_var.get() == ANOMALY_BASIS
        air_fit = analysis.air if not anomaly else (analysis.air_anomaly or analysis.air)
        sun_fit = analysis.sun if not anomaly else (analysis.sun_anomaly or analysis.sun)

        self._fill_card(self.air_card, air_fit, source, anomaly, "\u00b0C per \u00b0C")
        self._fill_card(self.sun_card, sun_fit, source, anomaly, "\u00b0C per sun-h")
        self.water_card.set(
            f"{analysis.water_days:,}",
            "days",
            (
                f"{analysis.anomaly_days} anomaly days \u00b7 {source.note}"
                if anomaly
                else source.note
            )
            + (f" \u00b7 {analysis.anomaly_note}" if anomaly and analysis.anomaly_note else ""),
        )
        self.driver_card.set(
            f"{len(self._air)} / {len(self._sun)}",
            "",
            "air days / sunshine days",
        )

        basis_note = " \u00b7 rise over normal" if anomaly else ""
        self.air_scatter.set_data(
            air_fit.points,
            fit=air_fit.fit,
            title=(
                f"Water vs air temperature{basis_note} (lag {air_fit.best.lag_days:+d} d)"
                if air_fit.best is not None
                else f"Water vs air temperature{basis_note}"
            ),
            x_unit="air \u0394C" if anomaly else "air C",
            y_unit="water \u0394C" if anomaly else "water C",
            empty_text="No overlapping water/air daily values",
        )
        self.sun_scatter.set_data(
            sun_fit.points,
            fit=sun_fit.fit,
            title=(
                f"Water vs sunshine{basis_note} (lag {sun_fit.best.lag_days:+d} d)"
                if sun_fit.best is not None
                else f"Water vs sunshine{basis_note}"
            ),
            x_unit="sun \u0394h" if anomaly else "sun h",
            y_unit="water \u0394C" if anomaly else "water C",
            empty_text="No overlapping water/sunshine daily values",
        )
        self._fill_table(air_fit, sun_fit)

    @staticmethod
    def _split_text(joint: JointDriverFit | None) -> str:
        if joint is None:
            return (
                "Sun vs air split: needs overlapping water, air and sunshine anomalies "
                "(a season or more works best)."
            )
        sun = f"{joint.sun_slope:+.2f}" if joint.sun_slope is not None else "\u2014"
        air = f"{joint.air_slope:+.2f}" if joint.air_slope is not None else "\u2014"
        sun_r = f"{joint.sun_partial_r:+.2f}" if joint.sun_partial_r is not None else "\u2014"
        air_r = f"{joint.air_partial_r:+.2f}" if joint.air_partial_r is not None else "\u2014"
        r2 = f"{joint.r_squared:.2f}" if joint.r_squared is not None else "\u2014"
        return (
            f"All else equal (rise over normal, {joint.n} days, R\u00b2 {r2}): "
            f"sun +1 h \u2192 water {sun} \u00b0C (partial r {sun_r}) \u00b7 "
            f"air +1 \u00b0C \u2192 water {air} \u00b0C (partial r {air_r}) \u00b7 "
            f"lags air +{joint.air_lag} d / sun +{joint.sun_lag} d \u00b7 {joint.confidence}"
        )

    def _fill_card(
        self,
        card: StatCard,
        fit,
        source: WaterSource,
        anomaly: bool,
        slope_unit: str,
    ) -> None:
        if fit.best is None:
            card.set("\u2014", "", f"not enough paired days \u00b7 {source.label}")
            return
        if anomaly:
            slope = f"{fit.slope:+.2f}" if fit.slope is not None else "\u2014"
            card.set(
                slope,
                slope_unit,
                (
                    f"r {fit.best.r:+.2f} \u00b7 best lag {fit.best.lag_days:+d} d "
                    f"\u00b7 n {fit.best.n} \u00b7 {fit.confidence}"
                ),
            )
        else:
            card.set(
                f"r {fit.best.r:+.2f}",
                "",
                f"best lag {fit.best.lag_days:+d} d \u00b7 n {fit.best.n} \u00b7 {fit.confidence}",
            )

    def _fill_table(self, air_fit, sun_fit) -> None:
        clear_tree(self.table)
        air_rows = {lag: (r, n) for lag, r, n in air_fit.by_lag}
        sun_rows = {lag: (r, n) for lag, r, n in sun_fit.by_lag}
        for lag in range(-5, 6):
            air_r, air_n = air_rows.get(lag, (None, 0))
            sun_r, sun_n = sun_rows.get(lag, (None, 0))
            self.table.insert(
                "",
                "end",
                values=(
                    f"{lag:+d}" if lag else "0",
                    f"{air_r:+.2f}" if air_r is not None else "\u2014",
                    str(air_n),
                    f"{sun_r:+.2f}" if sun_r is not None else "\u2014",
                    str(sun_n),
                ),
            )

    def comparison_inputs(self) -> tuple[str, dict, dict, dict] | None:
        """``(label, water, air, sun)`` for the selected source, or ``None``.

        Read on the main thread only (it touches Tk variables); the result is
        plain data that a worker can use safely.
        """
        source = self._selected_source()
        if source is None:
            return None
        return source.label, dict(source.daily), dict(self._air), dict(self._sun)

    def show_peer_comparison(self, peers: tuple[SunlightPeer, ...]) -> None:
        """Dialog comparing sunshine-driven water rise across nearby streams."""
        window = tk.Toplevel(self.winfo_toplevel())
        window.title("Sunlight response at nearby gages")
        window.transient(self.winfo_toplevel())
        frame = ttk.Frame(window, padding=(16, 14))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(
            frame,
            text="Sunlight response at nearby gages",
            style="Heading.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            frame,
            text=(
                "Rise over normal, air held constant: \u00b0C of water-temperature rise per "
                "sunshine-hour above the stream's own rolling normal, from a joint regression "
                "with air temperature. Sun pr / Air pr are the partial correlations. Mean \u00b0C "
                "hints at each stream's thermal class (coldwater streams run cooler). Gages "
                "without valid temperature in the window are excluded; MMW sensors are "
                "recent-only. Shared regional drivers; sorted strongest first. Screening "
                "heuristic, not a calibrated model."
            ),
            style="Muted.TLabel",
            wraplength=560,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))

        table_frame, table = treeview(
            frame,
            {
                "site": ("Site", 84, "w"),
                "name": ("Name", 190, "w"),
                "km": ("km", 48, "e"),
                "mean": ("Mean \u00b0C", 60, "e"),
                "sun_r": ("Sun pr", 54, "e"),
                "air_r": ("Air pr", 54, "e"),
                "slope": ("\u00b0C/sun-h", 68, "e"),
                "lag": ("Lag a/s", 56, "center"),
                "pairs": ("Pairs", 50, "e"),
            },
            height=min(12, max(3, len(peers))),
            stretch_last=False,
        )
        table_frame.grid(row=2, column=0, sticky="nsew")
        frame.rowconfigure(2, weight=1)
        set_row_tone(table)
        for peer in peers:
            name = peer.name[:32] + (" (this site)" if peer.this_site else "")
            if peer.error:
                table.insert(
                    "",
                    "end",
                    values=(
                        peer.site_number,
                        f"{name} \u2014 {peer.error[:40]}",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                    ),
                    tags=("muted",),
                )
                continue
            table.insert(
                "",
                "end",
                values=(
                    peer.site_number,
                    name,
                    f"{peer.distance_km:.0f}" if peer.distance_km else "0",
                    f"{peer.mean_c:.1f}" if peer.mean_c is not None else "\u2014",
                    f"{peer.sun_r:+.2f}" if peer.sun_r is not None else "\u2014",
                    f"{peer.air_r:+.2f}" if peer.air_r is not None else "\u2014",
                    (
                        f"{peer.slope_c_per_hour:+.2f}"
                        if peer.slope_c_per_hour is not None
                        else "\u2014"
                    ),
                    (
                        f"{peer.air_lag_days:+d}/{peer.sun_lag_days:+d}"
                        if peer.air_lag_days is not None and peer.sun_lag_days is not None
                        else "\u2014"
                    ),
                    str(peer.pairs),
                ),
            )
        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")

    def _clear(self, message: str) -> None:
        self._analysis = None
        self._joint = None
        self.split_label.configure(text="")
        for card in (self.air_card, self.sun_card, self.water_card, self.driver_card):
            card.set("\u2014", "", "")
        self.air_scatter.set_data([], title="Water vs air temperature", empty_text=message)
        self.sun_scatter.set_data([], title="Water vs sunshine", empty_text=message)
        clear_tree(self.table)
        self.caption.configure(text=message)
