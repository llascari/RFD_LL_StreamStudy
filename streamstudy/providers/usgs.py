"""USGS NWIS: site metadata, instantaneous values and site search."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime

from ..http import HttpClient
from ..models import Sample, Series, Site, to_utc

IV_URL = "https://waterservices.usgs.gov/nwis/iv/"
DV_URL = "https://waterservices.usgs.gov/nwis/dv/"
SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
OGC_URL = (
    "https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items"
)
USER_AGENT = "RFD-StreamStudy/0.1 (+https://github.com/llascari/RFD_StreamStudy)"

PARAMETERS = {
    "00060": ("Discharge", "ft\u00b3/s"),
    "00065": ("Gage height", "ft"),
    "00045": ("Precipitation", "in"),
    "00010": ("Water temperature", "\u00b0C"),
    "00095": ("Specific conductance", "\u00b5S/cm"),
    "00300": ("Dissolved oxygen", "mg/L"),
    "63680": ("Turbidity", "FNU"),
    "72137": ("Tidal discharge", "ft\u00b3/s"),
}

DEFAULT_PARAMETERS = ("00060", "00065", "00045", "00010")

_SITE_TYPES = {
    "ST": "Stream",
    "LK": "Lake",
    "ES": "Estuary",
    "SP": "Spring",
    "GW": "Well",
    "WE": "Wetland",
    "SW": "Sinkhole",
}

# NWIS reports states as FIPS codes in the expanded site file.
STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "60": "AS", "66": "GU", "69": "MP",
    "72": "PR", "78": "VI",
}


def _number(value) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number <= -999999:
        return None
    return number


def _parse_time(value: str) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return to_utc(datetime.fromisoformat(text))
    except ValueError:
        return to_utc(datetime.fromisoformat(text[:19]))


def _rdb_rows(text: str) -> list[dict[str, str]]:
    """Turn an RDB response into dicts, skipping comments and the format row."""
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if len(lines) < 3:
        return []
    header = lines[0].split("\t")
    return [
        {name: value.strip() for name, value in zip(header, line.split("\t"))}
        for line in lines[2:]
    ]


def _site_from_row(row: dict[str, str]) -> Site | None:
    number = row.get("site_no", "").strip()
    latitude = _number(row.get("dec_lat_va"))
    longitude = _number(row.get("dec_long_va"))
    if not number or latitude is None or longitude is None:
        return None
    state_code = row.get("state_cd", "").strip().zfill(2)
    site_type = row.get("site_tp_cd", "").strip()
    return Site(
        number=number,
        name=row.get("station_nm", "").strip(),
        latitude=latitude,
        longitude=longitude,
        agency=row.get("agency_cd", "USGS").strip() or "USGS",
        state=STATE_FIPS.get(state_code, ""),
        county="",
        huc=row.get("huc_cd", "").strip(),
        site_type=_SITE_TYPES.get(site_type, site_type),
        drainage_area_sq_mi=_number(row.get("drain_area_va")),
        altitude_ft=_number(row.get("alt_va")),
    )


def parse_site_rdb(text: str) -> list[Site]:
    sites: list[Site] = []
    seen: set[str] = set()
    for row in _rdb_rows(text):
        site = _site_from_row(row)
        if site is None or site.number in seen:
            continue
        seen.add(site.number)
        sites.append(site)
    return sites


STATE_BY_POSTAL = {postal: code for code, postal in STATE_FIPS.items()}


def parse_ogc_sites(payload: dict) -> list[Site]:
    """Parse monitoring-locations GeoJSON from the USGS Water Data OGC API."""
    sites: list[Site] = []
    seen: set[str] = set()
    for feature in payload.get("features", []) or []:
        props = feature.get("properties", {}) or {}
        number = str(props.get("monitoring_location_number", "")).strip()
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if not number or number in seen or len(coordinates) < 2:
            continue
        state_code = str(props.get("state_code", "")).zfill(2)
        seen.add(number)
        sites.append(
            Site(
                number=number,
                name=props.get("monitoring_location_name", "") or number,
                latitude=float(coordinates[1]),
                longitude=float(coordinates[0]),
                agency=props.get("agency_code", "USGS") or "USGS",
                state=STATE_FIPS.get(state_code, ""),
                county=str(props.get("county_name", "")).replace(" County", ""),
                huc=props.get("hydrologic_unit_code", "") or "",
                site_type=props.get("site_type", "") or "",
                drainage_area_sq_mi=_number(props.get("drainage_area")),
                altitude_ft=_number(props.get("altitude")),
            )
        )
    return sites


def parse_dv_json(text: str) -> dict[str, dict[date, float]]:
    """Parse daily-values JSON into ``{parameter: {date: value}}``.

    Daily timestamps are naive local midnights (``2024-01-01T00:00:00.000``),
    so the date part is taken verbatim.
    """
    data = json.loads(text)
    entries = data.get("value", {}).get("timeSeries", []) or []
    result: dict[str, dict[date, float]] = {}
    for entry in entries:
        variable = entry.get("variable", {}) or {}
        codes = variable.get("variableCode") or [{}]
        code = str(codes[0].get("value", ""))
        if not code:
            continue
        values: dict[date, float] = {}
        for block in entry.get("values", []) or []:
            for item in block.get("value", []) or []:
                raw = str(item.get("dateTime", ""))
                try:
                    day = date.fromisoformat(raw[:10])
                except ValueError:
                    continue
                value = _number(item.get("value"))
                if value is not None:
                    values[day] = value
        if values:
            result[code] = values
    return result


def parse_iv_json(text: str) -> dict[str, Series]:
    """Parse the WaterML-JSON instantaneous-values response."""
    data = json.loads(text)
    entries = data.get("value", {}).get("timeSeries", []) or []
    series: dict[str, Series] = {}
    for entry in entries:
        variable = entry.get("variable", {}) or {}
        codes = variable.get("variableCode") or [{}]
        code = str(codes[0].get("value", ""))
        if not code or code in series:
            continue
        samples: list[Sample] = []
        for block in entry.get("values", []) or []:
            for item in block.get("value", []) or []:
                samples.append(
                    Sample(
                        time=_parse_time(item.get("dateTime", "")),
                        value=_number(item.get("value")),
                        qualifiers=tuple(item.get("qualifiers") or ()),
                    )
                )
        samples.sort(key=lambda sample: sample.time)
        if not samples:
            continue
        name, units = PARAMETERS.get(code, (None, None))
        if name is None:
            description = variable.get("variableDescription", "Unknown") or "Unknown"
            name = description.split(",")[0]
            units = (variable.get("unit") or {}).get("unitCode", "")
        series[code] = Series(
            code=code, name=name, units=units, samples=tuple(samples), source="USGS NWIS"
        )
    return series


class UsgsProvider:
    """Read-only access to the USGS National Water Information System."""

    name = "USGS NWIS"

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient(USER_AGENT)

    def fetch_site(self, number: str) -> Site:
        text = self._client.get_text(
            SITE_URL, {"format": "rdb", "sites": number, "siteOutput": "expanded"}
        )
        sites = parse_site_rdb(text)
        if not sites:
            raise LookupError(f"USGS site {number} was not found")
        return sites[0]

    def fetch_series(
        self,
        number: str,
        days: int = 30,
        parameters: tuple[str, ...] = DEFAULT_PARAMETERS,
    ) -> dict[str, Series]:
        days = max(1, min(int(days), 120))
        text = self._client.get_text(
            IV_URL,
            {
                "format": "json",
                "sites": number,
                "parameterCd": ",".join(parameters),
                "period": f"P{days}D",
                "siteStatus": "all",
            },
        )
        return parse_iv_json(text)

    def fetch_daily(
        self,
        number: str,
        start: date,
        end: date,
        parameters: tuple[str, ...] = ("00060", "00065"),
    ) -> dict[str, dict[date, float]]:
        """Daily mean values (statistic 00003) for multi-year analysis."""
        text = self._client.get_text(
            DV_URL,
            {
                "format": "json",
                "sites": number,
                "parameterCd": ",".join(parameters),
                "statCd": "00003",
                "startDT": start.isoformat(),
                "endDT": end.isoformat(),
                "siteStatus": "all",
            },
        )
        return parse_dv_json(text)

    def search_sites(
        self,
        *,
        state: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 400,
    ) -> list[Site]:
        """Find active surface-water gages reporting discharge."""
        params = {
            "format": "rdb",
            "siteType": "ST",
            "siteStatus": "active",
            "hasDataTypeCd": "iv",
            "parameterCd": "00060",
        }
        if state:
            params["stateCd"] = state.upper()
        if bbox:
            west, south, east, north = bbox
            params["bBox"] = f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"
        text = self._client.get_text(SITE_URL, params)
        sites = parse_site_rdb(text)[: max(1, int(limit))]
        if state:
            sites = [replace(site, state=site.state or state.upper()) for site in sites]
        return sites

    def search_by_name(
        self,
        name: str,
        *,
        state: str | None = None,
        site_type: str | None = "Stream",
        limit: int = 150,
    ) -> list[Site]:
        """Global station-name search through the USGS Water Data OGC API.

        NWIS station names are upper-case and its CQL2 ``LIKE`` is case-sensitive,
        so the term is normalised; USGS site types are ``Stream``/``Lake``/…
        """
        term = name.strip().upper().replace("'", "''")
        if not term:
            return []
        filters = [f"monitoring_location_name LIKE '%{term}%'"]
        if state:
            fips = STATE_BY_POSTAL.get(state.strip().upper())
            if fips:
                filters.append(f"state_code = '{fips}'")
        if site_type:
            filters.append(f"site_type = '{site_type}'")
        payload = self._client.get_json(
            OGC_URL,
            {
                "f": "json",
                "limit": max(1, min(int(limit), 500)),
                "filter": " AND ".join(filters),
                "filter-lang": "cql2-text",
            },
        )
        return parse_ogc_sites(payload)[: max(1, int(limit))]
