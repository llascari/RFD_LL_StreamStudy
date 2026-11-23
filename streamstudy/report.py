"""Historical PDF reports for one creek, or every creek near it.

The report is deliberately descriptive, not predictive: it summarises the raw
daily flow and temperature record for a user-chosen window, highlights extreme
high and low flows, and shows the storms that produced them. Everything here is
pure except :func:`write_report`, which writes a PDF through the tiny
dependency-free writer in :mod:`streamstudy.pdf`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .analysis import haversine_km, nice_step
from .analysis_window import TimeWindow
from .models import FlowEvent, ResponseFit, Site, utc_now
from .pdf import PAGE_H, PAGE_W, PdfDocument, PdfPage
from .response import percentile
from .thermal import (
    DriverFit,
    WaterSource,
    build_thermal_analysis,
    sunlight_peers,
)

INK = (0.11, 0.13, 0.17)
MUTED = (0.42, 0.46, 0.52)
ACCENT = (0.16, 0.45, 0.75)
WATER = (0.13, 0.55, 0.62)
AIR = (0.85, 0.45, 0.18)
RAIN = (0.25, 0.52, 0.82)
RULE = (0.80, 0.83, 0.87)
CARD = (0.95, 0.96, 0.98)
WARN = (0.62, 0.20, 0.16)

MARGIN = 52.0
CONTENT_W = PAGE_W - 2 * MARGIN


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReportSite:
    """One gage plus everything the report needs to describe it."""

    site: Site
    history: object  # HistoryBundle; kept loose to avoid an import cycle
    air_mean: dict[date, float] = field(default_factory=dict)
    air_max: dict[date, float] = field(default_factory=dict)
    air_min: dict[date, float] = field(default_factory=dict)
    sunshine: dict[date, float] = field(default_factory=dict)
    mmw_name: str = ""
    mmw_temp_daily: dict[date, float] = field(default_factory=dict)
    distance_km: float = 0.0
    errors: tuple[str, ...] = ()

    @property
    def flow(self) -> dict[date, float]:
        return getattr(self.history, "flow_daily", {}) or {}

    @property
    def water_temp(self) -> dict[date, float]:
        return getattr(self.history, "water_temp_daily", {}) or {}

    @property
    def rain(self) -> dict[date, float]:
        return dict(getattr(self.history, "precip", ()) or ())

    @property
    def events(self) -> tuple[FlowEvent, ...]:
        return tuple(getattr(self.history, "events", ()) or ())

    @property
    def fit(self) -> ResponseFit | None:
        return getattr(self.history, "fit", None)

    @property
    def precip_source(self) -> str:
        return str(getattr(self.history, "precip_source", "") or "unavailable")


@dataclass(frozen=True)
class ReportData:
    """A finished report request: the primary gage plus optional neighbours."""

    primary: ReportSite
    window: TimeWindow
    radius_km: float = 0.0
    threshold_c: float = 20.0
    generated: datetime = field(default_factory=utc_now)
    region: tuple[ReportSite, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def sites(self) -> tuple[ReportSite, ...]:
        return (self.primary,) + tuple(self.region)

    @property
    def region_mode(self) -> bool:
        return bool(self.region)


@dataclass(frozen=True)
class FlowSummary:
    days: int
    mean: float
    median: float
    lowest: float
    lowest_day: date | None
    highest: float
    highest_day: date | None
    p10: float
    p90: float
    rain_total: float
    rain_days: int


@dataclass(frozen=True)
class TemperatureSummary:
    days: int
    mean: float | None
    lowest: float | None
    lowest_day: date | None
    highest: float | None
    highest_day: date | None
    days_above: int
    hours_above: float
    longest_run: int


def summarise_flow(
    flow: dict[date, float], start: date, end: date
) -> FlowSummary:
    """Window summary of daily mean discharge."""
    pairs = sorted(
        (day, value) for day, value in flow.items() if start <= day <= end
    )
    values = [float(value) for _day, value in pairs]
    if not values:
        return FlowSummary(0, math.nan, math.nan, math.nan, None, math.nan, None, math.nan, math.nan, 0.0, 0)
    low_index = min(range(len(values)), key=values.__getitem__)
    high_index = max(range(len(values)), key=values.__getitem__)
    return FlowSummary(
        days=len(values),
        mean=math.fsum(values) / len(values),
        median=percentile(values, 0.5),
        lowest=values[low_index],
        lowest_day=pairs[low_index][0],
        highest=values[high_index],
        highest_day=pairs[high_index][0],
        p10=percentile(values, 0.10),
        p90=percentile(values, 0.90),
        rain_total=0.0,
        rain_days=0,
    )


def summarise_temperature(
    values: dict[date, float],
    start: date,
    end: date,
    threshold_c: float,
) -> TemperatureSummary:
    """Mean/min/max plus time above a threshold, using daily means."""
    pairs = sorted(
        (day, value) for day, value in values.items() if start <= day <= end
    )
    usable = [(day, float(value)) for day, value in pairs if value is not None]
    if not usable:
        return TemperatureSummary(0, None, None, None, None, None, 0, 0.0, 0)
    numbers = [value for _day, value in usable]
    low_index = min(range(len(numbers)), key=numbers.__getitem__)
    high_index = max(range(len(numbers)), key=numbers.__getitem__)
    above = [day for day, value in usable if value > threshold_c]
    longest = run = 0
    previous: date | None = None
    for day in above:
        run = run + 1 if previous is not None and (day - previous).days == 1 else 1
        longest = max(longest, run)
        previous = day
    return TemperatureSummary(
        days=len(usable),
        mean=math.fsum(numbers) / len(numbers),
        lowest=numbers[low_index],
        lowest_day=usable[low_index][0],
        highest=numbers[high_index],
        highest_day=usable[high_index][0],
        days_above=len(above),
        hours_above=24.0 * len(above),
        longest_run=longest,
    )


def extreme_days(
    values: dict[date, float], start: date, end: date, count: int = 5, *, highest: bool = True
) -> list[tuple[date, float]]:
    pairs = [(day, value) for day, value in values.items() if start <= day <= end]
    pairs.sort(key=lambda item: item[1], reverse=highest)
    return pairs[: max(1, int(count))]


def _rain_shape(
    rain: dict[date, float], start: date, end: date
) -> tuple[FlowSummary, list[tuple[date, float]]]:
    """Attach rainfall totals to a flow summary (kept separate for clarity)."""
    totals = [(day, value) for day, value in rain.items() if start <= day <= end]
    total = math.fsum(value for _day, value in totals)
    return (
        FlowSummary(0, math.nan, math.nan, math.nan, None, math.nan, None, math.nan, math.nan, total, len(totals)),
        totals,
    )


# --------------------------------------------------------------------------- #
# PDF drawing helpers
# --------------------------------------------------------------------------- #
def _fmt(value: float | None, digits: int = 1, suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value:,.{digits}f}{suffix}"


def _fmt_day(day: date | None) -> str:
    return day.strftime("%b %d, %Y") if day else "n/a"


def format_elapsed(seconds: float) -> str:
    """Format a duration as MM:SS, or H:MM:SS after an hour."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _wrap(text: str, width_chars: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _paragraph(
    page: PdfPage,
    x: float,
    y: float,
    width_chars: int,
    text: str,
    *,
    size: float = 9.5,
    colour=INK,
    leading: float = 12.0,
    bold: bool = False,
) -> float:
    for line in _wrap(text, width_chars):
        page.text(x, y, line, size=size, colour=colour, bold=bold)
        y += leading
    return y


