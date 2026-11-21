"""Data providers for the streams and precipitation networks."""

from __future__ import annotations

from ..http import HttpClient
from .cocorahs import CoCoRaHSProvider
from .monitormywatershed import MonitorMyWatershedProvider
from .nws import NwsProvider
from .openmeteo import OpenMeteoProvider
from .usgs import UsgsProvider

__all__ = [
    "CoCoRaHSProvider",
    "MonitorMyWatershedProvider",
    "NwsProvider",
    "OpenMeteoProvider",
    "UsgsProvider",
    "build_providers",
]


def build_providers(client: HttpClient | None = None) -> dict[str, object]:
    client = client or HttpClient(
        "RFD-StreamStudy/0.1 (+https://github.com/llascari/RFD_StreamStudy)"
    )
    return {
        "usgs": UsgsProvider(client),
        "nws": NwsProvider(client),
        "openmeteo": OpenMeteoProvider(client),
        "cocorahs": CoCoRaHSProvider(client),
        "mmw": MonitorMyWatershedProvider(client),
    }
