"""Rank nearby gages as a data hub.

The score rewards what makes a gage useful for this app: a fitted rainfall→flow
response, a long storm sample, strong coherence with neighbouring streams,
water temperature, and proximity to the current gage. The suggested hub is the
best-scoring gage closest to the centroid of the top three.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .correlation import lagged_correlation
from .models import ResponseFit, Site


@dataclass(frozen=True)
class SiteScore:
    site: Site
    score: float
    r_squared: float
    events: int
    mean_peer_r: float
    has_temperature: bool
    distance_km: float
    reasons: str


@dataclass(frozen=True)
class Ranking:
    scores: tuple[SiteScore, ...]
    hub: SiteScore | None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _distance_km(first: Site, second: Site) -> float:
    mean_lat = math.radians((first.latitude + second.latitude) / 2.0)
    dx = (second.longitude - first.longitude) * 111.0 * math.cos(mean_lat)
    dy = (second.latitude - first.latitude) * 111.0
    return math.hypot(dx, dy)


def build_ranking(
    sites: tuple[Site, ...],
    flows: dict[str, dict],
    temperatures: dict[str, dict],
    fits: dict[str, ResponseFit | None],
    base_site: Site | None = None,
) -> Ranking:
    ids = [site.number for site in sites if flows.get(site.number)]
    peer: dict[str, list[float]] = {}
    for index, first in enumerate(ids):
        for second in ids[index + 1 :]:
            correlation = lagged_correlation(flows[first], flows[second], max_lag=1)
            if correlation is not None:
                peer.setdefault(first, []).append(abs(correlation.r))
                peer.setdefault(second, []).append(abs(correlation.r))

    scores: list[SiteScore] = []
    for site in sites:
        if site.number not in ids:
            continue
        fit = fits.get(site.number)
        r_squared = fit.r_squared if fit is not None else 0.0
        events = fit.events if fit is not None else 0
        peers = peer.get(site.number, [])
        mean_peer = sum(peers) / len(peers) if peers else 0.0
        has_temperature = bool(temperatures.get(site.number))
        distance = _distance_km(base_site, site) if base_site is not None else 0.0

        quality = 2.5 * _clamp(r_squared) + min(2.0, events / 40.0)
        peer_points = 2.0 * _clamp(mean_peer)
        temperature_points = 1.0 if has_temperature else 0.0
        distance_penalty = min(1.5, distance / 40.0)
        score = 1.0 + quality + peer_points + temperature_points - distance_penalty

        reasons = [f"{events} storms", f"r\u00b2 {r_squared:.2f}"]
        if peers:
            reasons.append(f"peer r {mean_peer:.2f}")
        if has_temperature:
            reasons.append("water temp")
        reasons.append(f"{distance:.0f} km")
        scores.append(
            SiteScore(
                site=site,
                score=score,
                r_squared=r_squared,
                events=events,
                mean_peer_r=mean_peer,
                has_temperature=has_temperature,
                distance_km=distance,
                reasons="  \u00b7  ".join(reasons),
            )
        )

    scores.sort(key=lambda item: item.score, reverse=True)
    hub: SiteScore | None = None
    top = scores[:3]
    if top:
        centre_lat = sum(item.site.latitude for item in top) / len(top)
        centre_lon = sum(item.site.longitude for item in top) / len(top)
        hub = min(
            top,
            key=lambda item: abs(item.site.latitude - centre_lat)
            + abs(item.site.longitude - centre_lon),
        )
    return Ranking(scores=tuple(scores), hub=hub)
