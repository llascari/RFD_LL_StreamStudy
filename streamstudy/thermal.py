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

from .analysis import daily_means, pearson
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
    """Air and sunshine fits for one water-temperature source."""

    water_days: int
    air: DriverFit
    sun: DriverFit
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
) -> ThermalAnalysis:
    """Fit both drivers against one water-temperature source.

    A **positive lag** means water temperature follows the driver: for example
    lag +1 pairs today's air temperature with tomorrow's water temperature.
    """
    if not water:
        return ThermalAnalysis(
            water_days=0,
            air=DriverFit(driver="air"),
            sun=DriverFit(driver="sunshine"),
            error="No daily water temperature for this source.",
        )
    return ThermalAnalysis(
        water_days=len(water),
        air=_driver_fit(
            water, air, "air temperature", max_lag=max_lag, min_pairs=min_pairs
        ),
        sun=_driver_fit(
            water, sunshine, "sunshine", max_lag=max_lag, min_pairs=min_pairs
        ),
    )
