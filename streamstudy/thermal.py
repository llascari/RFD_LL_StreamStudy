"""Correlate daily water temperature with air temperature and sunshine.

Water temperature responds to the weather with a lag: air temperature often
leads by zero to a couple of days, while sunshine can lead by a day or more.
This module is pure and works on local-date dictionaries, so both USGS daily
values and Monitor My Watershed sensor means can use it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from .analysis import daily_means, haversine_km, pearson
from .correlation import LagCorrelation, lagged_correlation
from .models import Series, WeatherDay


@dataclass(frozen=True)
class WaterSource:
    """One water-temperature series available for correlation."""

    key: str
    label: str
    daily: dict[date, float]
    note: str = ""
    recent_only: bool = False


@dataclass(frozen=True)
class DriverFit:
    """Best lag plus the full lag curve for one weather driver."""

    driver: str
    best: LagCorrelation | None = None
    by_lag: tuple[tuple[int, float | None, int], ...] = ()
    points: tuple[tuple[float, float], ...] = ()  # (driver value, water value)
    fit: tuple[tuple[float, float], tuple[float, float]] | None = None
    slope: float | None = None
    intercept: float | None = None
    confidence: str = "n/a"


@dataclass(frozen=True)
class ThermalAnalysis:
    """Air and sunshine fits for one water-temperature source.

    ``air``/``sun`` correlate absolute daily values; ``air_anomaly``/
    ``sun_anomaly`` correlate **rise over normal**: each series minus its own
    centred rolling mean, so the fits describe day-to-day departures from the
    seasonal norm rather than the seasonal cycle itself.
    """

    water_days: int
    air: DriverFit
    sun: DriverFit
    air_anomaly: DriverFit | None = None
    sun_anomaly: DriverFit | None = None
    anomaly_days: int = 0
    anomaly_note: str = ""
    error: str = ""


@dataclass(frozen=True)
class JointDriverFit:
    """Two-driver regression on rise-over-normal anomalies.

    Water-temperature anomalies are regressed on air-temperature and
    sunshine anomalies **together**, so each slope is one driver's effect
    with the other held constant ("all else being equal"). This separates
    sunshine's influence from the air temperature it travels with.
    """

    n: int = 0
    air_lag: int = 0
    sun_lag: int = 0
    air_slope: float | None = None  # °C per °C of air anomaly, sun constant
    sun_slope: float | None = None  # °C per sunshine-hour anomaly, air constant
    r_squared: float | None = None
    sun_partial_r: float | None = None
    air_partial_r: float | None = None
    confidence: str = "n/a"


@dataclass(frozen=True)
class SunlightPeer:
    """Sunshine-driven water-temperature sensitivity for one stream.

    ``slope_c_per_hour`` is the **partial** sunshine slope from the joint
    anomaly fit: °C of water rise per sunshine-hour above normal, with air
    temperature held constant. ``sun_r``/``air_r`` are the matching partial
    correlations. ``mean_c`` is the stream's mean water temperature in the
    window — a rough hint at its thermal class (coldwater vs warmwater).
    """

    site_number: str
    name: str
    distance_km: float
    water_days: int = 0
    mean_c: float | None = None
    sun_r: float | None = None
    air_r: float | None = None
    slope_c_per_hour: float | None = None
    sun_lag_days: int | None = None
    air_lag_days: int | None = None
    r_squared: float | None = None
    pairs: int = 0
    confidence: str = "n/a"
    this_site: bool = False
    error: str = ""


MIN_PEER_DAYS = 8


def _peer_has_valid_water(water: dict, min_days: int) -> bool:
    """Enough non-constant daily values to fit (test units are empty or stuck)."""
    if len(water) < min_days:
        return False
    values = list(water.values())
    return max(values) - min(values) > 0.05


def series_water_c(series: Series) -> dict[date, float]:
    """Daily mean water temperature in degrees Celsius from a sensor series."""
    daily = daily_means(series.samples)
    units = (series.units or "").upper()
    if "F" in units and "C" not in units:
        return {day: (value - 32.0) * 5.0 / 9.0 for day, value in daily.items()}
    return daily


def merge_weather(
    air: dict[date, float],
    sunshine: dict[date, float],
    weather_days: tuple[WeatherDay, ...] = (),
) -> tuple[dict[date, float], dict[date, float]]:
    """Combine long archive series with the app's recent daily weather."""
    merged_air = dict(air)
    merged_sun = dict(sunshine)
    for day in weather_days:
        if day.mean_c is not None:
            merged_air[day.day] = day.mean_c
        if day.sunshine_hours is not None:
            merged_sun[day.day] = day.sunshine_hours
    return merged_air, merged_sun


