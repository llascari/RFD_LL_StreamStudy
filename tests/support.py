"""Test helpers: fixture loading and an offline HTTP stand-in."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class FakeMmwClient:
    """Serves Monitor My Watershed fixtures for the ODM2 AJAX endpoint."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_text(self, url: str, params: dict | None = None) -> str:
        return fixture("mmw_sites.html")

    def post_form(self, url: str, data: dict) -> str:
        request = json.loads(data["request_data"])
        self.calls.append(request)
        if request.get("method") == "get_sampling_feature_metadata":
            return fixture("mmw_metadata.json")
        result_id = int(request.get("resultid", 0))
        return fixture("mmw_depth.json" if result_id == 8061 else "mmw_temp.json")


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

    def get_bytes(self, url: str, params: dict | None = None) -> bytes:
        return self.get_text(url, params).encode("utf-8")

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
        "monitoring-locations": fixture("ogc_locations.json"),
        "/nwis/iv/": fixture("usgs_iv.json"),
        "/nwis/dv/": fixture("usgs_dv.json"),
        "/nwis/site/": fixture("usgs_site.rdb"),
    }
