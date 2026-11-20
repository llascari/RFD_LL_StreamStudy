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
    "history_years": 3,
    "coco_station": "",
    "state": "NY",
}

ALLOWED_DAYS = (7, 14, 30, 60)
ALLOWED_HISTORY_YEARS = (2, 3, 5, 10)


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
    if data["history_years"] not in ALLOWED_HISTORY_YEARS:
        data["history_years"] = DEFAULTS["history_years"]
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