def rolling_nominal(
    values: dict[date, float],
    *,
    half_window: int = 7,
    min_points: int = 5,
) -> dict[date, float]:
    """Centred rolling mean at each date: a slowly varying "normal".

    Each date's nominal is the mean of the available values within
    ``±half_window`` days. Edge dates with fewer than ``min_points`` days in
    the window get no nominal, so the first and last week or so of a series
    has no anomaly.
    """
    if not values:
        return {}
    days = sorted(values)
    span = timedelta(days=half_window)
    nominal: dict[date, float] = {}
    start = 0
    end = 0
    for index, day in enumerate(days):
        low = day - span
        high = day + span
        while start < index and days[start] < low:
            start += 1
        if end < index:
            end = index
        while end + 1 < len(days) and days[end + 1] <= high:
            end += 1
        window_days = days[start : end + 1]
        if len(window_days) < min_points:
            continue
        nominal[day] = math.fsum(values[d] for d in window_days) / len(window_days)
    return nominal


def anomalies(
    values: dict[date, float], nominal: dict[date, float]
) -> dict[date, float]:
    """Values minus their rolling nominal (rise over normal)."""
    return {
        day: value - nominal[day] for day, value in values.items() if day in nominal
    }


def confidence_label(r: float | None, pairs: int) -> str:
    """A deliberately blunt screening label, not a significance test."""
    if r is None or pairs < 7 or not math.isfinite(r):
        return "too few days"
    if pairs >= 30 and abs(r) >= 0.65:
        return "strong"
    if pairs >= 14 and abs(r) >= 0.40:
        return "moderate"
    return "weak"


def linear_fit(
    points: list[tuple[float, float]] | tuple[tuple[float, float], ...],
) -> tuple[float, float] | None:
    """Ordinary least squares with an intercept: returns (slope, intercept)."""
    if len(points) < 2:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    mean_x = math.fsum(xs) / len(xs)
    mean_y = math.fsum(ys) / len(ys)
    sxx = math.fsum((x - mean_x) ** 2 for x in xs)
    if sxx <= 1e-12:
        return None
    sxy = math.fsum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = sxy / sxx
    return slope, mean_y - slope * mean_x


def partial_pearson(r_xy: float, r_xz: float, r_yz: float) -> float | None:
    """Correlation of x and y with z's shared influence removed."""
    denominator = (1.0 - r_xz * r_xz) * (1.0 - r_yz * r_yz)
    if denominator <= 1e-12:
        return None
    return (r_xy - r_xz * r_yz) / math.sqrt(denominator)


def _ols2(
    air: list[float], sun: list[float], water: list[float]
) -> tuple[float, float, float, float, float, float] | None:
    """OLS with two predictors; ``(air_slope, sun_slope, r2, air_partial,
    sun_partial, n)`` or ``None`` when the predictors are collinear."""
    count = len(water)
    mean_air = math.fsum(air) / count
    mean_sun = math.fsum(sun) / count
    mean_water = math.fsum(water) / count
    s_aa = math.fsum((a - mean_air) ** 2 for a in air)
    s_ss = math.fsum((s - mean_sun) ** 2 for s in sun)
    s_as = math.fsum((a - mean_air) * (s - mean_sun) for a, s in zip(air, sun))
    s_aw = math.fsum((a - mean_air) * (w - mean_water) for a, w in zip(air, water))
    s_sw = math.fsum((s - mean_sun) * (w - mean_water) for s, w in zip(sun, water))
    s_ww = math.fsum((w - mean_water) ** 2 for w in water)
    determinant = s_aa * s_ss - s_as * s_as
    if determinant <= 1e-9 * max(1.0, s_aa * s_ss):
        return None  # sun and air anomalies carry (almost) the same signal
    air_slope = (s_ss * s_aw - s_as * s_sw) / determinant
    sun_slope = (s_aa * s_sw - s_as * s_aw) / determinant
    residuals = [
        w - (mean_water + air_slope * (a - mean_air) + sun_slope * (s - mean_sun))
        for a, s, w in zip(air, sun, water)
    ]
    sse = math.fsum(residual * residual for residual in residuals)
    r_squared = 1.0 - sse / s_ww if s_ww > 1e-12 else None
    r_air = pearson(air, water)
    r_sun = pearson(sun, water)
    r_air_sun = pearson(air, sun)
    return (
        air_slope,
        sun_slope,
        r_squared,
        partial_pearson(r_air, r_sun, r_air_sun),
        partial_pearson(r_sun, r_air, r_air_sun),
        count,
    )