def _heading(page: PdfPage, y: float, text: str, *, size: float = 13) -> float:
    page.text(MARGIN, y, text, size=size, bold=True, colour=INK)
    page.line(MARGIN, y + 6, PAGE_W - MARGIN, y + 6, colour=RULE, width=0.8)
    return y + 22


def _footer(page: PdfPage, number: int) -> None:
    page.text(
        MARGIN,
        PAGE_H - 32,
        "StreamStudy experimental report - heuristics, not a forecast; not for safety decisions.",
        size=7.5,
        colour=MUTED,
    )
    page.text(PAGE_W - MARGIN - 34, PAGE_H - 32, f"Page {number}", size=7.5, colour=MUTED)


def _card(page: PdfPage, x: float, y: float, w: float, h: float, label: str, value: str, note: str = "") -> None:
    page.rect(x, y, w, h, fill=CARD, stroke=RULE, width=0.6)
    page.text(x + 8, y + 14, label, size=7.5, colour=MUTED)
    page.text(x + 8, y + 32, value, size=14, bold=True, colour=INK)
    if note:
        page.text(x + 8, y + 47, note, size=7.5, colour=MUTED)


def _table(
    page: PdfPage,
    x: float,
    y: float,
    widths: list[float],
    headers: list[str],
    rows: list[list[str]],
    *,
    size: float = 8,
    row_h: float = 14.0,
    max_rows: int | None = None,
) -> float:
    for column, label in enumerate(headers):
        page.text(x + sum(widths[:column]) + 2, y, label, size=size, bold=True, colour=MUTED)
    y += 4
    page.line(x, y, x + sum(widths), y, colour=RULE, width=0.7)
    y += row_h - 3
    for row in rows[: max_rows or len(rows)]:
        for column, value in enumerate(row):
            page.text(
                x + sum(widths[:column]) + 2,
                y,
                value,
                size=size,
                colour=INK,
            )
        y += row_h
    return y


