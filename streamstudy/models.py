"""Core data types shared by providers, analysis and the UI.

Every timestamp is timezone-aware UTC once it enters the app; the views
convert to the user's local time for display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Sample:
    """One observation of a time series."""

    time: datetime
    value: float | None
    qualifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Series:
    """A named time series with a unit and provenance."""

    code: str
    name: str
    units: str
    samples: tuple[Sample, ...]
    source: str

    @property
    def valid(self) -> tuple[Sample, ...]:
        return tuple(sample for sample in self.samples if sample.value is not None)

    @property
    def latest(self) -> Sample | None:
        valid = self.valid
        return valid[-1] if valid else None

    @property
    def span(self) -> tuple[datetime, datetime] | None:
        valid = self.valid
        if not valid:
            return None
        return valid[0].time, valid[-1].time

    @property
    def provisional(self) -> bool:
        return any("P" in sample.qualifiers for sample in self.samples)


@dataclass(frozen=True)
class SeriesStats:
    count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    latest: float


@dataclass(frozen=True)
class Site:
    """A USGS monitoring location."""

    number: str
    name: str
    latitude: float
    longitude: float
    agency: str = "USGS"
    state: str = ""
    county: str = ""
    huc: str = ""
    site_type: str = ""
    drainage_area_sq_mi: float | None = None
    altitude_ft: float | None = None
    params: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.name} ({self.number})"

    @property
    def url(self) -> str:
        return f"https://waterdata.usgs.gov/monitoring-location/USGS-{self.number}/"

    @property
    def coordinates(self) -> str:
        return f"{self.latitude:.4f}, {self.longitude:.4f}"


@dataclass(frozen=True)
class GaugeStation:
    """A nearby reference station (weather station or rain gauge)."""

    identifier: str
    name: str
    distance_km: float
    network: str
    latitude: float | None = None
    longitude: float | None = None
    detail: str = ""


@dataclass(frozen=True)
class ForecastPeriod:
    name: str
    start: datetime
    end: datetime
    temperature: float | None
    temperature_unit: str
    precip_probability: int | None
    short: str
    detailed: str = ""


@dataclass(frozen=True)
class FlowEvent:
    """One rain storm and the streamflow rise it produced."""

    start: date
    end: date
    rain_in: float
    rain_days: int
    baseline_cfs: float
    peak_cfs: float
    peak_date: date
    rise_cfs: float
    lag_hours: float
    half_life_days: float | None = None


@dataclass(frozen=True)
class ResponseFit:
    """Empirical rainfall-runoff relationship for one gage."""

    events: int
    slope: float  # cfs per inch, fitted through the origin
    ratio_p10: float
    ratio_p50: float
    ratio_p90: float
    r_squared: float
    lag_p50_hours: float
    lag_p10_hours: float
    lag_p90_hours: float
    half_life_days: float
    confidence: str


@dataclass
class HistoryBundle:
    """Multi-year daily precipitation + flow, with derived events and fit."""

    start: date
    end: date
    precip_source: str
    precip_days: int
    flow_days: int
    events: tuple[FlowEvent, ...] = ()
    fit: ResponseFit | None = None
    precip: tuple[tuple[date, float], ...] = ()
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MmwSite:
    """A Monitor My Watershed / EnviroDIY station."""

    identifier: str
    name: str
    latitude: float
    longitude: float
    site_id: str = ""
    organization: str = ""
    site_type: str = ""
    stream_name: str = ""
    distance_km: float = float("nan")
    url: str = ""


@dataclass
class DataBundle:
    """Everything fetched for one site, ready for the views to render."""

    site: Site
    usgs: dict[str, Series] = field(default_factory=dict)
    nws_station: GaugeStation | None = None
    nws_precip: Series | None = None
    nws_temperature: Series | None = None
    nws_hourly: tuple[ForecastPeriod, ...] = ()
    nws_daily: tuple[ForecastPeriod, ...] = ()
    nws_qpf: tuple[tuple[datetime, float], ...] = ()
    openmeteo_hourly: tuple[tuple[datetime, float, int | None], ...] = ()
    openmeteo_daily: tuple[tuple[date, float], ...] = ()
    openmeteo_zone: str = ""
    coco_station: GaugeStation | None = None
    coco_daily: tuple[tuple[date, float], ...] = ()
    mmw_site: MmwSite | None = None
    mmw_sites: tuple[MmwSite, ...] = ()
    mmw_series: dict[str, Series] = field(default_factory=dict)
    history: HistoryBundle | None = None
    errors: list[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=utc_now)

    def series(self, code: str) -> Series | None:
        return self.usgs.get(code)

    @property
    def has_usgs(self) -> bool:
        return bool(self.usgs)

    @property
    def ok_sources(self) -> int:
        """How many of the four data networks answered."""
        checks = (
            bool(self.usgs),
            bool(self.nws_daily or self.nws_precip or self.nws_qpf),
            bool(self.openmeteo_hourly or self.openmeteo_daily),
            bool(self.coco_daily),
        )
        return sum(1 for check in checks if check)

    @property
    def has_mmw(self) -> bool:
        return bool(self.mmw_site and self.mmw_series)
