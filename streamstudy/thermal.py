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
class SunlightPeer:
    """Sunshine-driven water-temperature sensitivity for one stream."""

    site_number: str
    name: str
    distance_km: float
    water_days: int = 0
    sun_r: float | None = None
    air_r: float | None = None
    slope_c_per_hour: float | None = None
    lag_days: int | None = None
    pairs: int = 0
    confidence: str = "n/a"
    this_site: bool = False
    error: str = ""


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
) -> tuple[SunlightPeer, ...]:
    """Compare how strongly sunshine anomalies drive water-temperature anomalies.

    ``peers`` items are ``(site_number, name, distance_km, water, air, sun,
    error)``. Each stream is fitted the same way and rows are returned sorted
    by the sunshine slope (°C of water rise per sunshine-hour above normal),
    strongest first, so relative sunlight sensitivity is directly visible.
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
    ) -> SunlightPeer:
        if error:
            return SunlightPeer(
                site_number=number,
                name=name,
                distance_km=distance,
                error=error,
                this_site=this_site,
            )
        analysis = build_thermal_analysis(
            water,
            air,
            sun,
            max_lag=max_lag,
            min_pairs=min_pairs,
        )
        sun_fit = analysis.sun_anomaly
        air_fit = analysis.air_anomaly
        best = sun_fit.best if sun_fit is not None else None
        return SunlightPeer(
            site_number=number,
            name=name,
            distance_km=distance,
            water_days=analysis.water_days,
            sun_r=best.r if best is not None else None,
            air_r=(air_fit.best.r if air_fit is not None and air_fit.best else None),
            slope_c_per_hour=sun_fit.slope if sun_fit is not None else None,
            lag_days=best.lag_days if best is not None else None,
            pairs=best.n if best is not None else 0,
            confidence=sun_fit.confidence if sun_fit is not None else "n/a",
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
        row(number, name, distance, water, air, sun, error)
        for number, name, distance, water, air, sun, error in peers
    )
    rows.sort(
        key=lambda item: (
            0 if item.slope_c_per_hour is not None else 1,
            -(item.slope_c_per_hour or 0.0),
            item.distance_km,
        )
    )
    return tuple(rows)
