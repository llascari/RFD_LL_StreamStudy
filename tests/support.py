"""Test helpers: fixture loading and an offline HTTP stand-in."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class StaticClient:
    """Returns fixture text based on a substring of the requested URL."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.mapping = mapping if mapping is not None else default_mapping()
        self.calls: list[tuple[str, dict | None]] = []

    def get_text(self, url: str, params: dict | None = None) -> str:
        self.calls.append((url, params))
        for marker, payload in self.mapping.items():
            if marker in url:
                return payload
        raise KeyError(f"No fixture configured for {url}")

    def get_json(self, url: str, params: dict | None = None) -> dict:
        return json.loads(self.get_text(url, params))

    def clear_cache(self) -> None:
        return None


def default_mapping() -> dict[str, str]:
    """Order matters: more specific paths first."""
    return {
        "archive-api.open-meteo.com": fixture("openmeteo_archive.json"),
        "open-meteo.com": fixture("openmeteo.json"),
        "/observations": fixture("nws_observations.json"),
        "forecast/hourly": fixture("nws_hourly.json"),
        "/forecast": fixture("nws_daily.json"),
        "/stations": fixture("nws_stations.json"),
        "gridpoints/": fixture("nws_grid.json"),
        "/points/": fixture("nws_points.json"),
        "exportreports.aspx": fixture("cocorahs_station.csv"),
        "/nwis/iv/": fixture("usgs_iv.json"),
        "/nwis/dv/": fixture("usgs_dv.json"),
        "/nwis/site/": fixture("usgs_site.rdb"),
    }
