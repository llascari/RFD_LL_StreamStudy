"""Open-Meteo: hourly precipitation (observed & forecast), no API key."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone

from ..http import HttpClient

API = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
USER_AGENT = "RFD-StreamStudy/0.1 (+https://github.com/llascari/RFD_StreamStudy)"


@dataclass(frozen=True)
class OpenMeteoData:
    hourly: tuple[tuple[datetime, float, int | None], ...]  # UTC, mm, probability
    daily: tuple[tuple[date, float], ...]  # local day, mm
    timezone: str
    elevation_m: float | None = None


def parse_payload(payload: dict) -> OpenMeteoData:
    offset = int(payload.get("utc_offset_seconds", 0) or 0)
    hourly_section = payload.get("hourly", {}) or {}
    times = hourly_section.get("time", []) or []
    amounts = hourly_section.get("precipitation", []) or []
    probabilities = hourly_section.get("precipitation_probability", []) or []

    hourly: list[tuple[datetime, float, int | None]] = []
    for index, stamp in enumerate(times):
        moment = datetime.fromtimestamp(int(stamp), tz=timezone.utc)
        amount = amounts[index] if index < len(amounts) else 0.0
        probability = probabilities[index] if index < len(probabilities) else None
        hourly.append(
            (moment, float(amount or 0.0), int(probability) if probability is not None else None)
        )

    daily_section = payload.get("daily", {}) or {}
    daily_times = daily_section.get("time", []) or []
    daily_sums = daily_section.get("precipitation_sum", []) or []
    daily: list[tuple[date, float]] = []
    for index, stamp in enumerate(daily_times):
        # Daily stamps are local midnight; shift by the UTC offset to get the local day.
        day = datetime.fromtimestamp(int(stamp) + offset, tz=timezone.utc).date()
        total = daily_sums[index] if index < len(daily_sums) else 0.0
        daily.append((day, float(total or 0.0)))

    return OpenMeteoData(
        hourly=tuple(hourly),
        daily=tuple(daily),
        timezone=payload.get("timezone", "") or "",
        elevation_m=payload.get("elevation"),
    )


@dataclass(frozen=True)
class ArchiveData:
    daily: tuple[tuple[date, float], ...]  # local day, mm
    timezone: str


def parse_archive_payload(payload: dict) -> ArchiveData:
    offset = int(payload.get("utc_offset_seconds", 0) or 0)
    section = payload.get("daily", {}) or {}
    days = section.get("time", []) or []
    totals = section.get("precipitation_sum", []) or []
    daily: list[tuple[date, float]] = []
    for index, stamp in enumerate(days):
        day = datetime.fromtimestamp(int(stamp) + offset, tz=timezone.utc).date()
        total = totals[index] if index < len(totals) else 0.0
        daily.append((day, float(total or 0.0)))
    return ArchiveData(daily=tuple(daily), timezone=payload.get("timezone", "") or "")


class OpenMeteoProvider:
    """Free weather API with modelled precipitation (no key required)."""

    name = "Open-Meteo"

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient(USER_AGENT)

    def fetch(
        self,
        latitude: float,
        longitude: float,
        *,
        past_days: int = 14,
        forecast_days: int = 2,
    ) -> OpenMeteoData:
        params = {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "hourly": "precipitation,precipitation_probability",
            "daily": "precipitation_sum",
            "past_days": max(0, min(int(past_days), 92)),
            "forecast_days": max(1, min(int(forecast_days), 16)),
            "timezone": "auto",
            "timeformat": "unixtime",
        }
        payload = self._client.get_json(API, params)
        return parse_payload(payload)

    def fetch_archive(
        self, latitude: float, longitude: float, start: date, end: date
    ) -> ArchiveData:
        """Historical daily precipitation from the ERA5 reanalysis archive."""
        payload = self._client.get_json(
            ARCHIVE_API,
            {
                "latitude": f"{latitude:.4f}",
                "longitude": f"{longitude:.4f}",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": "precipitation_sum",
                "timezone": "auto",
                "timeformat": "unixtime",
            },
        )
        return parse_archive_payload(payload)
