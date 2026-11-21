"""Assemble a DataBundle from all four providers, tolerating partial failure."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from .analysis import mm_to_inches
from .correlation import RegionalAnalysis, build_regional
from .ranking import Ranking, build_ranking
from .models import DataBundle, GaugeStation, HistoryBundle, Site, utc_now
from .response import analyse_history
from .providers.cocorahs import CoCoRaHSProvider
from .providers.monitormywatershed import MonitorMyWatershedProvider
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
        mmw: MonitorMyWatershedProvider | None = None,
    ) -> None:
        self.usgs = usgs
        self.nws = nws
        self.openmeteo = openmeteo
        self.cocorahs = cocorahs
        self.mmw = mmw

    @classmethod
    def from_dict(cls, providers: dict) -> "BundleLoader":
        return cls(
            usgs=providers["usgs"],
            nws=providers["nws"],
            openmeteo=providers["openmeteo"],
            cocorahs=providers["cocorahs"],
            mmw=providers.get("mmw"),
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

        # -- Open-Meteo daily air temperature, sunshine and cloud cover
        try:
            weather = self.openmeteo.fetch_weather(
                site.latitude,
                site.longitude,
                past_days=min(days + 1, 30),
                forecast_days=2,
            )
            bundle.weather_days = weather.daily
            bundle.weather_zone = weather.timezone
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Open-Meteo weather: {exc}")

        # -- A year of USGS daily water temperature for duration statistics
        try:
            end = date.today()
            start = end - timedelta(days=365)
            daily = self.usgs.fetch_daily(site.number, start, end, ("00010",))
            bundle.water_temp_daily = daily.get("00010", {})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"USGS water temperature: {exc}")

        # -- Monitor My Watershed / EnviroDIY sensors (relative depth, temperature)
        if self.mmw is not None:
            try:
                candidates = self.mmw.nearest_sites(
                    site.latitude, site.longitude, limit=4, max_km=60.0
                )
                contributing = []
                merged: dict[str, Series] = {}
                for candidate in candidates:
                    if len(contributing) >= 2:
                        break
                    found = self.mmw.sensors_for_site(
                        candidate.identifier, days=min(days, 30)
                    )
                    if not found:
                        continue
                    contributing.append(candidate)
                    for key, value in found.items():
                        merged.setdefault(key, value)
                    if {"depth", "temperature"} <= set(merged):
                        break
                if merged:
                    bundle.mmw_site = contributing[0]
                    bundle.mmw_sites = tuple(contributing)
                    bundle.mmw_series = merged
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Monitor My Watershed: {exc}")

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
                    day: mm_to_inches(millimetres)
                    for day, millimetres in archive.daily
                    if start <= day <= end
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
            precip=tuple(sorted(precip.items())),
            errors=errors,
        )

    def rank_sites(
        self,
        sites: list[Site],
        *,
        years: int = 2,
        rain: dict[date, float] | None = None,
        base_site: Site | None = None,
        max_sites: int = 5,
    ) -> Ranking:
        """Fetch flow/temperature history and rank nearby gages as a hub."""
        end = date.today() - timedelta(days=1)
        try:
            start = end.replace(year=end.year - max(1, int(years)))
        except ValueError:
            start = end.replace(year=end.year - max(1, int(years)), day=28)
        chosen = tuple(sites[: max(1, int(max_sites))])
        flows: dict[str, dict[date, float]] = {}
        temperatures: dict[str, dict[date, float]] = {}
        fits = {}
        for site in chosen:
            try:
                daily = self.usgs.fetch_daily(
                    site.number, start, end, ("00060", "00010")
                )
            except Exception:  # noqa: BLE001 - skip unusable candidates
                continue
            flows[site.number] = daily.get("00060", {})
            temperatures[site.number] = daily.get("00010", {})
            _, fit = analyse_history(flows[site.number], rain or {})
            fits[site.number] = fit
        return build_ranking(chosen, flows, temperatures, fits, base_site)

    def load_regional(
        self,
        sites: list[Site],
        *,
        years: int = 2,
        gauge_series: dict[date, float] | None = None,
        gauge_label: str = "CoCoRaHS gauge",
        max_gages: int = 6,
        max_lag: int = 5,
    ) -> RegionalAnalysis:
        """Daily flows for nearby gages and their correlation with rain/flow."""
        years = max(1, min(int(years), 10))
        end = date.today() - timedelta(days=1)
        try:
            start = end.replace(year=end.year - years)
        except ValueError:
            start = end.replace(year=end.year - years, day=28)

        chosen = tuple(sites[: max(1, int(max_gages))])
        flows: dict[str, dict[date, float]] = {}
        onsite: dict[str, dict[date, float]] = {}
        errors: list[str] = []
        for site in chosen:
            try:
                daily = self.usgs.fetch_daily(
                    site.number, start, end, ("00060", "00045")
                )
                if "00060" in daily:
                    flows[site.number] = daily["00060"]
                if "00045" in daily:
                    onsite[f"USGS {site.number}"] = daily["00045"]
            except Exception as exc:  # noqa: BLE001
                errors.append(f"USGS {site.number}: {exc}")

        precip: dict[str, dict[date, float]] = {}
        if chosen:
            latitude = sum(site.latitude for site in chosen) / len(chosen)
            longitude = sum(site.longitude for site in chosen) / len(chosen)
            try:
                archive = self.openmeteo.fetch_archive(
                    latitude, longitude, start, end
                )
                precip["ERA5 (map centre)"] = {
                    day: mm_to_inches(millimetres)
                    for day, millimetres in archive.daily
                    if start <= day <= end
                }
            except Exception as exc:  # noqa: BLE001
                errors.append(f"ERA5: {exc}")
        if gauge_series:
            precip[gauge_label] = dict(gauge_series)
        precip.update(onsite)

        return build_regional(
            chosen,
            flows,
            precip,
            start=start,
            end=end,
            max_lag=max_lag,
            errors=errors,
        )
