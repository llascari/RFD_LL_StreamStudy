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


@dataclass(frozen=True)
class WindowSummary:
    window_start: date
    window_end: date
    hours: float
    percent: float
    days_above: int
    mean_c: float | None
    max_c: float | None
    source: str


def summarize_window(
    samples,
    daily: dict[date, float],
    threshold_c: float,
    window_start: date,
    window_end: date,
) -> WindowSummary:
    """Duration above the threshold inside an arbitrary date window."""
    tz = datetime.now().astimezone().tzinfo
    start_dt = datetime.combine(window_start, datetime.min.time(), tzinfo=tz)
    end_dt = datetime.combine(
        window_end + timedelta(days=1), datetime.min.time(), tzinfo=tz
    )
    window_days = max(1, (window_end - window_start).days + 1)
    window_hours = window_days * 24.0

    in_window = [
        sample
        for sample in samples
        if sample.value is not None and start_dt <= sample.time < end_dt
    ]
    use_samples = window_days <= 7 and len(in_window) >= window_days * 12
    if use_samples:
        hours = hours_above(in_window, threshold_c, start_dt, end_dt)
        source = f"{len(in_window)} samples"
    else:
        hours = hours_above_daily(daily, threshold_c, window_start, window_end)
        source = f"{sum(1 for d in daily if window_start <= d <= window_end)} daily means"
    hours = min(hours, window_hours)

    values = [value for day, value in daily.items() if window_start <= day <= window_end]
    if not values and in_window:
        values = [float(sample.value) for sample in in_window]
    days_above = sum(
        1 for day, value in daily.items() if window_start <= day <= window_end and value > threshold_c
    )
    return WindowSummary(
        window_start=window_start,
        window_end=window_end,
        hours=hours,
        percent=100.0 * hours / window_hours,
        days_above=days_above,
        mean_c=sum(values) / len(values) if values else None,
        max_c=max(values) if values else None,
        source=source,
    )


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
