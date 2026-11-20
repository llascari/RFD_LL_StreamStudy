"""Overview tab: site identity, current conditions and source status."""

from __future__ import annotations

import math
import tkinter as tk
import webbrowser
from tkinter import ttk

from ..analysis import (
    bundle_precip_sources,
    format_value,
    series_stats,
    trend_label,
    trend_per_hour,
)
from ..models import DataBundle
from .theme import BG, SERIES_COLORS, WARN
from .widgets import SourceRow, StatCard


class HomeView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, padding=(22, 16))
        self.app = app
        self._site_url = ""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        self._build()

    def _build(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.meta_var = tk.StringVar(
            value="Enter a USGS site number above and press Load."
        )
        ttk.Label(header, text="Overview", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            textvariable=self.meta_var,
            style="Muted.TLabel",
            wraplength=780,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.link = ttk.Label(header, text="", style="Link.TLabel", cursor="hand2")
        self.link.grid(row=0, column=1, rowspan=2, sticky="e")
        self.link.bind("<Button-1>", self._open_site)

        cards = ttk.Frame(self)
        cards.grid(row=1, column=0, sticky="ew", pady=(16, 12))
        for column in range(4):
            cards.columnconfigure(column, weight=1, uniform="cards")
        self.gage_card = StatCard(cards, "Gage height", accent=SERIES_COLORS["gage"])
        self.discharge_card = StatCard(
            cards, "Discharge", accent=SERIES_COLORS["discharge"]
        )
        self.precip_card = StatCard(
            cards, "Precipitation (24 h)", accent=SERIES_COLORS["cocorahs"]
        )
        self.temp_card = StatCard(
            cards, "Water temperature", accent=SERIES_COLORS["temperature"]
        )
        for index, card in enumerate(
            (self.gage_card, self.discharge_card, self.precip_card, self.temp_card)
        ):
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 10) if index < 3 else 0)

        sources = ttk.Frame(self, style="Card.TFrame", padding=(16, 12))
        sources.grid(row=2, column=0, sticky="nsew")
        sources.columnconfigure(0, weight=1)
        ttk.Label(
            sources,
            text="Data sources",
            style="Card.TLabel",
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self.rows: dict[str, SourceRow] = {}
        networks = (
            ("usgs", "USGS NWIS"),
            ("nws", "NWS"),
            ("openmeteo", "Open-Meteo"),
            ("cocorahs", "CoCoRaHS"),
        )
        for index, (key, network) in enumerate(networks, start=1):
            row = SourceRow(sources, network)
            row.grid(row=index, column=0, sticky="ew", pady=(8 if index == 1 else 4, 0))
            self.rows[key] = row

        self.warnings_var = tk.StringVar(value="")
        self.warnings = tk.Label(
            self,
            textvariable=self.warnings_var,
            bg=BG,
            fg=WARN,
            font=("TkDefaultFont", 8),
            wraplength=940,
            justify="left",
            anchor="w",
        )
        self.warnings.grid(row=3, column=0, sticky="w", pady=(10, 0))

        self.note = ttk.Label(
            self,
            text="USGS values are provisional and subject to revision. "
            "CoCoRaHS gauges report 24-hour totals at ~7 AM local; Open-Meteo is a model, not a gauge.",
            style="Muted.TLabel",
            wraplength=940,
            justify="left",
        )
        self.note.grid(row=4, column=0, sticky="w", pady=(10, 0))

    # -- rendering -----------------------------------------------------
    def render(self, bundle: DataBundle) -> None:
        site = bundle.site
        bits = [site.name or f"USGS {site.number}"]
        bits += [f"USGS {site.number}", site.coordinates]
        if site.state:
            bits.append(site.state)
        if site.site_type:
            bits.append(site.site_type)
        if site.drainage_area_sq_mi:
            bits.append(f"{site.drainage_area_sq_mi:,.1f} mi\u00b2 drainage")
        self.meta_var.set("  \u00b7  ".join(bits))
        self._site_url = site.url
        self.link.configure(text="View on USGS WaterData  \u2197")

        self._render_cards(bundle)
        self._render_sources(bundle)
        if bundle.errors:
            self.warnings_var.set("Warnings: " + "  |  ".join(bundle.errors))
        else:
            self.warnings_var.set("")

    def _render_cards(self, bundle: DataBundle) -> None:
        gage = bundle.usgs.get("00065")
        if gage and gage.latest and gage.latest.value is not None:
            stats = series_stats(gage)
            rate = trend_per_hour(gage)
            detail = f"{trend_label(rate, gage.units)}"
            if stats:
                detail += f"  \u00b7  range {stats.minimum:.2f}\u2013{stats.maximum:.2f}"
            self.gage_card.set(
                format_value(gage.latest.value, 2), gage.units, detail
            )
        else:
            self.gage_card.set("\u2014", "", "not reported at this site")

        discharge = bundle.usgs.get("00060")
        if discharge and discharge.latest and discharge.latest.value is not None:
            stats = series_stats(discharge)
            rate = trend_per_hour(discharge)
            detail = f"{trend_label(rate, discharge.units)}"
            if stats:
                detail += f"  \u00b7  median {format_value(stats.median, 0)}"
            self.discharge_card.set(
                format_value(discharge.latest.value, 0), discharge.units, detail
            )
        else:
            self.discharge_card.set("\u2014", "", "not reported at this site")

        sources = bundle_precip_sources(bundle)
        labels = {
            "usgs": "USGS",
            "cocorahs": "CoCoRaHS",
            "openmeteo": "Open-Meteo",
            "nws": "NWS",
        }
        rendered = False
        for key in ("cocorahs", "usgs", "openmeteo", "nws"):
            daily = sources.get(key) or {}
            if not daily:
                continue
            day = max(daily)
            station = ""
            if key == "cocorahs" and bundle.coco_station:
                station = " " + bundle.coco_station.identifier
            elif key == "nws" and bundle.nws_station:
                station = " " + bundle.nws_station.identifier
            self.precip_card.set(
                f"{daily[day]:.2f}",
                "in",
                f"{labels[key]}{station}  \u00b7  {day:%b %d}",
            )
            rendered = True
            break
        if not rendered:
            self.precip_card.set("\u2014", "", "no precipitation reported")

        temperature = bundle.usgs.get("00010")
        if temperature and temperature.latest and temperature.latest.value is not None:
            rate = trend_per_hour(temperature)
            self.temp_card.set(
                format_value(temperature.latest.value, 1),
                temperature.units,
                trend_label(rate, temperature.units),
            )
        else:
            self.temp_card.set("\u2014", "", "not reported at this site")

    def _render_sources(self, bundle: DataBundle) -> None:
        usgs = self.rows["usgs"]
        if bundle.usgs:
            names = ", ".join(series.name for series in bundle.usgs.values())
            latest = max(
                (series.latest.time for series in bundle.usgs.values() if series.latest),
                default=None,
            )
            detail = f"{len(bundle.usgs)} series ({names})"
            if latest:
                detail += f"  \u00b7  latest {latest.astimezone():%b %d %H:%M}"
            usgs.set(detail, "ok", "live")
        else:
            usgs.set("No instantaneous values returned", "error", "unavailable")

        nws = self.rows["nws"]
        if bundle.nws_station:
            station = bundle.nws_station
            detail = f"{station.identifier} \u2014 {station.name}"
            if not math.isnan(station.distance_km):
                detail += f"  \u00b7  {station.distance_km:.1f} km away"
            observations = len(bundle.nws_precip.valid) if bundle.nws_precip else 0
            if observations:
                detail += f"  \u00b7  {observations} precip obs"
            if bundle.nws_daily:
                detail += f"  \u00b7  {len(bundle.nws_daily)} forecast periods"
            nws.set(detail, "ok", "live")
        else:
            nws.set("No nearby station found", "error", "unavailable")

        openmeteo = self.rows["openmeteo"]
        if bundle.openmeteo_hourly or bundle.openmeteo_daily:
            zone = bundle.openmeteo_zone or "model grid"
            detail = f"{zone}  \u00b7  {len(bundle.openmeteo_hourly)} hourly steps"
            if bundle.openmeteo_daily:
                detail += f"  \u00b7  {len(bundle.openmeteo_daily)} daily totals"
            openmeteo.set(detail, "ok", "modelled")
        else:
            openmeteo.set("No modelled precipitation returned", "error", "unavailable")

        cocorahs = self.rows["cocorahs"]
        if bundle.coco_station and bundle.coco_daily:
            station = bundle.coco_station
            detail = f"{station.identifier} \u2014 {station.name}"
            if not math.isnan(station.distance_km):
                detail += f"  \u00b7  {station.distance_km:.1f} km away"
            detail += f"  \u00b7  {len(bundle.coco_daily)} daily reports"
            cocorahs.set(detail, "ok", "gauge")
        elif bundle.coco_station:
            cocorahs.set(f"{bundle.coco_station.identifier} \u2014 no reports in range", "partial", "empty")
        else:
            cocorahs.set("No nearby volunteer gauge", "idle", "\u2014")

    def _open_site(self, _event: tk.Event) -> None:
        if self._site_url:
            webbrowser.open(self._site_url)
