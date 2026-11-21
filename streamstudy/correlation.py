"""Lagged cross-correlation between regional gages and rain sources.

Flows are compared in log space (``log1p``) because streamflow is roughly
multiplicative. For two series ``a`` and ``b`` the reported lag is the shift
that maximises |r|: a positive lag means ``b`` follows ``a`` (for example,
flow following rainfall, or a downstream gage following an upstream one).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from .analysis import pearson
from .models import Site

MIN_PAIRS = 30


@dataclass(frozen=True)
class LagCorrelation:
    r: float
    lag_days: int
    n: int


@dataclass
class RegionalAnalysis:
    start: date
    end: date
    sites: tuple[Site, ...]
    flow: dict[str, dict[date, float]]
    flow_pairs: dict[tuple[str, str], LagCorrelation] = field(default_factory=dict)
    rain_pairs: dict[tuple[str, str], LagCorrelation] = field(default_factory=dict)
    precip_labels: tuple[str, ...] = ()
    errors: list[str] = field(default_factory=list)

    def site(self, site_id: str) -> Site | None:
        return next((site for site in self.sites if site.number == site_id), None)

    def short_label(self, site_id: str) -> str:
        return site_id if len(site_id) <= 10 else site_id[-7:]

    def strongest_pairs(self, limit: int = 3) -> list[tuple[str, str, LagCorrelation]]:
        ordered = sorted(
            (
                (first, second, correlation)
                for (first, second), correlation in self.flow_pairs.items()
            ),
            key=lambda item: abs(item[2].r),
            reverse=True,
        )
        return ordered[:limit]


def _log(values: list[float]) -> list[float]:
    return [math.log1p(max(0.0, value)) for value in values]


def lagged_correlation(
    a: dict[date, float],
    b: dict[date, float],
    *,
    max_lag: int = 5,
    min_pairs: int = MIN_PAIRS,
    logarithmic: bool = True,
) -> LagCorrelation | None:
    """Best |r| over lags in ``[-max_lag, max_lag]`` days.

    ``logarithmic`` suits flow/stage; disable it for temperatures, which can
    be negative.
    """
    transform = _log if logarithmic else (lambda values: list(values))
    best: LagCorrelation | None = None
    for lag in sorted(range(-max_lag, max_lag + 1), key=abs):
        xs: list[float] = []
        ys: list[float] = []
        for day, value in a.items():
            other = b.get(day + timedelta(days=lag))
            if other is None:
                continue
            xs.append(value)
            ys.append(other)
        if len(xs) < min_pairs:
            continue
        r = pearson(transform(xs), transform(ys))
        if not math.isfinite(r):
            continue
        if best is None or abs(r) > abs(best.r) + 1e-12:
            best = LagCorrelation(r=r, lag_days=lag, n=len(xs))
    return best


def build_regional(
    sites: tuple[Site, ...],
    flows: dict[str, dict[date, float]],
    precip: dict[str, dict[date, float]],
    *,
    start: date,
    end: date,
    max_lag: int = 5,
    errors: list[str] | None = None,
) -> RegionalAnalysis:
    ids = [site.number for site in sites if site.number in flows]
    flow_pairs: dict[tuple[str, str], LagCorrelation] = {}
    for index, first in enumerate(ids):
        for second in ids[index + 1 :]:
            correlation = lagged_correlation(
                flows[first], flows[second], max_lag=max_lag
            )
            if correlation is not None:
                flow_pairs[(first, second)] = correlation

    rain_pairs: dict[tuple[str, str], LagCorrelation] = {}
    for site_id in ids:
        for label, series in precip.items():
            if not series:
                continue
            correlation = lagged_correlation(series, flows[site_id], max_lag=max_lag)
            if correlation is not None:
                rain_pairs[(site_id, label)] = correlation

    return RegionalAnalysis(
        start=start,
        end=end,
        sites=tuple(sites),
        flow=flows,
        flow_pairs=flow_pairs,
        rain_pairs=rain_pairs,
        precip_labels=tuple(precip),
        errors=list(errors or []),
    )
