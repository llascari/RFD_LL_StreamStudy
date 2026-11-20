# StreamStudy

A desktop explorer for **USGS stream gages, National Weather Service forecasts, and precipitation
data** — built with Python and Tkinter, with no third-party dependencies.

Enter any USGS site number (the default is [0423205010, Irondequoit Creek above Blossom Rd near
Rochester, NY](https://waterdata.usgs.gov/monitoring-location/USGS-0423205010/)) and see the
hydrograph, nearby gauge rain reports, modelled rainfall and the official forecast side by side.

| Overview | Hydrograph |
| --- | --- |
| ![Overview tab](docs/overview.png) | ![Hydrograph tab](docs/hydrograph.png) |

| Precipitation | Forecast |
| --- | --- |
| ![Precipitation tab](docs/precipitation.png) | ![Forecast tab](docs/forecast.png) |

![Site finder](docs/sites.png)

## Features

- **Hydrograph** — discharge and gage height from USGS instantaneous values, with a log-scale
  option, peak/median statistics and a hover readout on every chart
- **Precipitation comparison** — daily bars and a table comparing up to four sources:
  on-site USGS precipitation (parameter `00045` where available), the nearest CoCoRaHS volunteer
  gauge, Open-Meteo's gridded model, and NWS ASOS observations
- **Forecast** — NWS daily periods with full discussion text, plus the NWS gridpoint
  **quantitative precipitation forecast** (6-hourly bars) and peak precipitation probability
- **Site finder** — search active USGS surface-water gages by state, or within ~50 km of the
  loaded site, then double-click to load one
- **Resilient by design** — every provider is independent: if one API is down the other three still
  render, and the failure is shown as a warning instead of a broken window
- **Fast and polite** — background threads (results marshalled through a queue, never touching Tk
  from a worker), in-memory HTTP cache, one retry on transient 5xx/network errors
- **Zero install** — standard library only: `tkinter`, `urllib`, `sqlite`-free JSON settings

## Data sources and APIs

Everything comes from documented, structured APIs — no HTML scraping:

| Network | Endpoint | Used for | Auth |
| --- | --- | --- | --- |
| **USGS NWIS** | `waterservices.usgs.gov/nwis/iv/` (JSON) | Discharge, gage height, water temperature, on-site precipitation (last ≤120 days) | none |
| **USGS NWIS** | `waterservices.usgs.gov/nwis/site/` (RDB) | Site metadata and gage search (`siteType=ST`, `parameterCd=00060`) | none |
| **USGS Water Data** | `api.waterdata.usgs.gov/ogcapi/v0/…` | The newer OGC API — verified working; the app uses NWIS IV for its broader parameter coverage | none |
| **NWS** | `api.weather.gov/points/…`, `/gridpoints/…`, `/stations/…/observations` | Nearest ASOS station observations, daily/hourly forecast, gridpoint QPF | none (User-Agent required) |
| **Open-Meteo** | `api.open-meteo.com/v1/forecast` | Hourly precipitation + probability, daily sums (past 60 days, 2-day forecast) | none |
| **CoCoRaHS** | `data.cocorahs.org/cocorahs/export/exportreports.aspx` | Volunteer 24-hour gauge reports, nearest-gauge search | none |

Notes:

- CoCoRaHS also publishes a JSON API at `api2.cocorahs.org`; it resolved IPv6-only and timed out
  from our test network, so the app uses the official bulk CSV export endpoint instead. Both are
  documented public interfaces, not screen-scraping.
- USGS values are **provisional** and may be revised. CoCoRaHS gauges report 24-hour totals at the
  observer's reading time (~7 AM local), so daily comparisons are approximate. Open-Meteo is a
  gridded model, not a gauge.

## Quick start

Requires Python **3.10+** with Tk support (on Debian/Ubuntu: `sudo apt install python3-tk`).

```bash
git clone git@github.com:llascari/RFD_LL_StreamStudy.git
cd RFD_LL_StreamStudy
python -m streamstudy
```

Command line options:

```bash
python -m streamstudy --site 0423205010 --days 14
python -m streamstudy --help
```

Editable install (adds a `streamstudy` command):

```bash
python -m pip install -e .
streamstudy --site 0423205010
```

Settings (recent sites, last site, window) live in a small JSON file:

| Platform | Path |
| --- | --- |
| Linux | `~/.config/streamstudy/settings.json` (respects `XDG_CONFIG_HOME`) |
| macOS | `~/Library/Application Support/streamstudy/settings.json` |
| Windows | `%APPDATA%\streamstudy\settings.json` |

Override with `--settings PATH` or `$STREAMSTUDY_SETTINGS`.

## How it works

```
provider API ──► parse_*() ──► models (Site, Series, ForecastPeriod…)
                                   │
                         BundleLoader.load(site, options)
                    (one try/except per source → errors list)
                                   │
                StreamStudyApp (worker thread → queue → Tk main thread)
                                   │
         HomeView · HydroView · PrecipView · ForecastView · SitesView
```

- **`providers/`** — one module per network. Parsing functions are pure and unit tested against
  recorded API responses (`tests/fixtures/`).
- **`loader.py`** — assembles a `DataBundle`; partial failures are collected in `bundle.errors`
  rather than aborting.
- **`analysis.py`** — daily aggregation, unit conversions, medians/trends, "nice" axis steps.
- **`ui/charts.py`** — a small canvas chart widget (lines, grouped bars, log axis, hover tooltip)
  so the app stays dependency-free.
- **`ui/theme.py`** — dark ttk theme; `ui/widgets.py` — stat cards and table helpers.

## Project layout

```
RFD_LL_StreamStudy/
├── streamstudy/
│   ├── __main__.py        # argparse entry point
│   ├── app.py             # window, header, background loading, settings
│   ├── loader.py          # per-source fetch orchestration
│   ├── models.py          # Site, Series, Sample, ForecastPeriod, DataBundle
│   ├── analysis.py        # aggregation and formatting helpers
│   ├── http.py            # cached, retrying urllib client
│   ├── settings.py        # JSON settings (recent sites, window)
│   ├── providers/         # usgs.py · nws.py · openmeteo.py · cocorahs.py
│   └── ui/                # theme, charts, widgets and the five views
├── tests/
│   ├── fixtures/          # trimmed real API responses
│   └── test_*.py          # 53 tests (providers, analysis, loader, Tk smoke)
├── docs/                  # screenshots
├── pyproject.toml
└── .github/workflows/ci.yml
```

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

Headless Linux (runs the Tk smoke tests too):

```bash
xvfb-run -a python -m unittest discover -s tests -t . -v
```

The GUI tests skip themselves automatically when no display is available, so the suite also runs
in plain CI containers. Fixtures were captured from the live APIs and trimmed, so the tests never
touch the network.

## Attribution

Data courtesy of the [USGS National Water Information System](https://waterservices.usgs.gov/),
the [National Weather Service](https://www.weather.gov/documentation/services-web-api),
[Open-Meteo](https://open-meteo.com/) (CC BY 4.0), and
[CoCoRaHS](https://www.cocorahs.org/) (CC BY 4.0).

## License

MIT — see [LICENSE](LICENSE).
