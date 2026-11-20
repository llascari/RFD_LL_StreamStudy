"""Assemble a DataBundle from all four providers, tolerating partial failure."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from .analysis import mm_to_inches
from .models import DataBundle, GaugeStation, HistoryBundle, Site, utc_now
from .response import analyse_history
from .providers.cocorahs import CoCoRaHSProvider
from .providers.nws import NwsProvider
from .providers.openmeteo import OpenMeteoProvider
from .providers.usgs import UsgsProvider


@dataclass(frozen=True)
class LoadOptions:
    days: int = 14
    coco_station: str | None = None
    nws_station: str | None = None
    include_forecast: bool = True
    auto_cocorahs: bool = True


class BundleLoader:
    """Fetch everything for one site, collecting per-source errors."""

    def __init__(
        self,
        usgs: UsgsProvider,
        nws: NwsProvider,
        openmeteo: OpenMeteoProvider,
        cocorahs: CoCoRaHSProvider,
    ) -> None:
        self.usgs = usgs
        self.nws = nws
        self.openmeteo = openmeteo
        self.cocorahs = cocorahs

    @classmethod
    def from_dict(cls, providers: dict) -> "BundleLoader":
        return cls(
            usgs=providers["usgs"],
            nws=providers["nws"],
            openmeteo=providers["openmeteo"],
            cocorahs=providers["cocorahs"],
        )

    def load(self, site_number: str, options: LoadOptions | None = None) -> DataBundle:
        options = options or LoadOptions()
        days = max(1, min(int(options.days), 120))

        site = self.usgs.fetch_site(site_number)  # unknown site -> LookupError
        errors: list[str] = []

        try:
            series = self.usgs.fetch_series(site_number, days)
        except Exception as exc:  # network/HTTP failure of one source
            series = {}
            errors.append(f"USGS values: {exc}")
        if series:
            site = replace(site, params=tuple(series))

        bundle = DataBundle(site=site, usgs=series, errors=errors)

        # -- NWS: nearest station observations + official forecast
        try:
            location = self.nws.location(site.latitude, site.longitude)
            stations = self.nws.nearest_stations(location, limit=5)
            chosen = None
            if options.nws_station:
                chosen = next(
                    (s for s in stations if s.identifier.upper() == options.nws_station.upper()),
                    None,
                )
            chosen = chosen or (stations[0] if stations else None)
            bundle.nws_station = chosen
            if chosen is not None:
                precip, temperature = self.nws.observations(
                    chosen.identifier, hours=min(24 * days, 168)
                )
                bundle.nws_precip = precip
                bundle.nws_temperature = temperature
            if options.include_forecast:
                bundle.nws_daily = self.nws.daily_forecast(location)
                bundle.nws_hourly = self.nws.hourly_forecast(location, limit=48)
                try:
                    bundle.nws_qpf = self.nws.qpf(location)
                except Exception as exc:
                    errors.append(f"NWS QPF: {exc}")
        except Exception as exc:
            errors.append(f"NWS: {exc}")

        # -- Open-Meteo modelled precipitation
        try:
            model = self.openmeteo.fetch(
                site.latitude, site.longitude, past_days=min(days, 60), forecast_days=2
            )
            bundle.openmeteo_hourly = model.hourly
            bundle.openmeteo_daily = model.daily
            bundle.openmeteo_zone = model.timezone
        except Exception as exc:
            errors.append(f"Open-Meteo: {exc}")

        # -- CoCoRaHS volunteer gauge
        try:
            if options.coco_station:
                bundle.coco_station = GaugeStation(
                    identifier=options.coco_station.upper(),
                    name="CoCoRaHS gauge",
                    distance_km=float("nan"),
                    network="CoCoRaHS",
                )
                bundle.coco_daily = tuple(
                    self.cocorahs.daily_history(options.coco_station, days=min(days + 3, 40))
                )
            elif options.auto_cocorahs and site.state:
                nearest = self.cocorahs.nearest_stations(
                    site.latitude, site.longitude, site.state, days=3
                )
                if nearest:
                    bundle.coco_station = nearest[0]
                    bundle.coco_daily = tuple(
                        self.cocorahs.daily_history(
                            nearest[0].identifier, days=min(days + 3, 40)
                        )
                    )
            elif options.auto_cocorahs:
                errors.append("CoCoRaHS: site state unknown, nearest gauge not searched")
        except Exception as exc:
            errors.append(f"CoCoRaHS: {exc}")

        bundle.fetched_at = utc_now()
        return bundle

    def load_history(
        self,
        site: Site,
        *,
        years: int = 3,
        coco_station: str | None = None,
    ) -> HistoryBundle:
        """Daily flow + precipitation over several years, with a fitted response."""
        years = max(1, min(int(years), 15))
        end = date.today() - timedelta(days=1)
        try:
            start = end.replace(year=end.year - years)
        except ValueError:  # 29 February -> use the 28th
            start = end.replace(year=end.year - years, day=28)

        errors: list[str] = []
        flow: dict[date, float] = {}
        try:
            daily = self.usgs.fetch_daily(site.number, start, end, ("00060",))
            flow = daily.get("00060", {})
        except Exception as exc:  # noqa: BLE001 - one source failing is survivable
            errors.append(f"USGS daily values: {exc}")

        precip: dict[date, float] = {}
        source = ""
        if coco_station:
            try:
                days = (date.today() - start).days + 2
                rows = self.cocorahs.daily_history(coco_station, days=days)
                gauge = {day: value for day, value in rows if start <= day <= end}
                coverage = len(set(gauge) & set(flow)) / max(1, len(flow))
                if coverage >= 0.35:
                    precip = gauge
                    source = f"CoCoRaHS {coco_station} ({coverage:.0%} of days)"
                elif gauge:
                    errors.append(
                        f"CoCoRaHS {coco_station}: only {coverage:.0%} day coverage, "
                        "using ERA5 instead"
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"CoCoRaHS history: {exc}")

        if not precip:
            try:
                archive = self.openmeteo.fetch_archive(
                    site.latitude, site.longitude, start, end
                )
                precip = {
                    day: mm_to_inches(millimetres) for day, millimetres in archive.daily
                }
                source = "Open-Meteo ERA5"
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Open-Meteo archive: {exc}")

        events, fit = analyse_history(flow, precip)
        return HistoryBundle(
            start=start,
            end=end,
            precip_source=source or "unavailable",
            precip_days=len(precip),
            flow_days=len(flow),
            events=tuple(events),
            fit=fit,
            errors=errors,
        )
