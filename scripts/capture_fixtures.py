#!/usr/bin/env python3
"""Refresh tests/fixtures/ from the live public APIs.

Usage:
    python3 scripts/capture_fixtures.py

Requires network access. Responses are trimmed so the fixtures stay small and the tests stay
deterministic in shape (counts of points/days are preserved; values are whatever the API
returns today). Absolute dates are fixed where the tests depend on them.

After refreshing, run the test suite; if a provider changed something structural, update the
parser and the fixture-backed assertions together.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
UA = "RFD-StreamStudy/0.1 (+https://github.com/llascari/RFD_StreamStudy)"
SITE = "0423205010"


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", "replace")


def fetch_json(url: str) -> dict:
    return json.loads(fetch(url))


def fetch_post(url: str, data: dict) -> str:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", "replace")


def save(name: str, text: str) -> None:
    path = FIXTURES / name
    path.write_text(text)
    print(f"{name:32} {len(text):>8,} bytes")


def save_json(name: str, payload) -> None:
    save(name, json.dumps(payload, indent=1))


def usgs_site() -> None:
    save(
        "usgs_site.rdb",
        fetch(
            "https://waterservices.usgs.gov/nwis/site/"
            f"?format=rdb&sites={SITE}&siteOutput=expanded"
        ),
    )


def usgs_iv() -> None:
    payload = fetch_json(
        "https://waterservices.usgs.gov/nwis/iv/"
        f"?format=json&sites={SITE}&parameterCd=00060,00065&period=P2D"
    )
    for series in payload["value"]["timeSeries"]:
        series["values"][0]["value"] = series["values"][0]["value"][-12:]
        series["values"] = series["values"][:1]
    save_json("usgs_iv.json", payload)


def usgs_dv() -> None:
    start, end = date(2024, 1, 1), date(2024, 1, 21)
    payload = fetch_json(
        "https://waterservices.usgs.gov/nwis/dv/"
        f"?format=json&sites={SITE}&parameterCd=00060&statCd=00003"
        f"&startDT={start}&endDT={end}"
    )
    for series in payload["value"]["timeSeries"]:
        series["values"][0]["value"] = series["values"][0]["value"][:21]
        series["values"] = series["values"][:1]
    save_json("usgs_dv.json", payload)


def usgs_name_search() -> None:
    query = urlencode(
        {
            "f": "json",
            "limit": 10,
            "filter": (
                "monitoring_location_name LIKE '%IRONDEQUOIT%' "
                "AND state_code = '36' AND site_type = 'Stream'"
            ),
            "filter-lang": "cql2-text",
        }
    )
    payload = fetch_json(
        "https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?"
        + query
    )
    save_json("ogc_locations.json", payload)


def nws() -> None:
    points = fetch_json("https://api.weather.gov/points/43.1448,-77.5120")
    keep = (
        "gridId",
        "gridX",
        "gridY",
        "forecast",
        "forecastHourly",
        "observationStations",
        "relativeLocation",
        "timeZone",
        "radarStation",
    )
    trimmed = dict(points)
    trimmed["properties"] = {
        key: points["properties"][key] for key in keep if key in points["properties"]
    }
    save_json("nws_points.json", trimmed)

    props = points["properties"]
    stations = fetch_json(props["observationStations"])
    stations["features"] = stations["features"][:3]
    save_json("nws_stations.json", stations)

    hourly = fetch_json(props["forecastHourly"])
    hourly["properties"]["periods"] = hourly["properties"]["periods"][:3]
    save_json("nws_hourly.json", hourly)

    daily = fetch_json(props["forecast"])
    daily["properties"]["periods"] = daily["properties"]["periods"][:4]
    save_json("nws_daily.json", daily)

    grid = fetch_json(
        f"https://api.weather.gov/gridpoints/{props['gridId']}/{props['gridX']},{props['gridY']}"
    )
    save_json(
        "nws_grid.json",
        {
            "@context": grid.get("@context"),
            "type": "Feature",
            "properties": {
                "gridId": props.get("gridId"),
                "gridX": props.get("gridX"),
                "gridY": props.get("gridY"),
                "updateTime": grid["properties"].get("updateTime"),
                "quantitativePrecipitation": grid["properties"]["quantitativePrecipitation"],
            },
        },
    )

    end = date.today()
    start = end - timedelta(days=7)
    observations = fetch_json(
        "https://api.weather.gov/stations/KROC/observations"
        f"?start={start}T00:00:00Z&end={end}T23:59:00Z&limit=500"
    )
    with_precip = [
        feature
        for feature in observations["features"]
        if feature["properties"].get("precipitationLastHour")
    ]
    observations["features"] = (with_precip or observations["features"])[:8]
    save_json("nws_observations.json", observations)


def monitor_my_watershed() -> None:
    browse = fetch("https://monitormywatershed.org/browse/")
    match = re.search(r'<script id="sites-data"[^>]*>(.*?)</script>', browse, re.S)
    if match:
        sites = json.loads(match.group(1), strict=False)
        keep = [
            site
            for site in sites
            if site.get("code") in ("LL_SGTU_TEST2", "IRDQ Creek", "Oatka Creek 1")
        ]
        save(
            "mmw_sites.html",
            "<html><body>\n<script id=\"sites-data\" type=\"application/json\">\n"
            + json.dumps(keep, indent=1)
            + "\n</script>\n</body></html>\n",
        )

    ajax = "https://monitormywatershed.org/dataloader/ajax/"
    save(
        "mmw_metadata.json",
        fetch_post(
            ajax,
            {
                "request_data": json.dumps(
                    {
                        "method": "get_sampling_feature_metadata",
                        "sampling_feature_code": "LL_SGTU_TEST2",
                    }
                )
            },
        ),
    )

    def trim_series(result_id: int, name: str, want: int = 24) -> None:
        text = fetch_post(
            ajax,
            {
                "request_data": json.dumps(
                    {
                        "method": "get_result_timeseries",
                        "resultid": result_id,
                        "start_date": "2026-10-01",
                        "end_date": date.today().isoformat(),
                    }
                )
            },
        )
        raw = json.loads(text)
        if isinstance(raw, str):
            raw = json.loads(raw)
        keys = [
            key
            for key in sorted(raw["valuedatetime"], key=lambda k: int(k))
            if float(raw["datavalue"][key]) > -9998
        ][:want]
        payload = {
            field: {key: raw[field][key] for key in keys}
            for field in ("valueid", "datavalue", "valuedatetime", "valuedatetimeutcoffset")
        }
        save(name, json.dumps(payload))

    trim_series(8061, "mmw_depth.json")
    trim_series(4887, "mmw_temp.json")


def openmeteo() -> None:
    forecast = fetch_json(
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=43.1448&longitude=-77.512&hourly=precipitation,precipitation_probability"
        "&daily=precipitation_sum&past_days=2&forecast_days=1&timezone=auto&timeformat=unixtime"
    )
    forecast["hourly"] = {key: value[:6] for key, value in forecast["hourly"].items()}
    forecast["daily"] = {key: value[:3] for key, value in forecast["daily"].items()}
    save_json("openmeteo.json", forecast)

    archive = fetch_json(
        "https://archive-api.open-meteo.com/v1/archive"
        "?latitude=43.1448&longitude=-77.512&start_date=2024-01-01&end_date=2024-01-21"
        "&daily=precipitation_sum&timezone=auto&timeformat=unixtime"
    )
    archive["daily"]["time"] = archive["daily"]["time"][:21]
    archive["daily"]["precipitation_sum"] = archive["daily"]["precipitation_sum"][:21]
    save_json("openmeteo_archive.json", archive)


def cocorahs() -> None:
    text = fetch(
        "https://data.cocorahs.org/cocorahs/export/exportreports.aspx"
        "?ReportType=Daily&Format=CSV&State=NY&Station=NY-MR-90"
        "&StartDate=2026-11-10&EndDate=2026-11-20"
    )
    rows = list(csv.reader(io.StringIO(text)))
    save(
        "cocorahs_station.csv",
        "\n".join(",".join(row) for row in rows[:11]) + "\n",
    )


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    steps = (
        ("USGS site metadata", usgs_site),
        ("USGS instantaneous values", usgs_iv),
        ("USGS daily values", usgs_dv),
        ("USGS name search (OGC API)", usgs_name_search),
        ("NWS points/stations/forecasts/QPF", nws),
        ("Open-Meteo forecast + ERA5 archive", openmeteo),
        ("CoCoRaHS gauge history", cocorahs),
        ("Monitor My Watershed sensors", monitor_my_watershed),
    )
    failures = 0
    for label, step in steps:
        print(f"\n== {label}")
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - a flaky API shouldn't stop the rest
            failures += 1
            print(f"   FAILED: {exc}")
    print(f"\nDone ({failures} failure(s)). Run the tests, then review the diff.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
