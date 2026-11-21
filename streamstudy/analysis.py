"""Pure helpers that turn raw series into the numbers the UI shows."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, tzinfo

from .models import Series, SeriesStats


def mm_to_inches(value: float) -> float:
    return value / 25.4


def inches_to_mm(value: float) -> float:
    return value * 25.4


def local_day(moment: datetime, tz: tzinfo | None = None) -> date:
    if tz is None:
        return moment.astimezone().date()
    return moment.astimezone(tz).date()


def sum_by_day(samples, tz: tzinfo | None = None, *, scale: float = 1.0) -> dict[date, float]:
    """Sum incremental samples into local-day totals."""
    totals: dict[date, float] = {}
    for sample in samples:
        if sample.value is None:
            continue
        day = local_day(sample.time, tz)
        totals[day] = totals.get(day, 0.0) + sample.value * scale
    return totals


def pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient; 0.0 when either series is flat."""
    count = len(xs)
    if count < 2 or count != len(ys):
        return 0.0
    # fsum keeps a constant series exactly constant (plain sum drifts on
    # Python 3.10/3.11 and leaves ~1e-15 correlation noise).
    mean_x = math.fsum(xs) / count
    mean_y = math.fsum(ys) / count
    covariance = math.fsum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = math.sqrt(math.fsum((x - mean_x) ** 2 for x in xs))
    var_y = math.sqrt(math.fsum((y - mean_y) ** 2 for y in ys))
    if var_x < 1e-12 or var_y < 1e-12:
        return 0.0
    return covariance / (var_x * var_y)


def series_stats(series: Series) -> SeriesStats | None:
    values = [sample.value for sample in series.valid]
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    median = ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return SeriesStats(
        count=count,
        minimum=ordered[0],
        maximum=ordered[-1],
        mean=sum(ordered) / count,
        median=median,
        latest=values[-1],
    )


def trend_per_hour(series: Series, hours: float = 6.0) -> float | None:
    """Rate of change over the last ``hours``, in units per hour."""
    valid = series.valid
    if len(valid) < 2:
        return None
    latest = valid[-1]
    cutoff = latest.time - timedelta(hours=hours)
    earlier = None
    for sample in valid:
        if sample.time >= cutoff:
            earlier = sample
            break
    if earlier is None or earlier is latest:
        return None
    span = (latest.time - earlier.time).total_seconds() / 3600.0
    if span <= 0:
        return None
    return (latest.value - earlier.value) / span


def trend_label(rate: float | None, units: str = "") -> str:
    if rate is None:
        return "no trend"
    if abs(rate) < 1e-9:
        return "steady"
    arrow = "\u25b2" if rate > 0 else "\u25bc"
    return f"{arrow} {abs(rate):.2f} {units}/h"


def recent_days(count: int, end: date | None = None) -> list[date]:
    end = end or date.today()
    return [end - timedelta(days=offset) for offset in range(count - 1, -1, -1)]


def totals_for_window(daily: dict[date, float], days: int, end: date | None = None) -> float:
    window = set(recent_days(days, end))
    return sum(value for day, value in daily.items() if day in window)


def precip_table(
    sources: dict[str, dict[date, float]], days: int, end: date | None = None
) -> list[tuple[date, dict[str, float | None]]]:
    """Rows of (day, {source: inches}) across the requested window."""
    window = recent_days(days, end)
    rows = []
    for day in window:
        rows.append((day, {name: series.get(day) for name, series in sources.items()}))
    return rows


def nice_step(span: float, target: int = 5) -> float:
    """A round tick step covering ``span`` in roughly ``target`` steps."""
    if span <= 0:
        return 1.0
    raw = span / max(1, target)
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 2.5, 5, 10):
        if raw <= multiple * magnitude:
            return multiple * magnitude
    return 10 * magnitude


def format_value(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "\u2014"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 100:
        return f"{value:.1f}"
    return f"{value:.{digits}f}"


def bundle_precip_sources(bundle, tz: tzinfo | None = None) -> dict[str, dict[date, float]]:
    """Daily precipitation in inches from every source that has data."""
    sources: dict[str, dict[date, float]] = {}
    usgs_precip = bundle.usgs.get("00045")
    if usgs_precip and usgs_precip.valid:
        sources["usgs"] = sum_by_day(usgs_precip.samples, tz)
    if bundle.coco_daily:
        sources["cocorahs"] = dict(bundle.coco_daily)
    if bundle.openmeteo_daily:
        sources["openmeteo"] = {
            day: mm_to_inches(mm) for day, mm in bundle.openmeteo_daily
        }
    if bundle.nws_precip and bundle.nws_precip.valid:
        sources["nws"] = sum_by_day(bundle.nws_precip.samples, tz)
    return sources
