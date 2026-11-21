# AGENTS.md

Guidance for AI coding agents (and humans) working on StreamStudy. Read this before changing
code; it encodes the project's constraints and the traps that have bitten us.

## What this is

An **experimental** desktop app for exploring USGS stream gages, NWS forecasts, Open-Meteo /
CoCoRaHS precipitation, and simple empirical rainfall→flow and regional correlation models.
Python 3.10+, Tkinter, **standard library only**.

The human owns requirements and decisions; the implementation is LLM-generated. If you add
substantial work, add a row to [CREDITS.md](CREDITS.md) with the model you used.

## Golden rules

1. **No third-party runtime dependencies.** `tkinter`, `urllib`, `json`, `sqlite`-free JSON
   settings. Charts are drawn on Tk canvases; map tiles are decoded by `tk.PhotoImage`.
   If you need numpy/scipy, implement the small piece in pure Python instead.
2. **Python 3.10 must work.** CI tests 3.10, 3.12, 3.13. Use `from __future__ import annotations`
   for modern typing, avoid 3.11+ APIs (`tomllib`, `StrEnum`, `datetime.UTC`, …).
   Note: plain `sum()` is not compensated before 3.12 — use `math.fsum` for statistics.
3. **Tk only on the main thread.** Workers return results through `app.run_async` → a
   `queue.Queue` drained by `root.after`. Never call widgets from a thread, never `.after()`
   from a worker.
4. **Tests never touch the network.** All provider tests use trimmed live responses in
   `tests/fixtures/` via `tests/support.StaticClient`. Model tests use synthetic series with
   known answers.
5. **Fail soft for data sources.** Each provider is independent; a failure becomes a row in
   `bundle.errors` / `analysis.errors`, never a crash or an empty window.
6. **Keep the experimental framing.** README warning, in-app header, About dialog and
   CREDITS.md must stay truthful: heuristics, not forecasts; not for safety decisions.

## Repository map

```
streamstudy/
  app.py            window, header/footer, background orchestration, settings save
  loader.py         BundleLoader: current conditions + multi-year history + regional analysis
  models.py         Site, Series, Sample, FlowEvent, ResponseFit, DataBundle, HistoryBundle
  providers/        usgs.py · nws.py · openmeteo.py · cocorahs.py · monitormywatershed.py
                    (pure parse_* functions + thin fetch)
  response.py       baseflow, storm events, response fit, scenario → predicted hydrograph
  correlation.py    lagged log-flow Pearson, flow↔flow and flow↔rain
  temperature_stats.py  hours above a threshold, clear days
  ranking.py        nearby-gage scoring and hub suggestion
  analysis.py       daily aggregation, unit conversion, stats, nice axis steps, pearson
  http.py           cached urllib client (text/bytes/json), retries on 5xx only
  settings.py       JSON settings: recent sites, windows, map radius
  credits.py        attribution text shown in About
  ui/               theme, charts, map_view, nine tab views, widgets
tests/              fixtures + unit/smoke tests (unittest, no pytest required)
scripts/            capture_fixtures.py (refresh fixtures from live APIs)
```

Data flow: `providers` → `models` → `loader` → `app` (worker thread + queue) → `ui` views.
`response.py`, `correlation.py` and `analysis.py` are pure and must stay I/O-free.

## Commands

```bash
python3 -m streamstudy                     # run (needs a display)
python3 -m streamstudy --site 0423205010 --days 14
python3 -m unittest discover -s tests -t . -v               # tests (GUI tests skip headless)
xvfb-run -a python3 -m unittest discover -s tests -t . -v   # full suite incl. Tk
python3 scripts/capture_fixtures.py        # refresh fixtures (network; then re-run tests)
make test / make gui-test / make run       # same, if you like make
```

## Common tasks

- **Add a USGS parameter** — add it to `providers/usgs.py:PARAMETERS` and
  `DEFAULT_PARAMETERS`, then surface it in a view (`bundle.usgs[code]`).
- **Add a precipitation source** — new module in `providers/`, a `parse_*` function that returns
  `{date: inches}` or a series, wire it into `loader.load_history` / `load_regional`, and add the
  source to `analysis.bundle_precip_sources`. Add a fixture + tests.
- **Tune the rainfall→flow model** — change `response.py` only; keep `detect_events`,
  `fit_response` and `predict` pure. Extend `tests/test_response.py` with a synthetic basin whose
  true response is known, and keep the 10–90 band honest.
