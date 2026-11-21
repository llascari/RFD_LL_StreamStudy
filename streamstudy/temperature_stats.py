"""Water-temperature duration statistics.

Two resolutions are used, matching what the sources provide:

* high-frequency USGS IV samples for the last day/week (interval integration,
  capped to avoid over-counting gaps), and
* USGS daily means for the month/year windows.

Both return hours above a threshold plus the share of the window, which is the
practical way to compare "how warm was it" across seasons.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .models import Sample, WeatherDay


@dataclass(frozen=True)
class ThresholdWindow:
    label: str
    hours: float
    window_hours: float
    percent: float


def hours_above(
    samples,
    threshold_c: float,
    start: datetime,
    end: datetime,
    *,
    max_gap_hours: float = 2.0,
) -> float:
    """Integrate time above the threshold, capping sensor gaps."""
    points = sorted(
        (
            sample
            for sample in samples
            if sample.value is not None and start <= sample.time <= end
        ),
        key=lambda sample: sample.time,
    )
    if len(points) < 2:
        return 0.0
    total = 0.0
    for first, second in zip(points, points[1:]):
        gap = (second.time - first.time).total_seconds() / 3600.0
        if gap <= 0:
            continue
        if (first.value + second.value) / 2.0 > threshold_c:
            total += min(gap, max_gap_hours)
    return total


def hours_above_daily(
    daily: dict[date, float], threshold_c: float, start: date, end: date
) -> float:
    """Daily means above the threshold, counted as 24 h each."""
    return (
        24.0
        * sum(
            1
            for day, value in daily.items()
            if start <= day <= end and value > threshold_c
        )
    )


def threshold_windows(
    samples,
    daily: dict[date, float],
    threshold_c: float,
    now: datetime | None = None,
) -> list[ThresholdWindow]:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone().date()
    windows = (
        ("24 h", 1),
        ("7 days", 7),
        ("30 days", 30),
        ("1 year", 365),
    )
    stats: list[ThresholdWindow] = []
    for label, days in windows:
        window_hours = days * 24.0
        start = now - timedelta(days=days)
        hours = 0.0
        if days <= 7:
            hours = hours_above(samples, threshold_c, start, now)
        if hours <= 0 or days > 7:
            hours = hours_above_daily(daily, threshold_c, start.date(), today)
        hours = min(hours, window_hours)
        stats.append(
            ThresholdWindow(
                label=label,
                hours=hours,
                window_hours=window_hours,
                percent=100.0 * hours / window_hours if window_hours else 0.0,
            )
        )
    return stats


def clear_days(
    weather: tuple[WeatherDay, ...], days: int, cloud_threshold: float = 25.0
) -> int:
    cutoff = date.today() - timedelta(days=max(1, days) - 1)
    return sum(
        1
        for day in weather
        if day.day >= cutoff
        and day.cloud_pct is not None
        and day.cloud_pct <= cloud_threshold
    )
