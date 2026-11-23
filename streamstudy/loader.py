"""Assemble a DataBundle from all four providers, tolerating partial failure."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from datetime import date, timedelta

from .analysis import mm_to_inches
from .analysis_window import TimeWindow, last_years_window, preset_window
from .correlation import RegionalAnalysis, build_regional
from .ranking import Ranking, build_ranking
from .models import DataBundle, GaugeStation, HistoryBundle, Site, utc_now
from .response import analyse_history
from .providers.cocorahs import CoCoRaHSProvider
from .providers.monitormywatershed import MonitorMyWatershedProvider
from .providers.nws import NwsProvider
from .providers.openmeteo import OpenMeteoProvider
from .providers.usgs import UsgsProvider
from .report import ReportData, ReportSite
from .thermal import series_water_c


class ReportCancelled(Exception):
    """Raised when the user cancels a long report job."""


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class LoadOptions:
    days: int = 14
    analysis_window: TimeWindow | None = None
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
                site.latitude, site.longitude, past_days=min(days, 60), forecast_days=10
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

        # -- USGS daily water temperature for the selected analysis window
        try:
            window = (options.analysis_window or preset_window("1y")).clipped()
            daily = self.usgs.fetch_daily(
                site.number, window.start, window.end, ("00010",)
            )
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
        window: TimeWindow | None = None,
        years: int | None = None,
        coco_station: str | None = None,
        stage=None,
    ) -> HistoryBundle:
        """Daily flow + precipitation for a window, with a fitted response.

        ``stage`` is an optional ``stage(message)`` callback used by long report
        jobs to narrate which source is being fetched.
        """
        if window is None:
            window = (
                last_years_window(years) if years is not None else preset_window("1y")
            )
        window = window.clipped()
        start, end = window.start, window.end

        errors: list[str] = []
        flow: dict[date, float] = {}
        water_temp: dict[date, float] = {}
        if stage is not None:
            stage("USGS daily flow and water temperature")
        try:
            daily = self.usgs.fetch_daily(
                site.number, start, end, ("00060", "00010")
            )
            flow = daily.get("00060", {})
            water_temp = daily.get("00010", {})
        except Exception as exc:  # noqa: BLE001 - one source failing is survivable
            errors.append(f"USGS daily values: {exc}")

        precip: dict[date, float] = {}
        source = ""
        if coco_station:
            if stage is not None:
                stage("CoCoRaHS precipitation history")
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

        archive = None
        archive_attempted = False
        if not precip:
            archive_attempted = True
            if stage is not None:
                stage("Open-Meteo ERA5 precipitation and weather")
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

        # Air temperature and sunshine come from the same archive response as
        # the ERA5 rain when it was used; otherwise fetch the archive once more.
        if archive is None and not archive_attempted:
            if stage is not None:
                stage("Open-Meteo ERA5 air temperature and sunshine")
            try:
                archive = self.openmeteo.fetch_archive(
                    site.latitude, site.longitude, start, end
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Open-Meteo weather archive: {exc}")

        air_mean: dict[date, float] = {}
        air_max: dict[date, float] = {}
        air_min: dict[date, float] = {}
        sunshine: dict[date, float] = {}
        if archive is not None:
            for day in archive.weather:
                if day.mean_c is not None:
                    air_mean[day.day] = day.mean_c
                if day.max_c is not None:
                    air_max[day.day] = day.max_c
                if day.min_c is not None:
                    air_min[day.day] = day.min_c
                if day.sunshine_hours is not None:
                    sunshine[day.day] = day.sunshine_hours

        if stage is not None:
            stage("Fitting rainfall-runoff response")
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
            water_temp_daily=water_temp,
            flow_daily=flow,
            air_mean=air_mean,
            air_max=air_max,
            air_min=air_min,
            sunshine=sunshine,
            errors=errors,
        )

    def load_report_site(
        self,
        site: Site,
        window: TimeWindow,
        *,
        coco_station: str | None = None,
        include_mmw: bool = True,
        retries: int = 2,
        delay: float = 0.0,
        cancel=None,
        progress=None,
    ) -> ReportSite:
        """Load one gage for a report, retrying transport failures.

        ``progress(fraction, message)`` is local to this site (0 to 1) and
        narrates the USGS, precipitation, ERA5 and fitting stages.
        """
        attempts = max(1, int(retries) + 1)
        last_error: Exception | None = None
        mark = 0.05

        def report_stage(message: str) -> None:
            nonlocal mark
            mark = min(0.65, mark + 0.13)
            if progress is not None:
                progress(mark, message)

        for attempt in range(attempts):
            if cancel is not None and cancel():
                raise ReportCancelled()
            try:
                history = self.load_history(
                    site,
                    window=window,
                    coco_station=coco_station,
                    stage=report_stage if progress is not None else None,
                )
                if not history.flow_daily:
                    raise RuntimeError("USGS returned no daily flow values")
                errors = list(history.errors)
                mmw_name = ""
                mmw_temp: dict[date, float] = {}
                mmw = getattr(self, "mmw", None)
                if include_mmw and mmw is not None:
                    if progress is not None:
                        progress(0.72, "Checking nearby Monitor My Watershed sensors")
                    try:
                        candidates = mmw.nearest_sites(
                            site.latitude, site.longitude, limit=6, max_km=60.0
                        )
                        for candidate in candidates:
                            found = mmw.sensors_for_site(candidate.identifier, days=30)
                            if "temperature" not in found:
                                continue
                            values = series_water_c(found["temperature"])
                            if len(values) >= 5:
                                mmw_temp = values
                                mmw_name = (
                                    f"{candidate.name or candidate.identifier} "
                                    f"({candidate.distance_km:.0f} km)"
                                )
                                break
                    except Exception as exc:  # noqa: BLE001 - report continues without sensors
                        errors.append(f"Monitor My Watershed: {exc}")
                if progress is not None:
                    progress(0.9, "Preparing report data")
                    progress(1.0, "Site ready")
                return ReportSite(
                    site=site,
                    history=history,
                    air_mean=dict(history.air_mean),
                    air_max=dict(history.air_max),
                    air_min=dict(history.air_min),
                    sunshine=dict(history.sunshine),
                    mmw_name=mmw_name,
                    mmw_temp_daily=mmw_temp,
                    errors=tuple(errors),
                )
            except ReportCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - retried below
                last_error = exc
                if attempt + 1 < attempts:
                    if progress is not None:
                        progress(
                            mark,
                            f"Retrying after attempt {attempt + 1} of {attempts}: {exc}",
                        )
                    if delay > 0:
                        if cancel is not None and cancel():
                            raise ReportCancelled()
                        time.sleep(delay)
        raise RuntimeError(f"{site.number}: {last_error}")

    def load_report_region(
        self,
        primary_site: Site,
        window: TimeWindow,
        *,
        radius_km: float = 10.0,
        include_region: bool = True,
        max_sites: int = 6,
        threshold_c: float = 20.0,
        coco_station: str | None = None,
        include_mmw: bool = True,
        retries: int = 2,
        delay: float = 0.0,
        progress=None,
        cancel=None,
    ) -> ReportData:
        """Build a single-gage or radius report, one site at a time.

        ``progress`` is called as ``progress(fraction, message)``. ``cancel``
        is polled between sites and between retries; when it returns true a
        :class:`ReportCancelled` is raised. A site that still fails after its
        retries is listed in ``ReportData.failures`` and the report continues.
        """
        window = window.clipped()
        failures: list[str] = []
        max_sites = max(1, min(int(max_sites), 12))
        radius_km = max(0.0, min(float(radius_km), 100.0))

        nearby: list[tuple[Site, float]] = []
        if include_region and radius_km > 0 and max_sites > 1:
            lat_span = radius_km / 111.0
            lon_span = radius_km / max(0.2, 111.0 * math.cos(math.radians(primary_site.latitude)))
            bbox = (
                primary_site.longitude - lon_span,
                primary_site.latitude - lat_span,
                primary_site.longitude + lon_span,
                primary_site.latitude + lat_span,
            )
            if progress is not None:
                progress(0.01, "Searching for nearby USGS gages")
            try:
                found = self.usgs.search_sites(bbox=bbox, limit=max(30, max_sites * 6))
            except Exception as exc:  # noqa: BLE001 - primary report can still run
                failures.append(f"Nearby gage search: {exc}")
                found = []
            for candidate in found:
                if candidate.number == primary_site.number:
                    continue
                distance = _haversine_km(
                    primary_site.latitude,
                    primary_site.longitude,
                    candidate.latitude,
                    candidate.longitude,
                )
                if distance <= radius_km:
                    nearby.append((candidate, distance))
            nearby.sort(key=lambda item: item[1])
            nearby = nearby[: max_sites - 1]

        total = 1 + len(nearby)
        last_fraction = 0.0

        def site_progress(fraction, message, *, index: int, label: str) -> None:
            nonlocal last_fraction
            value = (index - 1 + max(0.0, min(1.0, float(fraction)))) / total
            last_fraction = max(last_fraction, value)
            if progress is not None:
                progress(
                    last_fraction,
                    f"Site {index} of {total} \u00b7 {label}: {message}",
                )

        if progress is not None:
            progress(0.02, f"Site 1 of {total} \u00b7 {primary_site.number}: starting")
        primary = self.load_report_site(
            primary_site,
            window,
            coco_station=coco_station,
            include_mmw=include_mmw,
            retries=retries,
            delay=delay,
            cancel=cancel,
            progress=(
                lambda fraction, message: site_progress(
                    fraction,
                    message,
                    index=1,
                    label=primary_site.number,
                )
            )
            if progress is not None
            else None,
        )

        region: list[ReportSite] = []
        for index, (candidate, distance) in enumerate(nearby, start=2):
            if cancel is not None and cancel():
                raise ReportCancelled()
            if progress is not None:
                progress(
                    (index - 1) / total,
                    f"Site {index} of {total} \u00b7 {candidate.number}: "
                    f"starting ({distance:.1f} km away)",
                )
            try:
                report = self.load_report_site(
                    candidate,
                    window,
                    include_mmw=include_mmw,
                    retries=retries,
                    delay=delay,
                    cancel=cancel,
                    progress=(
                        lambda fraction, message, idx=index, number=candidate.number: site_progress(
                            fraction,
                            message,
                            index=idx,
                            label=number,
                        )
                    )
                    if progress is not None
                    else None,
                )
                region.append(replace(report, distance_km=distance))
            except ReportCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad gage must not stop the report
                failures.append(f"{candidate.number}: {exc}")
                if progress is not None:
                    progress(
                        index / total,
                        f"Site {index} of {total} \u00b7 {candidate.number}: skipped ({exc})",
                    )

        if progress is not None:
            progress(
                1.0,
                f"All {total} sites processed; preparing the PDF",
            )
        return ReportData(
            primary=primary,
            window=window,
            radius_km=radius_km if include_region else 0.0,
            threshold_c=max(0.0, min(40.0, float(threshold_c))),
            failures=tuple(failures),
            region=tuple(region),
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