- **Map** — `ui/map_view.py`: drag/wheel emit `on_view_change` → `app.request_map_view`, which
  reloads tiles and gages for the new bbox; a debounced `<Configure>` resize emits `on_resize`
  with `force=True`; the Filter box is client-side. Zoom is a free level (`settings.map_zoom`),
  not a radius preset: `app.zoom_map(±1)` steps it, `fit_map_to_sites` frames the visible gages,
  and `recenter_map` keeps the current zoom. Tiles are fetched in the worker (`fetch_tiles`) and
  decoded on the main thread. Clicking calls `app.load_site`.
- **Temperature** — `temperature_stats.py` integrates hours above a threshold from IV samples
  (gap capped at 2 h) and uses daily means for 30 d/1 y; `ui/temperature_view.py` also correlates
  daily water temperature with Open-Meteo air temperature and sunshine (linear, ±2 d).
- **Nearby hub ranking** — `ranking.py` scores candidates on fit r²/storm count, mean peer
  correlation, water-temperature availability and distance; the hub is the best site nearest the
  centroid of the top three. `loader.rank_sites` fetches the history; the Site finder shows it.
- **Settings reset** — `app.reset_settings()` (menu **Settings → Reset settings to defaults…**)
  restores `settings.DEFAULTS`, keeps only the current site/name, saves, and reloads.
- **Sensors** — `providers/monitormywatershed.py` parses the JSON block on `/browse/` and POSTs
  ODM2 requests to `/dataloader/ajax/` (`get_sampling_feature_metadata`,
  `get_result_timeseries`). Times are epoch milliseconds; `-9999` is missing; depth is relative.
  Up to two nearby stations are merged (nearest wins per variable).
- **Name search** — `UsgsProvider.search_by_name` uses the OGC `monitoring-locations` collection
  with a CQL2 text filter. Station names are upper-case and `LIKE` is case-sensitive, so the term
  is normalised; the state filter needs the numeric FIPS code, and `site_type` defaults to `Stream`.
- **Charts** — `ui/charts.py`: `ChartCanvas` (time lines/bars, log axis, hover) and
  `ScatterChart`. Keep them dependency-free; redraw on `<Configure>`.

## Data-source gotchas

- **USGS IV** is limited to 120 days per request; multi-year work uses **daily values**
  (`/nwis/dv/`, `statCd=00003`) whose timestamps are naive local midnights — take the date part.
- **NWS** requires a descriptive `User-Agent`. Observations retention is roughly a week;
  `precipitationLastHour` is often null at ASOS sites. QPF `validTime` is `start/ISO-duration`
  and values are mm (kg/m²).
- **CoCoRaHS** CSV totals are 24-hour reads at ~7 AM local, `T` = trace. Their JSON API
  (`api2.cocorahs.org`) is IPv6-only on some networks and times out; the CSV export is the
  supported bulk path. Treat coverage < 35 % as insufficient and fall back to ERA5.
- **ERA5** (Open-Meteo archive) lags a few days; daily unix stamps are local midnight and need
  `utc_offset_seconds` to recover the local date.
- **OSM tiles** — fetch only the visible view, cache in memory, never bulk-download, always show
  “© OpenStreetMap contributors”. Degrade to the schematic grid if tiles fail.
- **OGC name search** — CQL2 `LIKE` is case-sensitive against upper-case station names; use
  `state_code` (FIPS string), not the postal code. Empty/blank terms must short-circuit.
- **Monitor My Watershed** — the site list is a JSON block in the `/browse/` HTML (parse with
  `strict=False`); observations need a POST of `request_data` JSON; values use `-9999` for
  missing. Depth is relative to the sensor, not a datum; flag constant series as suspicious.
  The portal exposes two temperature results (degF and degC) — prefer degC.
- **Open-Meteo weather** — `sunshine_duration` is seconds (divide by 3600); daily stamps are local
  midnight with `utc_offset_seconds`. USGS daily water temperature is `00010`/`statCd=00003`;
  confidence/units differ from IV, so keep the two resolutions separate in stats.

## Testing conventions

- Add provider parsing tests against a fixture; then relax exact numbers where a fixture refresh
  would legitimately change them (structure, ranges, units, ordering are the real contract).
- Tk tests: create `tk.Tk()`, `withdraw()` unless the test needs geometry, and always destroy.
  For drawing assertions, deiconify, select the tab, `root.update()`, then inspect canvas items.
- Determinism: pass explicit dates into pure functions; never assert on “today”.

## Attribution protocol

`CREDITS.md` is a per-area log of which model did what. When you complete a meaningful change:

1. Add or extend a row in `CREDITS.md` (area + model + prompt/review role).
2. Keep the README “Human-prompted, LLM-implemented” section in sync.
3. Do not remove the experimental warning or the About dialog’s warning line.
