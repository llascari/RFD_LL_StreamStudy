"""CoCoRaHS: volunteer daily rain-gauge reports via the public CSV export."""

from __future__ import annotations

import csv
import io
import math
from datetime import date, timedelta

from ..http import HttpClient
from ..models import GaugeStation

EXPORT = "https://data.cocorahs.org/cocorahs/export/exportreports.aspx"
USER_AGENT = "RFD-StreamStudy/0.1 (+https://github.com/llascari/RFD_StreamStudy)"


def parse_amount(value: str) -> float | None:
    """CoCoRaHS uses ``T`` for trace, ``NA`` for missing."""
    text = (value or "").strip()
    if not text or text.upper() == "NA":
        return None
    if text.upper() == "T":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def parse_report_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    rows = []
    for row in reader:
        cleaned = {(key or "").strip(): (value or "").strip() for key, value in row.items()}
        if not cleaned.get("StationNumber"):
            continue
        rows.append(cleaned)
    return rows


def parse_station_history(text: str) -> list[tuple[date, float]]:
    """Daily totals for one station, oldest first (one report per day)."""
    totals: dict[date, float] = {}
    for row in parse_report_csv(text):
        amount = parse_amount(row.get("TotalPrecipAmt", ""))
        if amount is None:
            continue
        try:
            day = date.fromisoformat(row.get("ObservationDate", ""))
        except ValueError:
            continue
        totals[day] = amount
    return sorted(totals.items())


def parse_nearest(text: str, latitude: float, longitude: float, limit: int = 5) -> list[GaugeStation]:
    """Pick the closest reporting gauges from a state-wide export."""
    best: dict[str, GaugeStation] = {}
    for row in parse_report_csv(text):
        try:
            lat = float(row.get("Latitude", ""))
            lon = float(row.get("Longitude", ""))
        except ValueError:
            continue
        station = row.get("StationNumber", "")
        if not station:
            continue
        distance = _distance_km(latitude, longitude, lat, lon)
        amount = parse_amount(row.get("TotalPrecipAmt", ""))
        detail = f"{amount:.2f} in on {row.get('ObservationDate', '')}" if amount is not None else ""
        candidate = GaugeStation(
            identifier=station,
            name=row.get("StationName", station),
            distance_km=distance,
            network="CoCoRaHS",
            latitude=lat,
            longitude=lon,
            detail=detail,
        )
        current = best.get(station)
        if current is None or candidate.distance_km < current.distance_km:
            best[station] = candidate
    return sorted(best.values(), key=lambda station: station.distance_km)[:limit]


class CoCoRaHSProvider:
    """Daily volunteer gauge reports (inches, 24 h totals ~7 AM local)."""

    name = "CoCoRaHS"

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient(USER_AGENT)

    def _export(self, start: date, end: date, *, state: str | None = None, station: str | None = None) -> str:
        params = {
            "ReportType": "Daily",
            "Format": "CSV",
            "StartDate": start.isoformat(),
            "EndDate": end.isoformat(),
            "dtf": "1",
        }
        if state:
            params["State"] = state.upper()
        if station:
            params["Station"] = station.upper()
        return self._client.get_text(EXPORT, params)

    def daily_history(self, station: str, days: int = 14) -> list[tuple[date, float]]:
        end = date.today()
        start = end - timedelta(days=max(1, int(days)) - 1)
        state = station.split("-")[0] if "-" in station else None
        return parse_station_history(self._export(start, end, state=state, station=station))

    def nearest_stations(
        self, latitude: float, longitude: float, state: str, days: int = 3, limit: int = 5
    ) -> list[GaugeStation]:
        end = date.today()
        start = end - timedelta(days=max(1, int(days)) - 1)
        text = self._export(start, end, state=state)
        return parse_nearest(text, latitude, longitude, limit)
