# Bionic context pack

This file is a **portable project brief** for an LLM agent (or human) opening StreamStudy on
another machine. Bionic's project registry and chat history live under `~/.lmstudio`, outside the
repository, so they do not travel with `git clone`. This pack plus [AGENTS.md](../AGENTS.md) is the
replacement: open the repo folder as a Bionic project, paste the prompt in
[BIONIC_PROMPT.md](BIONIC_PROMPT.md), and the new session has the context it needs.

> Snapshot: 2026-11-23, version 0.4.0 (after the rise-over-normal thermal work). The authoritative
> current state is `git log`, `README.md` and the test suite; update this file when the shape of
> the project changes.

## What StreamStudy is

An **experimental**, human-prompted / LLM-implemented Python + Tkinter desktop app for exploring
public hydrology and weather data. It is not a product, not a flood forecast, and not suitable for
safety, engineering, insurance or emergency decisions.

Current capabilities:

- USGS stream gages: current discharge/stage/water temperature, hydrographs, multi-year daily
  values, rainfall-runoff response fit, nearby-gage search and regional correlations.
- NWS forecast text, gridpoint QPF, and a 10-day flow forecast that convolves forecast rain with the
  empirical response shape (p10/p50/p90 band, confidence, similar past storms).
- Open-Meteo hourly/daily precipitation, air temperature, sunshine and cloud cover, plus ERA5
  history.
- CoCoRaHS volunteer gauge history and comparison.
- Monitor My Watershed / EnviroDIY sensors: water temperature, relative depth, conductance.
- Temperature tab: water vs air, sunshine, clear-day counts, time above a settable threshold.
- **Temp Drivers** tab: water-temperature correlation with air temperature and sunshine at lags
  −5..+5 days, for USGS and MMW water sources, with signed scatters and a lag table. Two bases:
  **absolute** values and **rise over normal** (each series minus its centred 15-day rolling
  mean — anomaly fits describe day-to-day drivers instead of the seasonal cycle; cards show the
  slope in °C per driver unit). **Compare nearby…** fetches USGS `00010` daily water temperature
  for the nearest gages and ranks streams by sunshine slope (°C of water rise per sunshine-hour
  above normal), strongest first.
- Navigable OpenStreetMap view with lagged cross-correlation between streams and rain.
- Historical PDF reports: single gage or radius region, up to 10 years, flow + temperature +
  extreme days + temperature correlations + schematic map + sources/limitations.
- Shared analysis window (1 d … 10 y or custom), flow metrics, settings reset, update checker,
  beginner-friendly install/update docs.

## Golden constraints

1. **Standard library only at runtime.** Tkinter, `urllib`, `json`, `pathlib`, hand-drawn charts,
   hand-written PDF writer. No numpy/scipy/pandas/requests.
2. **Python 3.10 must work.** CI runs 3.10/3.12/3.13 plus Xvfb.
3. **Tk only on the main thread.** Workers return through `app.run_async` / `queue.Queue`; do not
   touch Tk variables from a worker (this caused a real report-dialog hang).
4. **Tests never touch the network.** Use `tests/support.StaticClient` and fixtures.
5. **Fail soft.** One provider failing becomes an error row, not a crash.
6. **Keep the experimental framing and attribution.** README warning, in-app header, About dialog,
   `CREDITS.md`.
7. **Update the docs and `CREDITS.md` with meaningful changes.**

## Repository map

```
streamstudy/
  app.py            window, tabs, menus, worker queue, settings
  loader.py         DataBundle + HistoryBundle assembly, reports, regional analysis
  models.py         Site, Series, FlowEvent, ResponseFit, HistoryBundle, DataBundle…
  providers/        usgs · nws · openmeteo · cocorahs · monitormywatershed
  response.py       baseflow, storms, response fit, 48 h + 10-day prediction
  thermal.py        water vs air/sunshine correlations, lag curves, °F→°C
  correlation.py    lagged log-flow Pearson for regional streams/rain
  temperature_stats.py  threshold duration, clear days
  ranking.py        nearby-hub scoring
  report.py         historical statistics + PDF page composition
  pdf.py            stdlib PDF 1.4 writer
  analysis_window.py  shared presets/custom dates
  updates.py        git/VERSION update check
  ui/               11 tab views, charts, map_view, report_dialog, theme, widgets
tests/              offline unittest suite + fixtures
docs/               screenshots, how-it-was-made, reports, updating, this pack
```

Data flow: `providers` → `models` → `loader` → `app` (worker + queue) → `ui` views.
`response.py`, `correlation.py`, `thermal.py` and `analysis.py` are pure and I/O-free.

## Commands

```bash
python3 -m streamstudy
python3 -m unittest discover -s tests -t . -v
xvfb-run -a python3 -m unittest discover -s tests -t . -v   # includes Tk tests
python3 scripts/capture_fixtures.py                        # network; then re-test
make test / make gui-test / make run
```

## Data-source traps

- USGS IV is limited to 120 days; multi-year work uses daily values (`00003`).
- USGS water temperature is `00010`; not every gage has it.
- NWS needs a descriptive `User-Agent`; QPF values are mm.
- CoCoRaHS CSV is 24 h at ~7 AM; low coverage falls back to ERA5.
- ERA5 archive lags a few days; daily stamps need `utc_offset_seconds`.
- MMW depth is relative, not a datum; MMW sensors are recent-only; `-9999` is missing; prefer °C.
- OGC name search is case-sensitive against upper-case station names.
- OSM tiles: visible view only, cache, attribution.
- Analysis-window dates are local; long windows use daily means, short windows integrate IV with a
  2 h gap cap.
- Canvas text does **not** accept Text-widget options such as `spacing1` (this caused an empty chart
  tooltip).

## Recent work and current caveats

- The latest feature is the **rise-over-normal** (anomaly) basis and the cross-stream
  **sunlight comparison** in Temp Drivers — also on the PDF thermal page (anomaly rows in the
  correlation summary and a sunlight-sensitivity region table).
- Anomaly caveat: with a 15-day rolling normal, windows shorter than ~3 weeks leave little
  anomaly signal; MMW recent-only series are especially affected.
- PDF reports are 5 pages for one gage and 3 pages per additional region gage.
- Region report progress reports site + source stage, elapsed time, retries and stalls; cancel is
  checked between sites/retries.
- MMW report inclusion defaults on and can be disabled in the report dialog.
- `HistoryBundle` now carries `flow_daily`, `air_mean`, `air_max`, `air_min` and `sunshine`.
- Tests: run the suite rather than trusting a count written here.
- The short "recent past + predicted future" PDF variant is still a separate, unimplemented ask.

## Attribution

- **Human:** idea, requirements, reviews, corrections, publication decisions.
- **Implementation:** DeepSeek V4.1 Flash in LM Studio Bionic.
- Data: USGS, NWS, Open-Meteo, CoCoRaHS, Monitor My Watershed / WikiWatershed / EnviroDIY,
  OpenStreetMap contributors.

If you add substantial work, record the model in [CREDITS.md](../CREDITS.md) and append a row to
[HOW_THIS_WAS_MADE.md](HOW_THIS_WAS_MADE.md).