def joint_anomaly_fit(
    water: dict[date, float],
    air: dict[date, float],
    sunshine: dict[date, float],
    *,
    max_lag: int = 5,
    min_pairs: int = 5,
    anomaly_half_window: int = 7,
    anomaly_min_points: int = 5,
) -> JointDriverFit | None:
    """Sun and air effects on water rise, each holding the other constant.

    All three series are reduced to rise-over-normal anomalies, then water is
    regressed on air and sunshine together at every ``(air_lag, sun_lag)``
    pair from 0 to ``max_lag`` days (drivers lead water). The best r² wins;
    slopes are in °C of water rise per unit of driver rise.
    """
    water_anomaly = anomalies(
        water,
        rolling_nominal(
            water, half_window=anomaly_half_window, min_points=anomaly_min_points
        ),
    )
    air_anomaly = anomalies(
        air,
        rolling_nominal(
            air, half_window=anomaly_half_window, min_points=anomaly_min_points
        ),
    )
    sun_anomaly = anomalies(
        sunshine,
        rolling_nominal(
            sunshine, half_window=anomaly_half_window, min_points=anomaly_min_points
        ),
    )
    if not water_anomaly or not air_anomaly or not sun_anomaly:
        return None

    best: JointDriverFit | None = None
    best_key: tuple[float, int, int] | None = None
    for air_lag in range(0, max_lag + 1):
        for sun_lag in range(0, max_lag + 1):
            paired_air: list[float] = []
            paired_sun: list[float] = []
            paired_water: list[float] = []
            for day, water_value in water_anomaly.items():
                air_value = air_anomaly.get(day - timedelta(days=air_lag))
                sun_value = sun_anomaly.get(day - timedelta(days=sun_lag))
                if air_value is None or sun_value is None:
                    continue
                paired_air.append(air_value)
                paired_sun.append(sun_value)
                paired_water.append(water_value)
            if len(paired_water) < min_pairs:
                continue
            fitted = _ols2(paired_air, paired_sun, paired_water)
            if fitted is None:
                continue
            air_slope, sun_slope, r_squared, air_partial, sun_partial, count = fitted
            if r_squared is None or not math.isfinite(r_squared):
                continue
            key = (r_squared, -air_lag, -sun_lag)
            if best_key is None or key > best_key:
                best_key = key
                best = JointDriverFit(
                    n=count,
                    air_lag=air_lag,
                    sun_lag=sun_lag,
                    air_slope=air_slope,
                    sun_slope=sun_slope,
                    r_squared=r_squared,
                    sun_partial_r=sun_partial,
                    air_partial_r=air_partial,
                    confidence=confidence_label(sun_partial, count),
                )
    return best


def _driver_fit(
    water: dict[date, float],
    driver: dict[date, float],
    name: str,
    *,
    max_lag: int,
    min_pairs: int,
) -> DriverFit:
    best = lagged_correlation(
        driver,
        water,
        max_lag=max_lag,
        min_pairs=min_pairs,
        logarithmic=False,
    )
    by_lag: list[tuple[int, float | None, int]] = []
    for lag in range(-max_lag, max_lag + 1):
        xs: list[float] = []
        ys: list[float] = []
        for day, driver_value in driver.items():
            water_value = water.get(day + timedelta(days=lag))
            if water_value is None:
                continue
            xs.append(driver_value)
            ys.append(water_value)
        r = pearson(xs, ys) if len(xs) >= 2 else None
        if r is not None and not math.isfinite(r):
            r = None
        by_lag.append((lag, r, len(xs)))

    if best is None or best.n < min_pairs:
        return DriverFit(driver=name, by_lag=tuple(by_lag))

    points: list[tuple[float, float]] = []
    for day, driver_value in driver.items():
        water_value = water.get(day + timedelta(days=best.lag_days))
        if water_value is not None:
            points.append((float(driver_value), float(water_value)))
    fit = None
    slope = intercept = None
    fitted = linear_fit(points)
    if fitted is not None:
        slope, intercept = fitted
        x_low = min(point[0] for point in points)
        x_high = max(point[0] for point in points)
        fit = (
            (x_low, intercept + slope * x_low),
            (x_high, intercept + slope * x_high),
        )
    return DriverFit(
        driver=name,
        best=best,
        by_lag=tuple(by_lag),
        points=tuple(points),
        fit=fit,
        slope=slope,
        intercept=intercept,
        confidence=confidence_label(best.r, best.n),
    )


