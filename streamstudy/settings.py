"""Tiny JSON settings file (last site, recent sites, range, gauge)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT_SITE = "0423205010"  # Irondequoit Creek above Blossom Rd, Rochester NY

DEFAULTS = {
    "last_site": DEFAULT_SITE,
    "recent_sites": [DEFAULT_SITE],
    "days": 14,
    "site_names": {},
    "temperature_threshold_c": 20.0,
    "analysis_window": {"mode": "1y"},
    "store_flow_metrics": True,
    "flow_metrics": {},
    "map_zoom": 10,
    "map_years": 2,
    "coco_station": "",
    "state": "NY",
}

ALLOWED_DAYS = (7, 14, 30, 60)
ALLOWED_MAP_YEARS = (1, 2, 3)


def default_settings_path() -> Path:
    override = os.environ.get("STREAMSTUDY_SETTINGS")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "streamstudy" / "settings.json"


def load_settings(path: str | Path | None = None) -> dict:
    target = Path(path) if path else default_settings_path()
    data = dict(DEFAULTS)
    try:
        payload = json.loads(target.read_text())
        if isinstance(payload, dict):
            data.update({k: v for k, v in payload.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if data["days"] not in ALLOWED_DAYS:
        data["days"] = DEFAULTS["days"]
    names = data.get("site_names")
    if not isinstance(names, dict):
        data["site_names"] = {}
    else:
        data["site_names"] = {str(key): str(value) for key, value in names.items()}
    try:
        threshold = float(data.get("temperature_threshold_c", 20.0))
    except (TypeError, ValueError):
        threshold = 20.0
    data["temperature_threshold_c"] = max(0.0, min(40.0, threshold))
    data["store_flow_metrics"] = bool(data.get("store_flow_metrics", True))
    window = data.get("analysis_window")
    if not isinstance(window, dict) or window.get("mode") not in (
        "1d", "7d", "30d", "90d", "1y", "2y", "5y", "custom"
    ):
        data["analysis_window"] = dict(DEFAULTS["analysis_window"])
    metrics = data.get("flow_metrics")
    data["flow_metrics"] = (
        {str(site): value for site, value in metrics.items() if isinstance(value, dict)}
        if isinstance(metrics, dict)
        else {}
    )
    # Migrate the old radius preference to a zoom level once.
    if "map_zoom" not in data and "map_radius" in data:
        try:
            legacy = float(data["map_radius"])
        except (TypeError, ValueError):
            legacy = 0.5
        data["map_zoom"] = {0.25: 11, 0.5: 10, 1.0: 9, 2.0: 8}.get(legacy, 10)
    data.pop("map_radius", None)
    try:
        zoom = int(data.get("map_zoom", 10))
    except (TypeError, ValueError):
        zoom = 10
    data["map_zoom"] = max(4, min(15, zoom))
    if data.get("map_years", 2) not in ALLOWED_MAP_YEARS:
        data["map_years"] = DEFAULTS["map_years"]
    if not isinstance(data["recent_sites"], list):
        data["recent_sites"] = list(DEFAULTS["recent_sites"])
    return data


def save_settings(data: dict, path: str | Path | None = None) -> None:
    target = Path(path) if path else default_settings_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2))
        temp.replace(target)
    except OSError:
        pass  # non-fatal: the app keeps working with in-memory settings


def remember_site(data: dict, site_number: str) -> dict:
    recent = [s for s in data.get("recent_sites", []) if s != site_number]
    recent.insert(0, site_number)
    data["recent_sites"] = recent[:8]
    data["last_site"] = site_number
    return data
