"""NWS (api.weather.gov): nearest stations, observations and forecasts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..http import HttpClient
from ..models import ForecastPeriod, GaugeStation, Sample, Series, to_utc, utc_now

API = "https://api.weather.gov"
USER_AGENT = "RFD-StreamStudy/0.1 (+https://github.com/llascari/RFD_StreamStudy)"


@dataclass(frozen=True)
class NwsLocation:
    """Everything the gridpoint/station endpoints need for one lat/lon."""

    grid_id: str
    grid_x: int
    grid_y: int
    forecast_url: str
    hourly_url: str
    stations_url: str
    city: str
    state: str
    timezone: str
    radar_station: str = ""

    @property
    def office_point(self) -> str:
        return f"{self.grid_id}/{self.grid_x},{self.grid_y}"


def _inches(value, unit: str) -> float | None:
    if value is None:
        return None
    unit = (unit or "").lower()
    if unit.endswith(":mm"):
        return value / 25.4
    if unit.endswith(":m"):
        return value * 1000.0 / 25.4
    if unit.endswith(":in"):
        return value
    return value / 25.4


def _parse_time(value: str) -> datetime:
    return to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def parse_location(payload: dict) -> NwsLocation:
    props = payload.get("properties", {}) or {}
    relative = (props.get("relativeLocation") or {}).get("properties", {}) or {}
    return NwsLocation(
        grid_id=props.get("gridId", ""),
        grid_x=int(props.get("gridX", 0) or 0),
        grid_y=int(props.get("gridY", 0) or 0),
        forecast_url=props.get("forecast", ""),
        hourly_url=props.get("forecastHourly", ""),
        stations_url=props.get("observationStations", ""),
        city=relative.get("city", ""),
        state=relative.get("state", ""),
        timezone=props.get("timeZone", ""),
        radar_station=props.get("radarStation", ""),
    )


def parse_stations(payload: dict) -> list[GaugeStation]:
    stations = []
    for feature in payload.get("features", []) or []:
        props = feature.get("properties", {}) or {}
        identifier = props.get("stationIdentifier", "")
        if not identifier:
            continue
        distance = props.get("distance") or {}
        meters = distance.get("value")
        stations.append(
            GaugeStation(
                identifier=identifier,
                name=props.get("name", identifier),
                distance_km=(float(meters) / 1000.0) if meters is not None else float("inf"),
                network="NWS",
                detail=props.get("timeZone", ""),
            )
        )
    stations.sort(key=lambda station: station.distance_km)
    return stations


def parse_observations(payload: dict) -> tuple[Series | None, Series | None]:
    """Return (precipitation, temperature) series built from observations.

    Precipitation is the reported last-hour accumulation, converted to inches;
    summing it per day yields daily totals.
    """
    precip: list[Sample] = []
    temps: list[Sample] = []
    for feature in payload.get("features", []) or []:
        props = feature.get("properties", {}) or {}
        timestamp = props.get("timestamp")
        if not timestamp:
            continue
        moment = _parse_time(timestamp)
        precip_field = props.get("precipitationLastHour") or {}
        if precip_field.get("value") is not None:
            precip.append(
                Sample(
                    time=moment,
                    value=_inches(precip_field["value"], precip_field.get("unitCode", "")),
                )
            )
        temp_field = props.get("temperature") or {}
        if temp_field.get("value") is not None and temp_field.get("unitCode", "").endswith("degC"):
            temps.append(Sample(time=moment, value=float(temp_field["value"])))

    precip.sort(key=lambda sample: sample.time)
    temps.sort(key=lambda sample: sample.time)
    precip_series = (
        Series("nws_precip", "NWS precipitation", "in", tuple(precip), "NWS obs")
        if precip
        else None
    )
    temp_series = (
        Series("nws_temp", "Air temperature", "\u00b0C", tuple(temps), "NWS obs")
        if temps
        else None
    )
    return precip_series, temp_series


def _duration_hours(text: str) -> float:
    """Hours in a simple ISO-8601 duration such as ``PT6H`` or ``P1DT2H``."""
    hours = 0.0
    match = re.search(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", text)
    if not match:
        return 0.0
    days, hour_part, minutes = (int(group or 0) for group in match.groups())
    hours = days * 24 + hour_part + minutes / 60
    return hours


def parse_qpf(payload: dict) -> tuple[tuple[datetime, float], ...]:
    """Quantitative precipitation forecast: 6-hourly amounts in inches.

    Each entry is ``(centre_of_interval, inches)`` so it can be plotted as a
    bar. Values arrive in kg/m² (equivalent to mm).
    """
    section = payload.get("properties", {}).get("quantitativePrecipitation", {}) or {}
    entries: list[tuple[datetime, float]] = []
    for item in section.get("values", []) or []:
        valid = str(item.get("validTime", ""))
        if "/" not in valid:
            continue
        start_text, duration_text = valid.split("/", 1)
        start = _parse_time(start_text)
        hours = _duration_hours(duration_text) or 6.0
        millimeters = item.get("value")
        inches = _inches(float(millimeters), "wmoUnit:mm") if millimeters is not None else 0.0
        entries.append((start + timedelta(hours=hours / 2.0), inches))
    return tuple(sorted(entries))


def parse_periods(payload: dict) -> tuple[ForecastPeriod, ...]:
    periods = []
    for item in payload.get("properties", {}).get("periods", []) or []:
        probability = (item.get("probabilityOfPrecipitation") or {}).get("value")
        periods.append(
            ForecastPeriod(
                name=item.get("name", ""),
                start=_parse_time(item["startTime"]),
                end=_parse_time(item["endTime"]),
                temperature=item.get("temperature"),
                temperature_unit="\u00b0F" if item.get("temperatureUnit") == "F" else "\u00b0C",
                precip_probability=int(probability) if probability is not None else None,
                short=item.get("shortForecast", ""),
                detailed=item.get("detailedForecast", ""),
            )
        )
    return tuple(periods)


class NwsProvider:
    """api.weather.gov client (no API key required, User-Agent mandatory)."""

    name = "NWS"

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient(USER_AGENT)

    def location(self, latitude: float, longitude: float) -> NwsLocation:
        payload = self._client.get_json(f"{API}/points/{latitude:.4f},{longitude:.4f}")
        return parse_location(payload)

    def nearest_stations(self, location: NwsLocation, limit: int = 5) -> list[GaugeStation]:
        if not location.stations_url:
            return []
        payload = self._client.get_json(location.stations_url)
        return parse_stations(payload)[: max(1, limit)]

    def observations(self, station_id: str, hours: int = 48) -> tuple[Series | None, Series | None]:
        end = utc_now()
        start = end - timedelta(hours=max(1, hours))
        payload = self._client.get_json(
            f"{API}/stations/{station_id}/observations",
            {
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "limit": 500,
            },
        )
        return parse_observations(payload)

    def hourly_forecast(self, location: NwsLocation, limit: int = 48) -> tuple[ForecastPeriod, ...]:
        payload = self._client.get_json(location.hourly_url)
        return parse_periods(payload)[: max(1, limit)]

    def daily_forecast(self, location: NwsLocation) -> tuple[ForecastPeriod, ...]:
        payload = self._client.get_json(location.forecast_url)
        return parse_periods(payload)

    def qpf(self, location: NwsLocation) -> tuple[tuple[datetime, float], ...]:
        """Gridpoint quantitative precipitation forecast (inches per interval)."""
        payload = self._client.get_json(
            f"{API}/gridpoints/{location.grid_id}/{location.grid_x},{location.grid_y}"
        )
        return parse_qpf(payload)