def build_thermal_analysis(
    water: dict[date, float],
    air: dict[date, float],
    sunshine: dict[date, float],
    *,
    max_lag: int = 5,
    min_pairs: int = 5,
    anomaly_half_window: int = 7,
    anomaly_min_points: int = 5,
) -> ThermalAnalysis:
    """Fit both drivers against one water-temperature source.

    A **positive lag** means water temperature follows the driver: for example
    lag +1 pairs today's air temperature with tomorrow's water temperature.

    Alongside the absolute fits, each series is reduced to its rise over a
    centred rolling mean ("normal") and fitted again; those anomaly fits
    describe day-to-day drivers instead of the shared seasonal cycle.
    """
    if not water:
        return ThermalAnalysis(
            water_days=0,
            air=DriverFit(driver="air"),
            sun=DriverFit(driver="sunshine"),
            air_anomaly=DriverFit(driver="air anomaly"),
            sun_anomaly=DriverFit(driver="sunshine anomaly"),
            error="No daily water temperature for this source.",
        )

    def anomaly(values: dict[date, float]) -> dict[date, float]:
        return anomalies(
            values,
            rolling_nominal(
                values,
                half_window=anomaly_half_window,
                min_points=anomaly_min_points,
            ),
        )

    water_anomaly = anomaly(water)
    air_anomaly_values = anomaly(air)
    sun_anomaly_values = anomaly(sunshine)
    air_anomaly_fit = _driver_fit(
        water_anomaly,
        air_anomaly_values,
        "air anomaly",
        max_lag=max_lag,
        min_pairs=min_pairs,
    )
    sun_anomaly_fit = _driver_fit(
        water_anomaly,
        sun_anomaly_values,
        "sunshine anomaly",
        max_lag=max_lag,
        min_pairs=min_pairs,
    )
    note = ""
    if not water_anomaly:
        note = (
            "too few days for a rolling normal "
            f"(need {anomaly_min_points}+ days within \u00b1{anomaly_half_window} d)"
        )
    return ThermalAnalysis(
        water_days=len(water),
        air=_driver_fit(
            water, air, "air temperature", max_lag=max_lag, min_pairs=min_pairs
        ),
        sun=_driver_fit(
            water, sunshine, "sunshine", max_lag=max_lag, min_pairs=min_pairs
        ),
        air_anomaly=air_anomaly_fit,
        sun_anomaly=sun_anomaly_fit,
        anomaly_days=len(water_anomaly),
        anomaly_note=note,
    )


def sunlight_peers(
    base_number: str,
    base_name: str,
    base_water: dict[date, float],
    base_air: dict[date, float],
    base_sun: dict[date, float],
    peers: list[tuple[str, str, float, dict, dict, dict, str]],
    *,
    max_lag: int = 5,
    min_pairs: int = 5,
    min_days: int = MIN_PEER_DAYS,
) -> tuple[SunlightPeer, ...]:
    """Compare sunshine's effect on water rise with air held constant.

    ``peers`` items are ``(site_number, name, distance_km, water, air, sun,
    error)``. Every stream gets the same joint anomaly regression (water on
    air and sunshine together), so the ranked slope is °C of water rise per
    sunshine-hour above normal **holding air temperature constant" — for
    roughly the same sun exposure, streams that differ here really do respond
    differently. Rows are sorted strongest first.

    Only streams with valid temperature data make the list: candidates with
    fewer than ``min_days`` of daily values, or a stuck (constant) sensor,
    are excluded entirely, so test units and dry channels do not pollute the
    comparison. Genuine fetch failures stay visible as error rows.
    """

    def row(
        number: str,
        name: str,
        distance: float,
        water: dict,
        air: dict,
        sun: dict,
        error: str,
        *,
        this_site: bool = False,
    ) -> SunlightPeer | None:
        if error:
            return SunlightPeer(
                site_number=number,
                name=name,
                distance_km=distance,
                error=error,
                this_site=this_site,
            )
        if not this_site and not _peer_has_valid_water(water, min_days):
            return None
        analysis = build_thermal_analysis(
            water,
            air,
            sun,
            max_lag=max_lag,
            min_pairs=min_pairs,
        )
        joint = joint_anomaly_fit(
            water,
            air,
            sun,
            max_lag=max_lag,
            min_pairs=min_pairs,
        )
        values = list(water.values())
        return SunlightPeer(
            site_number=number,
            name=name,
            distance_km=distance,
            water_days=analysis.water_days,
            mean_c=(math.fsum(values) / len(values)) if values else None,
            sun_r=joint.sun_partial_r if joint is not None else None,
            air_r=joint.air_partial_r if joint is not None else None,
            slope_c_per_hour=joint.sun_slope if joint is not None else None,
            sun_lag_days=joint.sun_lag if joint is not None else None,
            air_lag_days=joint.air_lag if joint is not None else None,
            r_squared=joint.r_squared if joint is not None else None,
            pairs=joint.n if joint is not None else 0,
            confidence=joint.confidence if joint is not None else "n/a",
            this_site=this_site,
        )

    rows = [
        row(
            base_number,
            base_name,
            0.0,
            base_water,
            base_air,
            base_sun,
            "",
            this_site=True,
        )
    ]
    rows.extend(
        kept
        for kept in (
            row(number, name, distance, water, air, sun, error)
            for number, name, distance, water, air, sun, error in peers
        )
        if kept is not None
    )
    rows.sort(
        key=lambda item: (
            0 if item.slope_c_per_hour is not None else 1,
            -(item.slope_c_per_hour or 0.0),
            item.distance_km,
        )
    )
    return tuple(rows)
