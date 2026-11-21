"""Monitor My Watershed (WikiWatershed / EnviroDIY ODM2 portal).

Sites publish a JSON block on `/browse/`; observations are served by the
portal's AJAX endpoint (ODM2 result time series). Sensors usually report
water temperature and a **relative** water depth (in/mm) — not an absolute
stage or flow — so combine them with a nearby USGS gage rather than treating
the depth as a datum-referenced value.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from ..http import HttpClient
from ..models import MmwSite, Sample, Series

BROWSE_URL = "https://monitormywatershed.org/browse/"
AJAX_URL = "https://monitormywatershed.org/dataloader/ajax/"
SITE_URL = "https://monitormywatershed.org/sites/{code}/"
USER_AGENT = "RFD-StreamStudy/0.1 (+https://github.com/llascari/RFD_StreamStudy)"

LABELS = {
    "depth": "Relative water depth",
    "temperature": "Water temperature",
    "precipitation": "Precipitation",
    "conductance": "Specific conductance",
}

UNIT_LABELS = {
    "degC": "\u00b0C",
    "degF": "\u00b0F",
    "uS/cm": "\u00b5S/cm",
    "ms/cm": "mS/cm",
    "in": "in",
    "mm": "mm",
    "NTU": "NTU",
}

_MISSING = -9998.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def parse_sites(html: str) -> list[MmwSite]:
    """Extract the site list embedded in the Browse Sites page."""
    match = re.search(r'<script[^>]*id="sites-data"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1), strict=False)
    except ValueError:
        return []
    sites: list[MmwSite] = []
    for item in payload or []:
        try:
            latitude = float(item["latitude"])
            longitude = float(item["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        code = str(item.get("code", "")).strip()
        if not code:
            continue
        detail = str(item.get("detail_link", "") or "")
        url = (
            "https://monitormywatershed.org" + detail
            if detail.startswith("/")
            else detail or SITE_URL.format(code=code)
        )
        sites.append(
            MmwSite(
                identifier=code,
                name=item.get("name") or code,
                latitude=latitude,
                longitude=longitude,
                site_id=str(item.get("id", "")),
                organization=item.get("organization", "") or "",
                site_type=item.get("type", "") or "",
                stream_name=item.get("stream_name", "") or "",
                url=url,
            )
        )
    return sites


def _payload(text: str):
    """The portal sometimes double-encodes JSON (a JSON string containing JSON)."""
    data = json.loads(text)
    if isinstance(data, str):
        data = json.loads(data)
    return data


def parse_metadata(text: str) -> list[dict]:
    data = _payload(text)
    return [item for item in data or [] if isinstance(item, dict) and item.get("resultid")]


def parse_timeseries(text: str) -> list[Sample]:
    data = _payload(text)
    dates = data.get("valuedatetime", {}) or {}
    values = data.get("datavalue", {}) or {}
    samples: list[Sample] = []
    for key, stamp in dates.items():
        raw = values.get(key)
        try:
            value = float(raw)
            milliseconds = float(stamp)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= _MISSING:
            continue
        try:
            moment = datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            continue
        samples.append(Sample(time=moment, value=value))
    samples.sort(key=lambda sample: sample.time)
    return samples


def choose_results(results: list[dict]) -> dict[str, dict]:
    """Pick the most useful water-quality result per variable class."""

    def aqueous(result: dict) -> bool:
        medium = str(result.get("sampledmediumcv", "")).lower()
        return any(word in medium for word in ("aqueous", "liquid", "water"))

    chosen: dict[str, dict] = {}
    for result in results:
        if not aqueous(result):
            continue
        name = str(result.get("variablenamecv", "")).lower()
        units = str(result.get("unitsabbreviation", "")).lower()
        if "depth" in name:
            chosen.setdefault("depth", result)
        elif "temperature" in name:
            current = chosen.get("temperature")
            if current is None or (
                units in ("degc", "\u00b0c") and
                str(current.get("unitsabbreviation", "")).lower() not in ("degc", "\u00b0c")
            ):
                chosen["temperature"] = result
        elif "precipitation" in name:
            chosen.setdefault("precipitation", result)
        elif "conductance" in name:
            chosen.setdefault("conductance", result)
    return chosen


class MonitorMyWatershedProvider:
    """Public ODM2 portal used by EnviroDIY / WikiWatershed sensors."""

    name = "Monitor My Watershed"

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client or HttpClient(USER_AGENT)
        self._sites: list[MmwSite] | None = None

    def sites(self) -> list[MmwSite]:
        if self._sites is None:
            self._sites = parse_sites(self._client.get_text(BROWSE_URL))
        return list(self._sites)

    def nearest_sites(
        self,
        latitude: float,
        longitude: float,
        *,
        limit: int = 6,
        max_km: float = 60.0,
    ) -> list[MmwSite]:
        nearby = []
        for site in self.sites():
            distance = _haversine_km(latitude, longitude, site.latitude, site.longitude)
            if distance <= max_km:
                nearby.append(replace(site, distance_km=distance))
        nearby.sort(key=lambda site: site.distance_km)
        return nearby[: max(1, int(limit))]

    def _post(self, request: dict) -> str:
        return self._client.post_form(AJAX_URL, {"request_data": json.dumps(request)})

    def results(self, site_code: str) -> list[dict]:
        return parse_metadata(
            self._post(
                {
                    "method": "get_sampling_feature_metadata",
                    "sampling_feature_code": site_code,
                }
            )
        )

    def series(self, result_id: int, start: date, end: date) -> list[Sample]:
        return parse_timeseries(
            self._post(
                {
                    "method": "get_result_timeseries",
                    "resultid": int(result_id),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                }
            )
        )

    def sensors_for_site(self, site_code: str, *, days: int = 14) -> dict[str, Series]:
        """Return usable sensor series (depth / temperature / rain / conductance)."""
        end = date.today()
        start = end - timedelta(days=max(1, int(days)))
        chosen = choose_results(self.results(site_code))
        series: dict[str, Series] = {}
        for key, result in chosen.items():
            try:
                samples = self.series(result["resultid"], start, end)
            except Exception:  # noqa: BLE001 - one variable failing is survivable
                continue
            if not samples:
                continue
            units = UNIT_LABELS.get(
                str(result.get("unitsabbreviation", "")), result.get("unitsabbreviation", "")
            )
            series[key] = Series(
                code=key,
                name=LABELS[key],
                units=units,
                samples=tuple(samples),
                source="Monitor My Watershed",
            )
        return series