def _decimate(points: list[tuple[date, float]], limit: int = 520) -> list[tuple[date, float]]:
    if len(points) <= limit:
        return points
    stride = max(1, len(points) // limit)
    sampled = points[::stride]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def _flow_chart(
    page: PdfPage,
    x: float,
    y: float,
    w: float,
    h: float,
    flow: dict[date, float],
    rain: dict[date, float],
    start: date,
    end: date,
    title: str,
) -> None:
    page.text(x, y, title, size=10, bold=True, colour=INK)
    plot_x, plot_top = x + 42, y + 16
    plot_w = w - 48
    plot_bottom = y + h - 32
    plot_h = plot_bottom - plot_top
    pairs = sorted((day, value) for day, value in flow.items() if start <= day <= end)
    points = _decimate([(day, float(value)) for day, value in pairs if value is not None])
    page.line(plot_x, plot_bottom, plot_x + plot_w, plot_bottom, colour=RULE, width=0.8)
    page.line(plot_x, plot_top, plot_x, plot_bottom, colour=RULE, width=0.8)
    if len(points) < 2:
        page.text(plot_x + 8, plot_top + plot_h / 2, "No daily flow data in this window", size=9, colour=MUTED)
        return

    values = [value for _day, value in points]
    low, high = min(values), max(values)
    use_log = low > 0 and high / low >= 8.0
    if use_log:
        low = 10 ** math.floor(math.log10(low))
        high = 10 ** math.ceil(math.log10(max(high, low * 10)))

        def project(value: float) -> float:
            return math.log10(max(value, low)) / math.log10(high / low)

    else:
        pad = max(1.0, (high - low) * 0.08)
        low, high = max(0.0, low - pad), high + pad

        def project(value: float) -> float:
            return (value - low) / (high - low) if high > low else 0.5

    for step in range(5):
        fraction = step / 4.0
        grid_y = plot_bottom - fraction * plot_h
        page.line(plot_x, grid_y, plot_x + plot_w, grid_y, colour=(0.90, 0.91, 0.93), width=0.5)
        value = low * (high / low) ** fraction if use_log else low + fraction * (high - low)
        page.text(x + 4, grid_y + 2.5, _fmt(value, 0 if value >= 100 else 1), size=7, colour=MUTED)

    span_days = max(1, (end - start).days)
    polyline = []
    for day, value in points:
        px = plot_x + plot_w * (day - start).days / span_days
        py = plot_bottom - project(value) * plot_h
        polyline.append((px, py))
    page.polyline(polyline, colour=ACCENT, width=1.3)
    page.text(plot_x + 4, plot_top - 4, "flow (cfs)", size=7, colour=MUTED)

    # Rainfall strip below the flow plot.
    strip_top = plot_bottom + 8
    strip_h = 20.0
    rain_pairs = [(day, value) for day, value in rain.items() if start <= day <= end and value > 0]
    if rain_pairs:
        rain_max = max(value for _day, value in rain_pairs)
        bar_w = max(1.0, plot_w / max(1, span_days) * 0.8)
        for day, value in rain_pairs:
            px = plot_x + plot_w * (day - start).days / span_days
            bar_h = strip_h * max(0.04, value / rain_max)
            page.rect(px - bar_w / 2, strip_top + strip_h - bar_h, bar_w, bar_h, fill=RAIN)
        page.text(
            plot_x + plot_w - 104,
            strip_top + 4,
            f"rain (in, max {rain_max:.2f})",
            size=6.5,
            colour=MUTED,
        )
    else:
        page.text(plot_x + 4, strip_top + strip_h, "no precipitation recorded in this window", size=7, colour=MUTED)

    # x-axis labels: start, quarters, end.
    labels = 5
    for index in range(labels):
        day = start + (end - start) * index / max(1, labels - 1)
        px = plot_x + plot_w * index / max(1, labels - 1)
        text = day.strftime("%b %Y") if span_days > 100 else day.strftime("%b %d")
        page.text(px - 14, plot_bottom + strip_h + 22, text, size=7, colour=MUTED)


def _temperature_chart(
    page: PdfPage,
    x: float,
    y: float,
    w: float,
    h: float,
    water: dict[date, float],
    air: dict[date, float],
    threshold_c: float,
    start: date,
    end: date,
    title: str,
) -> None:
    page.text(x, y, title, size=10, bold=True, colour=INK)
    plot_x, plot_top = x + 36, y + 18
    plot_w = w - 42
    plot_bottom = y + h - 22
    plot_h = plot_bottom - plot_top
    page.line(plot_x, plot_bottom, plot_x + plot_w, plot_bottom, colour=RULE, width=0.8)
    page.line(plot_x, plot_top, plot_x, plot_bottom, colour=RULE, width=0.8)

    series = []
    for label, values, colour in (
        ("water", water, WATER),
        ("air", air, AIR),
    ):
        pairs = sorted(
            (day, float(value))
            for day, value in values.items()
            if start <= day <= end and value is not None
        )
        if len(pairs) >= 2:
            series.append((label, _decimate(pairs), colour))
    if not series:
        page.text(plot_x + 8, plot_top + plot_h / 2, "No daily temperature data in this window", size=9, colour=MUTED)
        return

    all_values = [value for _label, points, _colour in series for _day, value in points]
    low, high = min(all_values + [threshold_c]), max(all_values + [threshold_c])
    pad = max(1.0, (high - low) * 0.1)
    low, high = low - pad, high + pad
    span_days = max(1, (end - start).days)

    for step in range(5):
        fraction = step / 4.0
        grid_y = plot_bottom - fraction * plot_h
        page.line(plot_x, grid_y, plot_x + plot_w, grid_y, colour=(0.90, 0.91, 0.93), width=0.5)
        page.text(x + 2, grid_y + 2.5, _fmt(low + fraction * (high - low), 0, " C"), size=7, colour=MUTED)

    # Threshold as a dashed line.
    threshold_y = plot_bottom - (threshold_c - low) / (high - low) * plot_h
    dash = 0.0
    while dash < plot_w:
        page.line(
            plot_x + dash,
            threshold_y,
            plot_x + min(plot_w, dash + 5),
            threshold_y,
            colour=(0.72, 0.30, 0.24),
            width=0.7,
        )
        dash += 10
    page.text(
        plot_x + plot_w - 92,
        threshold_y - 4,
        f"{threshold_c:g} C threshold",
        size=7,
        colour=(0.72, 0.30, 0.24),
    )

    legend_x = plot_x + 4
    for label, points, colour in series:
        coords = [
            (
                plot_x + plot_w * (day - start).days / span_days,
                plot_bottom - (value - low) / (high - low) * plot_h,
            )
            for day, value in points
        ]
        page.polyline(coords, colour=colour, width=1.2)
        page.rect(legend_x, plot_top - 8, 7, 7, fill=colour)
        page.text(legend_x + 10, plot_top - 2, label, size=7.5, colour=MUTED)
        legend_x += 52

    for index in range(5):
        day = start + (end - start) * index / 4
        px = plot_x + plot_w * index / 4
        text = day.strftime("%b %Y") if span_days > 100 else day.strftime("%b %d")
        page.text(px - 14, plot_bottom + 12, text, size=7, colour=MUTED)


def _schematic_map(
    page: PdfPage,
    x: float,
    y: float,
    w: float,
    h: float,
    sites: tuple[ReportSite, ...],
    primary: ReportSite,
) -> None:
    page.text(x, y, "Locator map (schematic, no basemap)", size=10, bold=True, colour=INK)
    box_y = y + 14
    page.rect(x, box_y, w, h, fill=(0.94, 0.96, 0.99), stroke=RULE, width=0.7)
    points = [site.site for site in sites]
    lats = [site.latitude for site in points]
    lons = [site.longitude for site in points]
    lat_span = max(0.01, max(lats) - min(lats))
    lon_span = max(0.01, max(lons) - min(lons))
    scale = min((w - 50) / lon_span, (h - 40) / lat_span)
    cx = x + w / 2
    cy = box_y + h / 2
    mid_lat = (max(lats) + min(lats)) / 2
    mid_lon = (max(lons) + min(lons)) / 2
    for site in sites:
        px = cx + (site.site.longitude - mid_lon) * scale
        py = cy - (site.site.latitude - mid_lat) * scale
        is_primary = site.site.number == primary.site.number
        page.circle(px, py, 4.5 if is_primary else 3.0, fill=ACCENT if is_primary else (0.35, 0.55, 0.75))
        page.text(px + 6, py - 2, site.site.number, size=6.5, colour=INK)
    page.text(x + 8, box_y + h - 10, f"center {mid_lat:.3f}, {mid_lon:.3f}", size=7, colour=MUTED)
    page.text(x + w - 92, box_y + 12, "N", size=8, bold=True, colour=MUTED)
    page.line(x + w - 82, box_y + 22, x + w - 82, box_y + 10, colour=MUTED, width=0.8)


# --------------------------------------------------------------------------- #
# Report pages
# --------------------------------------------------------------------------- #
def _cover(document: PdfDocument, data: ReportData) -> PdfPage:
    page = document.add_page()
    page.rect(0, 0, PAGE_W, 96, fill=(0.10, 0.22, 0.36))
    page.text(MARGIN, 36, "StreamStudy", size=24, bold=True, colour=(1, 1, 1))
    page.text(MARGIN, 60, "Historical streamflow and temperature report", size=12, colour=(0.82, 0.89, 0.96))
    page.text(MARGIN, 78, "experimental - for exploration only", size=8.5, colour=(0.72, 0.82, 0.92))

    site = data.primary.site
    y = 126
    page.text(MARGIN, y, site.name, size=17, bold=True, colour=INK)
    y += 18
    page.text(MARGIN, y, f"USGS {site.number}  |  {site.latitude:.4f}, {site.longitude:.4f}", size=9, colour=MUTED)
    y += 22
    page.text(
        MARGIN,
        y,
        f"Window {data.window.start.isoformat()} to {data.window.end.isoformat()} "
        f"({data.window.days} days)",
        size=9.5,
        colour=INK,
    )
    y += 13
    mode = (
        f"Region report: every gage within {data.radius_km:g} km "
        f"({len(data.sites)} sites)"
        if data.region_mode
        else "Single-gage report"
    )
    page.text(MARGIN, y, f"{mode}  |  water-temperature threshold {data.threshold_c:g} C", size=9.5, colour=INK)
    y += 13
    page.text(
        MARGIN,
        y,
        f"Images generated {data.generated.strftime('%b %d, %Y %H:%M')}  |  "
        f"precipitation source: {data.primary.precip_source}",
        size=8.5,
        colour=MUTED,
    )

    y += 24
    page.rect(MARGIN, y, CONTENT_W, 66, fill=(1.0, 0.97, 0.90), stroke=(0.86, 0.72, 0.42), width=0.8)
    note = (
        "This is an experimental, human-prompted and LLM-implemented report. Daily means, "
        "empirical rainfall-runoff relationships and a handful of data sources cannot capture "
        "soil moisture, routing, regulation or sensor error. Treat every number as a screening "
        "estimate, not a forecast or a safety decision."
    )
    inner = _paragraph(page, MARGIN + 10, y + 14, 92, note, size=8.2, colour=(0.42, 0.30, 0.12), leading=10.5)
    page.text(MARGIN + 10, inner + 1, "Please verify against the primary agency record before using it.", size=7.5, italic=True, colour=(0.42, 0.30, 0.12))

    y += 84
    flow = summarise_flow(data.primary.flow, data.window.start, data.window.end)
    water = summarise_temperature(data.primary.water_temp, data.window.start, data.window.end, data.threshold_c)
    rain_summary, _rain_days = _rain_shape(data.primary.rain, data.window.start, data.window.end)
    card_w = (CONTENT_W - 18) / 3
    _card(
        page, MARGIN, y, card_w, 60, "Mean daily flow",
        _fmt(flow.mean, 1, " cfs"), f"median {_fmt(flow.median, 1)} cfs",
    )
    _card(
        page, MARGIN + card_w + 9, y, card_w, 60, "Peak daily flow",
        _fmt(flow.highest, 1, " cfs"), _fmt_day(flow.highest_day),
    )
    _card(
        page, MARGIN + 2 * (card_w + 9), y, card_w, 60, "Water above threshold",
        f"{water.days_above} days" if water.days else "no water temp",
        f"{water.hours_above:,.0f} h at {data.threshold_c:g} C",
    )
    y += 74
    page.text(
        MARGIN,
        y,
        f"Rain in window: {rain_summary.rain_total:.2f} in across {rain_summary.rain_days} days  |  "
        f"flow days: {flow.days}  |  water-temperature days: {water.days}",
        size=9,
        colour=INK,
    )

    y += 22
    _schematic_map(page, MARGIN, y, CONTENT_W, 150, data.sites, data.primary)

    y += 176
    if data.region_mode:
        y = _heading(page, y, "Sites in this report", size=11)
        rows = []
        for index, site_report in enumerate(data.sites, start=1):
            site_flow = summarise_flow(site_report.flow, data.window.start, data.window.end)
            temp = summarise_temperature(site_report.water_temp, data.window.start, data.window.end, data.threshold_c)
            fit = site_report.fit
            rows.append(
                [
                    str(index),
                    site_report.site.number,
                    f"{site_report.distance_km:.1f}",
                    str(site_flow.days),
                    _fmt(site_flow.mean, 0),
                    _fmt(site_flow.highest, 1),
                    str(temp.days),
                    f"{fit.r_squared:.2f}" if fit is not None else "n/a",
                ]
            )
        _table(
            page, MARGIN, y,
            [22, 74, 54, 42, 62, 62, 62, 52],
            ["#", "USGS site", "km", "flow d", "mean cfs", "peak cfs", "temp d", "fit r2"],
            rows, size=7.5, row_h=12.5,
        )
    else:
        y = _heading(page, y, "What is inside", size=11)
        for line in (
            "Flow hydrograph, distribution and the highest and lowest daily flows.",
            "Water and air temperature, time above the threshold and the warmest/coldest days.",
            "Air and sunshine correlations with water temperature, including MMW sensors.",
            "The storms that produced the largest rises, with the fitted response parameters.",
            "Sources, methods and honest limitations.",
        ):
            page.text(MARGIN + 4, y, "- " + line, size=9, colour=INK)
            y += 14
    _footer(page, 1)
    return page


def _flow_page(
    document: PdfDocument,
    data: ReportData,
    site_report: ReportSite,
    *,
    page_number: int,
    compact: bool,
) -> PdfPage:
    page = document.add_page()
    start, end = data.window.start, data.window.end
    flow = summarise_flow(site_report.flow, start, end)
    rain_summary, _ = _rain_shape(site_report.rain, start, end)
    heading = site_report.site.name if not compact else f"{site_report.site.name} - flow"
    page.text(MARGIN, 46, heading, size=14, bold=True, colour=INK)
    page.text(MARGIN, 61, f"USGS {site_report.site.number}  |  {start.isoformat()} to {end.isoformat()}", size=8.5, colour=MUTED)
    y = 78

    card_w = (CONTENT_W - 12) / 4
    _card(page, MARGIN, y, card_w, 52, "Mean / median", f"{_fmt(flow.mean, 1)} / {_fmt(flow.median, 1)}", "cfs")
    _card(page, MARGIN + card_w + 4, y, card_w, 52, "Lowest daily", _fmt(flow.lowest, 1), _fmt_day(flow.lowest_day))
    _card(page, MARGIN + 2 * (card_w + 4), y, card_w, 52, "Highest daily", _fmt(flow.highest, 1), _fmt_day(flow.highest_day))
    _card(page, MARGIN + 3 * (card_w + 4), y, card_w, 52, "Rain in window", f"{rain_summary.rain_total:.2f} in", f"{rain_summary.rain_days} wet days")
    y += 66

    _flow_chart(
        page, MARGIN, y, CONTENT_W, 190 if not compact else 150,
        site_report.flow, site_report.rain, start, end,
        "Daily mean flow and daily precipitation",
    )
    y += (218 if not compact else 176)

    if compact:
        page.text(
            MARGIN,
            y,
            f"10th-90th percentile: {_fmt(flow.p10, 1)} to {_fmt(flow.p90, 1)} cfs  |  "
            f"available flow days: {flow.days}",
            size=8.5,
            colour=INK,
        )
        y += 16
        high = extreme_days(site_report.flow, start, end, 3, highest=True)
        low = extreme_days(site_report.flow, start, end, 3, highest=False)
        rows = [
            [day.strftime("%Y-%m-%d"), f"{value:,.1f}", _fmt(site_report.rain.get(day), 2)]
            for day, value in high
        ]
        rows += [
            [day.strftime("%Y-%m-%d"), f"{value:,.1f}", _fmt(site_report.rain.get(day), 2)]
            for day, value in low
        ]
        _table(page, MARGIN, y, [80, 70, 60], ["Extreme day", "cfs", "rain in"], rows, size=8, row_h=12)
        y += 22 + 12 * len(rows)
        if site_report.errors:
            y = _heading(page, y + 6, "Data notes", size=9)
            for error in site_report.errors[:4]:
                page.text(MARGIN + 2, y, "- " + error[:105], size=7.5, colour=WARN)
                y += 11
    else:
        high = extreme_days(site_report.flow, start, end, 6, highest=True)
        low = extreme_days(site_report.flow, start, end, 6, highest=False)
        page.text(MARGIN, y, "Highest daily flows", size=10, bold=True, colour=INK)
        page.text(MARGIN + 230, y, "Lowest daily flows", size=10, bold=True, colour=INK)
        table_rows = []
        for index in range(max(len(high), len(low))):
            left = high[index] if index < len(high) else None
            right = low[index] if index < len(low) else None
            table_rows.append(
                [
                    left[0].strftime("%Y-%m-%d") if left else "",
                    f"{left[1]:,.1f}" if left else "",
                    _fmt(site_report.rain.get(left[0]), 2) if left else "",
                    right[0].strftime("%Y-%m-%d") if right else "",
                    f"{right[1]:,.1f}" if right else "",
                    _fmt(site_report.rain.get(right[0]), 2) if right else "",
                ]
            )
        y = _table(
            page, MARGIN, y + 8, [78, 58, 52, 90, 58, 52],
            ["Date", "cfs", "rain", "Date", "cfs", "rain"],
            table_rows, size=8, row_h=13,
        )
        y += 8
        page.text(
            MARGIN,
            y,
            f"Distribution: 10th percentile {_fmt(flow.p10, 1)} cfs, "
            f"90th percentile {_fmt(flow.p90, 1)} cfs. "
            f"Daily values are USGS statistic 00003 (mean of the day).",
            size=8.5,
            colour=INK,
        )
        y += 18
        if site_report.errors:
            y = _heading(page, y, "Data notes", size=9)
            for error in site_report.errors[:6]:
                page.text(MARGIN + 2, y, "- " + error[:110], size=7.5, colour=WARN)
                y += 11

    _footer(page, page_number)
    return page


def _temperature_page(
    document: PdfDocument,
    data: ReportData,
    site_report: ReportSite,
    *,
    page_number: int,
) -> PdfPage:
    page = document.add_page()
    start, end = data.window.start, data.window.end
    water = summarise_temperature(site_report.water_temp, start, end, data.threshold_c)
    air = summarise_temperature(site_report.air_mean, start, end, data.threshold_c)
    sunshine = summarise_temperature(site_report.sunshine, start, end, 0.0)

    page.text(MARGIN, 46, f"{site_report.site.name} - temperature", size=14, bold=True, colour=INK)
    page.text(MARGIN, 61, f"{start.isoformat()} to {end.isoformat()}  |  threshold {data.threshold_c:g} C", size=8.5, colour=MUTED)
    y = 78
    card_w = (CONTENT_W - 12) / 4
    _card(
        page, MARGIN, y, card_w, 52, "Water mean",
        _fmt(water.mean, 1, " C") if water.days else "no data",
        f"{water.days} daily means",
    )
    _card(
        page, MARGIN + card_w + 4, y, card_w, 52, "Water range",
        f"{_fmt(water.lowest, 1)} to {_fmt(water.highest, 1)}" if water.days else "n/a",
        "daily means (C)",
    )
    _card(
        page, MARGIN + 2 * (card_w + 4), y, card_w, 52, "Days above threshold",
        f"{water.days_above} days" if water.days else "n/a",
        f"{water.hours_above:,.0f} h total" if water.days else "",
    )
    _card(
        page, MARGIN + 3 * (card_w + 4), y, card_w, 52, "Longest warm run",
        f"{water.longest_run} days" if water.days else "n/a",
        "consecutive daily means",
    )
    y += 66

    _temperature_chart(
        page, MARGIN, y, CONTENT_W, 210,
        site_report.water_temp, site_report.air_mean, data.threshold_c,
        start, end, "Daily mean water temperature (USGS) and air temperature (ERA5)",
    )
    y += 238

    y = _heading(page, y, "Temperature statistics", size=10)
    rows = [
        [
            "Water (USGS daily mean)",
            _fmt(water.mean, 2),
            _fmt(water.lowest, 2),
            _fmt_day(water.lowest_day),
            _fmt(water.highest, 2),
            _fmt_day(water.highest_day),
            str(water.days_above),
            f"{water.hours_above:,.0f}",
        ],
        [
            "Air (ERA5 daily mean)",
            _fmt(air.mean, 2),
            _fmt(air.lowest, 2),
            _fmt_day(air.lowest_day),
            _fmt(air.highest, 2),
            _fmt_day(air.highest_day),
            str(air.days_above),
            f"{air.hours_above:,.0f}",
        ],
    ]
    y = _table(
        page, MARGIN, y, [122, 52, 52, 72, 52, 72, 48, 46],
        ["Series", "mean C", "min C", "min date", "max C", "max date", f"days >{data.threshold_c:g}", "hours"],
        rows, size=7.5, row_h=15,
    )
    y += 8
    y = _paragraph(
        page,
        MARGIN,
        y,
        100,
        "Water temperature is only available at some gages; air temperature and sunshine are "
        "modelled (ERA5) for every gage. Duration above the threshold uses daily means, so each "
        "qualifying day counts as 24 hours; this is a screening statistic, not a continuous "
        "integration.",
        size=8,
        colour=MUTED,
        leading=10.5,
    )
    y += 8

    y = _heading(page, y, "Warmest and coldest water days", size=10)
    warm = extreme_days(site_report.water_temp, start, end, 5, highest=True)
    cold = extreme_days(site_report.water_temp, start, end, 5, highest=False)
    rows = [
        [
            warm[index][0].strftime("%Y-%m-%d") if index < len(warm) else "",
            _fmt(warm[index][1], 1) if index < len(warm) else "",
            cold[index][0].strftime("%Y-%m-%d") if index < len(cold) else "",
            _fmt(cold[index][1], 1) if index < len(cold) else "",
        ]
        for index in range(max(len(warm), len(cold)))
    ]
    if rows:
        y = _table(
            page, MARGIN, y, [86, 64, 86, 64], ["Warmest day", "C", "Coldest day", "C"], rows, size=8, row_h=13,
        )
    else:
        page.text(MARGIN, y, "No daily water temperature for this gage in the window.", size=8.5, colour=MUTED)
        y += 14
    y += 8
    if sunshine.days:
        y = _paragraph(
            page,
            MARGIN,
            y,
            100,
            f"Sunshine: {sunshine.mean:.1f} h/day on average across {sunshine.days} days "
            "(ERA5 sunshine duration). Compare warm, clear days with air temperature on the "
            "Temperature tab.",
            size=8.5,
            colour=INK,
            leading=11,
        )
        y += 4

    fit = site_report.fit
    if fit is not None:
        y = _heading(page, y + 6, "Rainfall to flow response", size=10)
        page.text(
            MARGIN,
            y,
            f"{fit.events} storms  |  {fit.slope:,.1f} cfs per inch  |  "
            f"median lag {fit.lag_p50_hours:.0f} h (10-90: {fit.lag_p10_hours:.0f}-{fit.lag_p90_hours:.0f} h)  |  "
            f"recession half-life {fit.half_life_days:.1f} days  |  r2 {fit.r_squared:.2f}  |  "
            f"confidence {fit.confidence}",
            size=8.5,
            colour=INK,
        )
        y += 16
        events = sorted(site_report.events, key=lambda event: event.rain_in, reverse=True)[:5]
        rows = [
            [
                event.start.strftime("%Y-%m-%d"),
                f"{event.rain_in:.2f}",
                f"{event.peak_cfs:,.0f}",
                f"+{event.rise_cfs:,.0f}",
                f"{event.lag_hours:.0f}",
                _fmt(event.half_life_days, 1),
            ]
            for event in events
        ]
        if rows:
            _table(
                page, MARGIN, y, [82, 62, 70, 66, 54, 64],
                ["Storm start", "rain in", "peak cfs", "rise cfs", "lag h", "half-life d"],
                rows, size=7.5, row_h=11,
            )
    _footer(page, page_number)
    return page


def _thermal_sources(site_report: ReportSite) -> list[WaterSource]:
    sources: list[WaterSource] = []
    history = site_report.history
    water = getattr(history, "water_temp_daily", {}) or {}
    if water:
        sources.append(WaterSource("usgs", "USGS 00010", dict(water)))
    if site_report.mmw_temp_daily:
        name = site_report.mmw_name or "sensor"
        sources.append(
            WaterSource(
                "mmw",
                f"MMW {name}",
                dict(site_report.mmw_temp_daily),
                note="recent record only",
                recent_only=True,
            )
        )
    return sources


def _signed_range(values: list[float]) -> tuple[float, float]:
    low, high = min(values), max(values)
    if high - low < 1e-9:
        low -= 1.0
        high += 1.0
    pad = (high - low) * 0.08
    return low - pad, high + pad


def _thermal_scatter(
    page: PdfPage,
    x: float,
    y: float,
    w: float,
    h: float,
    fit: DriverFit,
    *,
    title: str,
    x_label: str,
) -> None:
    page.text(x, y, title, size=9, bold=True, colour=INK)
    plot_x, plot_top = x + 34, y + 14
    plot_w = w - 40
    plot_bottom = y + h - 26
    plot_h = plot_bottom - plot_top
    points = _decimate([(float(px), float(py)) for px, py in fit.points], 320)
    page.line(plot_x, plot_bottom, plot_x + plot_w, plot_bottom, colour=RULE, width=0.7)
    page.line(plot_x, plot_top, plot_x, plot_bottom, colour=RULE, width=0.7)
    if len(points) < 2:
        page.text(
            plot_x + 6,
            plot_top + plot_h / 2,
            "No paired daily values in this window",
            size=8,
            colour=MUTED,
        )
        return

    xmin, xmax = _signed_range([point[0] for point in points])
    ymin, ymax = _signed_range([point[1] for point in points])
    xstep = nice_step(xmax - xmin, 4)
    ystep = nice_step(ymax - ymin, 4)

    for index in range(5):
        fraction = index / 4.0
        value = ymin + fraction * (ymax - ymin)
        grid_y = plot_bottom - fraction * plot_h
        page.line(
            plot_x,
            grid_y,
            plot_x + plot_w,
            grid_y,
            colour=(0.90, 0.91, 0.93),
            width=0.5,
        )
        page.text(plot_x - 3, grid_y + 2.5, _fmt(value, 0), size=6.5, colour=MUTED)
    for index in range(5):
        fraction = index / 4.0
        value = xmin + fraction * (xmax - xmin)
        grid_x = plot_x + fraction * plot_w
        page.line(
            grid_x,
            plot_top,
            grid_x,
            plot_bottom,
            colour=(0.90, 0.91, 0.93),
            width=0.5,
        )
        page.text(grid_x - 8, plot_bottom + 9, _fmt(value, 1), size=6.5, colour=MUTED)

    def px(value: float) -> float:
        return plot_x + (value - xmin) / (xmax - xmin) * plot_w

    def py(value: float) -> float:
        return plot_bottom - (value - ymin) / (ymax - ymin) * plot_h

    if xmin < 0 < xmax:
        page.line(px(0), plot_top, px(0), plot_bottom, colour=RULE, width=0.7)
    if ymin < 0 < ymax:
        page.line(plot_x, py(0), plot_x + plot_w, py(0), colour=RULE, width=0.7)
    if fit.fit is not None:
        page.line(
            px(fit.fit[0][0]),
            py(fit.fit[0][1]),
            px(fit.fit[1][0]),
            py(fit.fit[1][1]),
            colour=ACCENT,
            width=1.0,
        )
    for point_x, point_y in points:
        page.circle(px(point_x), py(point_y), 1.2, fill=(0.25, 0.55, 0.85))
    page.text(plot_x + plot_w, plot_bottom + 22, x_label, size=6.5, colour=MUTED)
    page.text(plot_x - 24, plot_top - 3, "water C", size=6.5, colour=MUTED)


def _thermal_page(
    document: PdfDocument,
    data: ReportData,
    site_report: ReportSite,
    *,
    page_number: int,
) -> PdfPage:
    page = document.add_page()
    start, end = data.window.start, data.window.end
    sources = _thermal_sources(site_report)
    analyses = [
        (
            source,
            build_thermal_analysis(
                source.daily,
                site_report.air_mean,
                site_report.sunshine,
                max_lag=5,
                min_pairs=5,
            ),
        )
        for source in sources
    ]
    primary_source, primary = analyses[0] if analyses else (None, None)

    page.text(
        MARGIN,
        46,
        site_report.site.name,
        size=14,
        bold=True,
        colour=INK,
    )
    page.text(
        MARGIN,
        61,
        f"Temperature correlations  |  {start.isoformat()} to {end.isoformat()}  |  "
        "water vs air and sunshine",
        size=8.5,
        colour=MUTED,
    )
    y = 78
    card_w = (CONTENT_W - 12) / 4
    if primary is not None:
        air = primary.air.best
        sun = primary.sun.best
    else:
        air = sun = None
    _card(
        page,
        MARGIN,
        y,
        card_w,
        52,
        "Air -> water",
        f"r {air.r:+.2f}" if air is not None else "n/a",
        f"lag {air.lag_days:+d} d  n {air.n}" if air is not None else "no paired days",
    )
    _card(
        page,
        MARGIN + card_w + 4,
        y,
        card_w,
        52,
        "Sunshine -> water",
        f"r {sun.r:+.2f}" if sun is not None else "n/a",
        f"lag {sun.lag_days:+d} d  n {sun.n}" if sun is not None else "no paired days",
    )
    _card(
        page,
        MARGIN + 2 * (card_w + 4),
        y,
        card_w,
        52,
        "Water sources",
        str(len(sources)),
        (
            " + ".join("USGS" if source.key == "usgs" else "MMW" for source in sources)
            if sources
            else "none"
        ),
    )
    _card(
        page,
        MARGIN + 3 * (card_w + 4),
        y,
        card_w,
        52,
        "Water days",
        f"{primary.water_days:,}" if primary is not None else "0",
        primary_source.label if primary_source is not None else "no water record",
    )
    y += 66

    half = (CONTENT_W - 12) / 2
    _thermal_scatter(
        page,
        MARGIN,
        y,
        half,
        185,
        primary.air if primary is not None else DriverFit(driver="air temperature"),
        title="Water vs air temperature",
        x_label="air C",
    )
    _thermal_scatter(
        page,
        MARGIN + half + 12,
        y,
        half,
        185,
        primary.sun if primary is not None else DriverFit(driver="sunshine"),
        title="Water vs sunshine",
        x_label="sunshine h",
    )
    y += 203

    y = _heading(page, y, "Correlation summary", size=10)
    rows = []
    for source, analysis in analyses:
        fits = [
            analysis.air,
            analysis.sun,
            analysis.air_anomaly,
            analysis.sun_anomaly,
        ]
        for fit in fits:
            if fit is None:
                continue
            best = fit.best
            rows.append(
                [
                    source.label[:34],
                    fit.driver,
                    f"{best.r:+.2f}" if best is not None else "n/a",
                    f"{best.lag_days:+d}" if best is not None else "n/a",
                    str(best.n) if best is not None else "0",
                    fit.confidence,
                ]
            )
    if rows:
        y = _table(
            page,
            MARGIN,
            y,
            [168, 88, 50, 44, 40, 70],
            ["Water source", "Driver", "Best r", "Lag d", "Pairs", "Confidence"],
            rows,
            size=7.5,
            row_h=12,
        )
    else:
        page.text(
            MARGIN,
            y,
            "No daily water temperature for USGS or Monitor My Watershed in this window.",
            size=8.5,
            colour=MUTED,
        )
        y += 16

    if primary is not None:
        y += 4
        y = _heading(page, y, "Correlation by lag", size=10)
        air_rows = {lag: (r, n) for lag, r, n in primary.air.by_lag}
        sun_rows = {lag: (r, n) for lag, r, n in primary.sun.by_lag}
        lag_rows = []
        for lag in range(-5, 6):
            air_r, air_n = air_rows.get(lag, (None, 0))
            sun_r, sun_n = sun_rows.get(lag, (None, 0))
            lag_rows.append(
                [
                    f"{lag:+d}" if lag else "0",
                    f"{air_r:+.2f}" if air_r is not None else "n/a",
                    str(air_n),
                    f"{sun_r:+.2f}" if sun_r is not None else "n/a",
                    str(sun_n),
                ]
            )
        y = _table(
            page,
            MARGIN,
            y,
            [58, 64, 52, 64, 52],
            ["Lag (d)", "Air r", "Air n", "Sun r", "Sun n"],
            lag_rows,
            size=7.5,
            row_h=10.5,
        )
        y += 6
        page.text(
            MARGIN,
            y,
            "Positive lag means water temperature follows the driver. Pearson r on daily means; "
            "correlation is not causation and the drivers are gridded weather estimates.",
            size=8,
            colour=MUTED,
        )
    else:
        page.text(
            MARGIN,
            y,
            "Air temperature and sunshine are unavailable, so no correlations can be computed.",
            size=8.5,
            colour=MUTED,
        )

    if primary_source is not None:
        _sunlight_comparison(page, data, site_report, primary_source, y)

    _footer(page, page_number)
    return page


def _sunlight_comparison(
    page: PdfPage,
    data: ReportData,
    site_report: ReportSite,
    primary_source: WaterSource,
    y: float,
) -> None:
    """Rank the primary gage and its region peers by sunlight-driven water rise."""
    peers = []
    for other in data.region:
        sources = _thermal_sources(other)
        if not sources:
            continue
        source = sources[0]
        peers.append(
            (
                other.site.number,
                other.site.name,
                haversine_km(
                    site_report.site.latitude,
                    site_report.site.longitude,
                    other.site.latitude,
                    other.site.longitude,
                ),
                source.daily,
                other.air_mean,
                other.sunshine,
                "",
            )
        )
    if not peers:
        page.text(
            MARGIN,
            y + 6,
            "Region comparison: generate a region report (with a radius) to compare sunlight "
            "sensitivity across nearby streams.",
            size=8,
            colour=MUTED,
        )
        return

    ranked = sunlight_peers(
        site_report.site.number,
        site_report.site.name,
        primary_source.daily,
        site_report.air_mean,
        site_report.sunshine,
        peers,
    )
    rows = [
        peer
        for peer in ranked
        if peer.slope_c_per_hour is not None or peer.this_site or peer.error
    ]
    heading_h = 18
    note_h = 24
    room = PAGE_H - 40 - y - heading_h - note_h
    capacity = int(room // 12)
    rows = rows[: max(0, capacity)]
    if len(rows) < 1:
        return
    y = _heading(page, y, "Sunlight sensitivity across the region", size=10)
    table_rows = []
    for peer in rows:
        name = peer.name[:30] + (" (this gage)" if peer.this_site else "")
        if peer.error:
            table_rows.append(
                [peer.site_number, f"{name} \u2014 {peer.error[:36]}", "", "", "", "", ""]
            )
            continue
        table_rows.append(
            [
                peer.site_number,
                name,
                f"{peer.distance_km:.0f}",
                f"{peer.sun_r:+.2f}" if peer.sun_r is not None else "n/a",
                f"{peer.air_r:+.2f}" if peer.air_r is not None else "n/a",
                (
                    f"{peer.slope_c_per_hour:+.2f}"
                    if peer.slope_c_per_hour is not None
                    else "n/a"
                ),
                f"{peer.lag_days:+d}" if peer.lag_days is not None else "n/a",
            ]
        )
    y = _table(
        page,
        MARGIN,
        y,
        [66, 148, 40, 48, 48, 64, 46],
        ["Site", "Name", "km", "Sun r", "Air r", "C/sun-h", "Lag d"],
        table_rows,
        size=7.5,
        row_h=12,
    )
    _paragraph(
        page,
        MARGIN,
        y + 6,
        118,
        "Rise over normal: slope is \u00b0C of water-temperature rise per sunshine-hour above "
        "each stream's own rolling normal, strongest first. Correlation is not causation.",
        size=8,
        colour=MUTED,
        leading=10.5,
    )


def _references_page(document: PdfDocument, data: ReportData, *, page_number: int) -> PdfPage:
    page = document.add_page()
    y = 46
    y = _heading(page, y, "Sources, methods and limitations", size=14)
    y += 4
    text = (
        "Streamflow and water temperature: USGS National Water Information System daily values, "
        "parameter 00060 (discharge, cfs) and 00010 (water temperature, C), statistic 00003 "
        "(daily mean). https://waterdata.usgs.gov/"
    )
    y = _paragraph(page, MARGIN, y, 104, text, size=9, leading=12.5) + 4
    text = (
        "Precipitation: CoCoRaHS volunteer gauge totals when a station with adequate coverage was "
        "available, otherwise the Open-Meteo ERA5 reanalysis archive. CoCoRaHS reports 24-hour "
        "totals around 7 AM local time; ERA5 is a gridded model product. Neither is an on-site "
        "tipping bucket at the gage. https://www.cocorahs.org/  |  https://open-meteo.com/"
    )
    y = _paragraph(page, MARGIN, y, 104, text, size=9, leading=12.5) + 4
    text = (
        "Air temperature and sunshine: Open-Meteo ERA5 archive (daily mean/max/min temperature and "
        "sunshine duration). Streamflow forecasts elsewhere in the app blend NWS QPF with Open-Meteo; "
        "this historical report does not include a forecast."
    )
    y = _paragraph(page, MARGIN, y, 104, text, size=9, leading=12.5) + 4
    text = (
        "Temperature correlations: USGS daily water temperature and nearby Monitor My Watershed "
        "sensor means (recent record only) are paired with daily air temperature and sunshine at "
        "lags from -5 to +5 days. The report shows Pearson r at the best absolute lag and the full "
        "lag curve. A positive lag means water temperature follows the driver. Correlation is not "
        "causation; the drivers are gridded weather estimates, not gauges at the creek."
    )
    y = _paragraph(page, MARGIN, y, 104, text, size=9, leading=12.5) + 4
    text = (
        "Rise over normal: absolute temperature correlations mostly track the seasonal cycle, so "
        "each series is also reduced to its departure from a centred 15-day rolling mean and "
        "refitted. Those anomaly rows (and the sunlight-sensitivity table, which ranks streams by "
        "\u00b0C of water rise per sunshine-hour above normal) describe day-to-day drivers rather than "
        "seasons. On short windows the rolling normal removes much of the variation, so treat the "
        "anomaly results as a screening heuristic."
    )
    y = _paragraph(page, MARGIN, y, 104, text, size=9, leading=12.5) + 4
    text = (
        "Storm response: storms are days with at least 0.10 in of precipitation; baseflow is a "
        "smoothed 7-day rolling minimum; a rise is the peak above baseflow within four days. The "
        "fitted rate, lag percentiles and recession half-life are descriptive summaries of observed "
        "events, not physically calibrated parameters."
    )
    y = _paragraph(page, MARGIN, y, 104, text, size=9, leading=12.5) + 8

    y = _heading(page, y, "Health warnings", size=11)
    warnings = [
        "Daily means hide short, intense peaks. A one-day mean can be far below the true crest.",
        "Rating curves, ice, debris and instrument faults produce bad values that are not always flagged.",
        "Precipitation is point-in-space or gridded, while a basin integrates over its whole area.",
        "Snowmelt, soil moisture, reservoirs, diversions and groundwater are not modelled.",
        "Air temperature is not water temperature; do not use one as a proxy for the other.",
        "This app and report are experimental and were built by an LLM from human prompts.",
    ]
    for warning in warnings:
        page.text(MARGIN + 4, y, "- " + warning, size=9, colour=INK)
        y += 14

    y += 8
    y = _heading(page, y, "Reproduce this report", size=11)
    text = (
        "StreamStudy is a public, standard-library-only Python app. Set the same analysis window, "
        "temperature threshold and (for a region report) radius, then choose File > Generate PDF "
        "report. https://github.com/llascari/RFD_LL_StreamStudy"
    )
    y = _paragraph(page, MARGIN, y, 104, text, size=9, leading=12.5)

    if data.failures:
        y += 6
        y = _heading(page, y, "Sites that could not be loaded", size=10)
        for failure in data.failures:
            page.text(MARGIN + 4, y, "- " + failure[:112], size=8, colour=WARN)
            y += 11

    _footer(page, page_number)
    return page


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def write_report(data: ReportData, path: str | Path) -> Path:
    """Render ``data`` to a multi-page PDF and return the written path."""
    document = PdfDocument(title=f"StreamStudy report - {data.primary.site.number}")
    _cover(document, data)
    _flow_page(document, data, data.primary, page_number=2, compact=False)
    _temperature_page(document, data, data.primary, page_number=3)
    _thermal_page(document, data, data.primary, page_number=4)
    number = 5
    for site_report in data.region:
        _flow_page(document, data, site_report, page_number=number, compact=True)
        number += 1
        _temperature_page(document, data, site_report, page_number=number)
        number += 1
        _thermal_page(document, data, site_report, page_number=number)
        number += 1
    _references_page(document, data, page_number=number)
    return document.save(path)
