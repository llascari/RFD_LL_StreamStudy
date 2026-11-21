"""Empirical rainfall-runoff response: history in, first-order forecast out.

The model is deliberately simple and transparent:

1. Separate baseflow with a rolling 7-day minimum (smoothed, clamped to flow).
2. Detect storms (>= 0.10 in) and measure the rise above baseflow, the lag from
   the storm's rain centroid to the peak, and the post-peak recession half-life.
3. Fit a response rate (cfs per inch, through the origin) and the 10th/50th/90th
   percentiles of the observed rise-per-inch ratios.
4. For a forecast hyetograph, predict a peak from that ratio, time the peak with
   the median lag, and draw a smooth rise followed by an exponential recession.

This is a first-order estimate: daily means, no soil-moisture state, no routing.
The 10-90 percentile band is the honest expression of that uncertainty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from .analysis import mm_to_inches, pearson
from .models import DataBundle, FlowEvent, ResponseFit, Series, utc_now

MIN_RAIN_IN = 0.10
RESPONSE_DAYS = 4


# --------------------------------------------------------------------------- #
# small statistics helpers
# --------------------------------------------------------------------------- #
def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * max(0.0, min(1.0, fraction))
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


# --------------------------------------------------------------------------- #
# baseflow and event detection
# --------------------------------------------------------------------------- #
def baseflow(flow: dict[date, float], window: int = 7) -> dict[date, float]:
    """Rolling-minimum baseflow, lightly smoothed and never above the flow."""
    days = sorted(flow)
    rolling: dict[date, float] = {}
    for index, day in enumerate(days):
        start = max(0, index - window + 1)
        rolling[day] = min(flow[d] for d in days[start : index + 1])
    smoothed: dict[date, float] = {}
    for index, day in enumerate(days):
        neighbours = days[max(0, index - 1) : index + 2]
        average = sum(rolling[d] for d in neighbours) / len(neighbours)
        smoothed[day] = min(flow[day], average)
    return smoothed


def _recession_half_life(
    flow: dict[date, float],
    base: dict[date, float],
    peak_day: date,
    days: list[date],
    max_days: int = 7,
) -> float | None:
    peak_excess = flow[peak_day] - base[peak_day]
    if peak_excess <= 0:
        return None
    points: list[tuple[float, float]] = []
    threshold = max(0.5, 0.02 * flow[peak_day])
    for day in days:
        if not peak_day < day <= peak_day + timedelta(days=max_days):
            continue
        excess = flow[day] - base[day]
        if excess > threshold:
            points.append(((day - peak_day).days, math.log(excess)))
    if len(points) < 2:
        return None
    mean_x = sum(p[0] for p in points) / len(points)
    mean_y = sum(p[1] for p in points) / len(points)
    denominator = sum((p[0] - mean_x) ** 2 for p in points)
    if denominator == 0:
        return None
    slope = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / denominator
    if slope >= 0:
        return None
    half_life = math.log(2) / -slope
    # Recessions longer than ~2 weeks are usually baseflow artefacts, not signal.
    if not math.isfinite(half_life) or not 0.05 <= half_life <= 15.0:
        return None
    return half_life


def _centroid(storm: list[date], precip: dict[date, float]) -> float:
    weights = [(day, precip.get(day, 0.0)) for day in storm if precip.get(day, 0.0) > 0]
    total = sum(weight for _day, weight in weights)
    if total <= 0:
        return datetime.combine(storm[0], time(12)).timestamp()
    return (
        sum(weight * datetime.combine(day, time(12)).timestamp() for day, weight in weights)
        / total
    )


def detect_events(
    flow: dict[date, float],
    precip: dict[date, float],
    *,
    min_rain: float = MIN_RAIN_IN,
    response_days: int = RESPONSE_DAYS,
    min_rise: float = 1.0,
    min_relative_rise: float = 0.03,
) -> list[FlowEvent]:
    """Pair storms with the flow peak that follows them."""
    days = sorted(set(flow) & set(precip))
    if len(days) < 10:
        return []
    base = baseflow({day: flow[day] for day in days})
    events: list[FlowEvent] = []
    index = 0
    while index < len(days):
        day = days[index]
        if precip[day] < 0.01:
            index += 1
            continue

        storm = [day]
        index += 1
        while (
            index < len(days)
            and days[index] == storm[-1] + timedelta(days=1)
            and precip[days[index]] >= 0.01
        ):
            storm.append(days[index])
            index += 1

        rain_total = sum(precip[d] for d in storm)
        if rain_total < min_rain:
            continue

        end_day = storm[-1]
        window = [
            d for d in days if end_day <= d <= end_day + timedelta(days=response_days)
        ]
        if not window:
            continue

        peak_day = max(window, key=lambda d: flow[d])
        baseline = base[storm[0]]
        peak = flow[peak_day]
        rise = peak - baseline
        if rise < max(min_rise, min_relative_rise * max(baseline, 1e-6)):
            continue

        centroid = _centroid(storm, precip)
        peak_time = datetime.combine(peak_day, time(12)).timestamp()
        lag_hours = (peak_time - centroid) / 3600.0

        events.append(
            FlowEvent(
                start=storm[0],
                end=end_day,
                rain_in=rain_total,
                rain_days=len(storm),
                baseline_cfs=baseline,
                peak_cfs=peak,
                peak_date=peak_day,
                rise_cfs=rise,
                lag_hours=lag_hours,
                half_life_days=_recession_half_life(flow, base, peak_day, days),
            )
        )
    return events


# --------------------------------------------------------------------------- #
# fit
# --------------------------------------------------------------------------- #
def fit_response(events: list[FlowEvent]) -> ResponseFit | None:
    usable = [event for event in events if event.rain_in > 0 and event.rise_cfs > 0]
    if len(usable) < 3:
        return None

    denominator = sum(event.rain_in**2 for event in usable)
    slope = (
        sum(event.rain_in * event.rise_cfs for event in usable) / denominator
        if denominator
        else 0.0
    )
    ratios = sorted(event.rise_cfs / event.rain_in for event in usable)
    logs_x = [math.log(event.rain_in) for event in usable]
    logs_y = [math.log(event.rise_cfs) for event in usable]
    r_squared = max(0.0, pearson(logs_x, logs_y)) ** 2

    lags = sorted(event.lag_hours for event in usable)
    half_lives = [
        event.half_life_days for event in usable if event.half_life_days is not None
    ]
    half_life = percentile(half_lives, 0.5) if half_lives else 1.0
    if not math.isfinite(half_life) or half_life <= 0:
        half_life = 1.0

    if r_squared >= 0.55 and len(usable) >= 12:
        confidence = "moderate"
    elif r_squared >= 0.30 and len(usable) >= 6:
        confidence = "low to moderate"
    else:
        confidence = "low"

    return ResponseFit(
        events=len(usable),
        slope=slope,
        ratio_p10=percentile(ratios, 0.10),
        ratio_p50=percentile(ratios, 0.50),
        ratio_p90=percentile(ratios, 0.90),
        r_squared=r_squared,
        lag_p50_hours=percentile(lags, 0.50),
        lag_p10_hours=percentile(lags, 0.10),
        lag_p90_hours=percentile(lags, 0.90),
        half_life_days=half_life,
        confidence=confidence,
    )


def analyse_history(
    flow: dict[date, float], precip: dict[date, float]
) -> tuple[list[FlowEvent], ResponseFit | None]:
    events = detect_events(flow, precip)
    return events, fit_response(events)


# --------------------------------------------------------------------------- #
# forecast scenario and prediction
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Scenario:
    """Rain increments (time of interval centre, inches) for the next hours."""

    increments: tuple[tuple[datetime, float], ...]
    total_in: float

    def centroid(self) -> datetime:
        total = sum(value for _moment, value in self.increments)
        if total <= 0:
            return utc_now()
        moment = (
            sum(moment.timestamp() * value for moment, value in self.increments) / total
        )
        return datetime.fromtimestamp(moment, tz=timezone.utc)


@dataclass(frozen=True)
class Prediction:
    rain_in: float
    current_cfs: float
    baseflow_cfs: float
    peak_cfs: float
    low_peak_cfs: float
    high_peak_cfs: float
    rise_cfs: float
    rise_pct_base: float
    rise_pct_peak: float
    decay_24h_pct: float
    peak_time: datetime
    half_life_days: float
    curve: tuple[tuple[datetime, float], ...]
    low_curve: tuple[tuple[datetime, float], ...]
    high_curve: tuple[tuple[datetime, float], ...]
    confidence: str
    source: str
    similar: tuple[FlowEvent, ...] = ()


def scenario_from_qpf(
    qpf: tuple[tuple[datetime, float], ...], now: datetime | None = None, hours: int = 48
) -> Scenario:
    now = now or utc_now()
    limit = now + timedelta(hours=hours)
    selected = [
        (moment, value)
        for moment, value in qpf
        if now - timedelta(hours=6) <= moment <= limit and value > 0
    ]
    return Scenario(tuple(selected), sum(value for _moment, value in selected))


def scenario_from_hourly(
    rows: tuple[tuple[datetime, float, int | None], ...],
    now: datetime | None = None,
    hours: int = 48,
) -> Scenario:
    now = now or utc_now()
    limit = now + timedelta(hours=hours)
    selected = [
        (moment, mm_to_inches(millimetres))
        for moment, millimetres, _probability in rows
        if now - timedelta(hours=1) <= moment <= limit and millimetres > 0
    ]
    return Scenario(tuple(selected), sum(value for _moment, value in selected))


def forecast_scenario(
    bundle: DataBundle, now: datetime | None = None, hours: int = 48
) -> tuple[Scenario, str]:
    """Prefer the official NWS QPF; fall back to the Open-Meteo model."""
    now = now or utc_now()
    official = scenario_from_qpf(bundle.nws_qpf, now, hours)
    if official.total_in > 0.001:
        return official, "NWS QPF"
    modelled = scenario_from_hourly(bundle.openmeteo_hourly, now, hours)
    return modelled, "Open-Meteo"


def scale_scenario(scenario: Scenario, total_in: float) -> Scenario:
    """Re-scale a scenario to a user-supplied total, preserving storm timing."""
    if scenario.total_in <= 0:
        return Scenario((), max(0.0, total_in))
    factor = max(0.0, total_in) / scenario.total_in
    return Scenario(
        tuple((moment, value * factor) for moment, value in scenario.increments),
        max(0.0, total_in),
    )


def recent_baseflow(series: Series | None, days: int = 7) -> float:
    """Lowest recent flow: a crude but stable antecedent baseflow estimate."""
    if series is None:
        return 0.0
    valid = series.valid
    if not valid:
        return 0.0
    cutoff = valid[-1].time - timedelta(days=days)
    recent = [sample.value for sample in valid if sample.time >= cutoff]
    return float(min(recent)) if recent else float(valid[-1].value)


def predict(
    scenario: Scenario,
    fit: ResponseFit | None,
    events: tuple[FlowEvent, ...],
    *,
    current_cfs: float,
    baseflow_cfs: float,
    now: datetime | None = None,
    step_hours: float = 2.0,
    source: str = "",
) -> Prediction | None:
    """Turn a rain scenario + fitted response into a predicted hydrograph."""
    now = now or utc_now()
    if fit is None or scenario.total_in <= 0.005:
        return None

    base = max(0.0, baseflow_cfs)
    current = max(float(current_cfs), base)
    peak_time = scenario.centroid() + timedelta(hours=max(0.0, fit.lag_p50_hours))
    earliest = now + timedelta(hours=2)
    if peak_time < earliest:
        peak_time = earliest

    def build(ratio: float) -> tuple[float, tuple[tuple[datetime, float], ...]]:
        target = base + ratio * scenario.total_in
        peak = max(current, target)
        rise_span = max(3600.0, (peak_time - now).total_seconds())

        points: list[tuple[datetime, float]] = []
        moment = now
        while moment < peak_time:
            fraction = min(1.0, (moment - now).total_seconds() / rise_span)
            smooth = fraction * fraction * (3.0 - 2.0 * fraction)
            points.append((moment, current + (peak - current) * smooth))
            moment += timedelta(hours=step_hours)
        points.append((peak_time, peak))

        half_life = fit.half_life_days if fit.half_life_days > 0 else 1.0
        # 8 half-lives brings the recession within ~0.4% of baseflow.
        horizon = peak_time + timedelta(days=min(10.0, max(2.0, 8.0 * half_life)))
        moment = peak_time + timedelta(hours=step_hours)
        while moment <= horizon:
            elapsed_days = (moment - peak_time).total_seconds() / 86400.0
            decay = 0.5 ** (elapsed_days / half_life)
            points.append((moment, base + (peak - base) * decay))
            moment += timedelta(hours=step_hours)
        return peak, tuple(points)

    peak, curve = build(fit.ratio_p50)
    low_peak, low_curve = build(fit.ratio_p10)
    high_peak, high_curve = build(fit.ratio_p90)

    rise = max(0.0, peak - current)
    rise_pct_base = 100.0 * rise / base if base > 0 else 0.0
    rise_pct_peak = 100.0 * rise / peak if peak > 0 else 0.0
    after_peak = [
        value for moment, value in curve if moment >= peak_time + timedelta(hours=24)
    ]
    flow_24h = after_peak[0] if after_peak else curve[-1][1]
    storm_flow = max(1e-9, peak - base)
    decay_24h_pct = 100.0 * max(0.0, peak - flow_24h) / storm_flow

    similar = tuple(
        sorted(
            (
                event
                for event in events
                if event.rain_in > 0
                and abs(event.rain_in - scenario.total_in)
                <= max(0.10, 0.30 * scenario.total_in)
            ),
            key=lambda event: event.start,
            reverse=True,
        )[:5]
    )

    return Prediction(
        rain_in=scenario.total_in,
        current_cfs=current,
        baseflow_cfs=base,
        peak_cfs=peak,
        low_peak_cfs=low_peak,
        high_peak_cfs=high_peak,
        rise_cfs=rise,
        rise_pct_base=rise_pct_base,
        rise_pct_peak=rise_pct_peak,
        decay_24h_pct=decay_24h_pct,
        peak_time=peak_time,
        half_life_days=fit.half_life_days,
        curve=curve,
        low_curve=low_curve,
        high_curve=high_curve,
        confidence=fit.confidence,
        source=source,
        similar=similar,
    )
