"""Assemble a DataBundle from all four providers, tolerating partial failure."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .models import DataBundle, GaugeStation, utc_now
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
