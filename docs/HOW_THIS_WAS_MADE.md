# How this was made — a prompt-driven build log

StreamStudy was built almost entirely by **prompting an LLM**. A human supplied the idea,
requirements, reviews and corrections; the code, tests, documentation and screenshots were written
by **DeepSeek V4.1 Flash** running in **[LM Studio Bionic](https://lmstudio.ai/)**.

This page is the honest story of that loop — roughly one row per round of prompts — so others can
see the shape of a project like this and try it themselves. It is not a tutorial, and it is not
polished marketing: the dead ends are included.

---

## The short version

1. **Start with a real domain and a real example** (a USGS gage URL), not an abstract "build an app".
2. **Verify every data source live** before writing UI. APIs and field names are where projects die.
3. **Build vertical slices**: one screen + real data + tests + screenshot, then the next screen.
4. **Keep logic pure** (models, fits, statistics) and put I/O at the edges.
5. **Record real API responses as fixtures** so 130 tests run offline in under four seconds.
6. **Look at screenshots every round.** Most layout bugs are invisible in code.
7. **Say what is experimental** and **credit the implementation**, including the model.

---

## Timeline

| # | Prompt / instruction (paraphrased) | What was built | Commit |
| --- | --- | --- | --- |
| 1 | “Create a Python GUI project and push it to a new private GitHub repo.” | First prototype: **FocusDeck**, a Tkinter focus timer with tests and CI. | `2f633da`, `e58728a` |
| 2 | “This repo is **RFD_LL_StreamStudy**. Build an app to query weather, USGS stream gages and web-scrapable precipitation for streams/creeks — here is an example gage.” | Full pivot: USGS/NWS/Open-Meteo/CoCoRaHS providers, charts, tests, screenshots, CI. | `ddfff17` |
| 3 | “There should be APIs for all those things.” | Audited each network; kept the API paths, added the **NWS QPF** endpoint, documented CoCoRaHS's JSON API vs its official CSV export, and made every source fail independently. | folded into `4ff96fb` |
| 4 | “A key feature: pull historical precipitation and map it to stream flows — first-order predicted level and timing from forecast rain.” | `response.py`: baseflow, storm events, response fit, lag/recession, forecast scenario with a 10–90 % band; **Rainfall → Flow** tab. Live example: 93 storms, 161 cfs/in. | `4ff96fb` |
| 5 | “Add a map overlay with clickable gages, and cross-correlation between streams and multiple precipitation sources.” | OpenStreetMap tiles drawn on a Tk canvas (no dependencies), clickable markers, lagged log-flow Pearson matrix, rain correlations. | `a3a3de8`, `8df3011` |
| 6 | “Make it public and note that this is experimental — something to play with.” | Public repo, README warning banner, in-app “experimental”, About dialog. | `725b8f8` |
| 7 | “Add attribution: human-prompted, fully implemented by the particular LLM (DeepSeek V4.1 Flash).” + “mention Bionic/LM Studio too.” | `CREDITS.md`, About dialog, README section, repo description. | `e365795` |
| 8 | “If you want to build an AGENTS.md or other nuggets so others can play with it, great.” | `AGENTS.md`, `CONTRIBUTING.md`, `Makefile`, and `scripts/capture_fixtures.py` for refreshing fixtures. | `e365795` |
| 9 | “Before finishing the sensors work, expand getting started for all major platforms — copyable instructions for Python, Git, etc.” + “push the docs early.” | `INSTALL.md` with Windows/macOS/Linux setup, ZIP-without-Git path, verification commands, troubleshooting; platform table in the README. | `c70b01c` |
| 10 | “Add Monitor My Watershed as an input; it has temperature and relative gage height, and can be mixed with USGS.” | ODM2 portal provider (`/browse/` site JSON + `/dataloader/ajax/`), **Sensors** tab, merging up to two stations, stuck-sensor flag. | `8423b03` |
| 11 | “The map should be navigable (scroll/drag), auto-resize.” + “Search by name too.” | Pan/zoom, debounced resize reload, live name filter, USGS OGC name search; labelled site picker. | `e365795`, `a805eca` |
| 12 | “A whole Temperature tab (water, air, sunshine correlation); duration above a settable temperature for 1 d/1 w/1 m/1 y; store more metrics; find a high-value nearby gage; reset settings.” | **Temperature** tab, `temperature_stats.py`, prediction percentages (% of baseflow / peak, 24 h decay % of storm flow) **stored per site in `settings.flow_metrics`** when **Remember** is ticked, `ranking.py` hub suggestion, **Settings → Reset**. | `af146b3` |
| 13 | “Update the screenshots/docs; they look stale.” | Regenerated every image from the running app, fixed the view list and quick start, moved the Site finder status to its own row. | `23826b6` |
| 14 | “Map scrolling/dragging and auto-recentering seem tied to the radius pulldown.” | Removed the radius presets: free zoom level, `−/+`, **Fit gages**, and Recenter that keeps your zoom; persists `map_zoom`. | `3f6d2f8` |
| 15 | “Map navigation seems broken — it snaps back. Is that load lag? Maybe keep a larger map available for panning.” | Panning moves the view immediately (optimistic), tiles are cached by zoom and prefetched 35 % beyond the viewport, and a failed/slow refresh no longer yanks the map back. Wheel zoom applies when the new tiles arrive instead of reverting. | `4f2ca9f` |
| 16 | “Have the app check the repo for updates and tell the user; show how to update — and also how to revert or create their own variation.” | `updates.py` compares the git commit (or `VERSION` for ZIP copies) with GitHub; a footer banner and **Help → Check for updates…** dialog show copyable commands; `docs/UPDATING.md` covers update, revert and fork workflows. | `c47cef5` |

The first two commits are a different app. That is fine: the prompt changed the domain, and the
right move was to pivot rather than bolt features onto the wrong program.

---

## What worked

- **A concrete example drives everything.** Starting from the Irondequoit Creek gage URL meant we
  always had real discharge, real storms and a real nearby rain gauge to test against.
- **Verify first, code second.** Every endpoint was checked with `curl` before it became a provider.
  That is how we learned about USGS's 120-day IV limit, NWS's `User-Agent` requirement, CoCoRaHS's
  7 AM observation windows and Open-Meteo's local-midnight unix stamps.
- **Fixtures + pure functions.** Parsing is tested against trimmed, recorded responses; the model
  is tested on synthetic storms whose answer is known (150 cfs/in, 24 h lag, 1.5-day half-life).
  No network in tests, so the suite stays fast and deterministic.
- **Screenshots as a review loop.** The header clipping, the squeezed prediction chart, the clipped
  heatmap labels and the cut-off temperature stats were all found by looking at rendered images.
- **Failure as a feature.** Each source is a `try/except` that appends to `errors`; the window still
  renders. CoCoRaHS timeouts and 503s from USGS became warnings, not crashes.
- **Write the caveats down.** “Depth is relative”, “heuristic, not a forecast”, “provisional data”
  are in the README, the UI and the About box.

## What broke (and what we changed)

| Symptom | Cause | Fix |
| --- | --- | --- |
| Flat series had `r = -5.8e-15` on Python 3.10 | uncompensated `sum()` | `math.fsum` + a degeneracy threshold (`8df3011`) |
| Slow loads when CoCoRaHS was slow | retrying timeouts | no retry on timeouts; ERA5 fallback |
| Depth sensor “looked broken” | real sensor stuck at a constant | flag constant series as suspicious instead of hiding them |
| Prediction chart disappeared | canvas under its minimum height after layout changes | gave the chart a stable height and fixed the grid weights |
| Map “tied to the radius dropdown” | zoom was derived from a preset radius | free zoom level, Fit gages, Recenter preserving zoom |
| Map “snapped back” after dragging | the canvas waited for the network, then redrew the old centre | optimistic pan, same-zoom tile cache, 35 % prefetch margin |
| Fixture refresh broke tests | assertions pinned to one recorded value | assert structure/ranges/ordering instead of magic numbers |

## A prompt recipe you can copy

If you want to try this:

1. **Give one real object and one real URL**: “Build a desktop app around *this* gage/route/account.
   Here is the page I use.”
2. **Ask for an API audit**: “Find the official APIs for every source; verify field names; tell me
   what is unavailable before writing UI.”
3. **Ask for one slice at a time**: “Add the overview tab first, with tests and a screenshot.”
4. **Ask for a model with a synthetic test**: “Implement this heuristic, and prove it recovers a
   known answer on synthetic data.”
5. **Demand honest failure**: “If one source is down, show a warning and render the rest.”
6. **Ask for docs and screenshots every few rounds**: “Regenerate the screenshots and check the
   README still matches the app.”
7. **Finish with provenance**: “State that a human prompted it and which model implemented it.”

## By the numbers

- **9 tabs**: Overview, Hydrograph, Sensors, Temperature, Precipitation, Rainfall → Flow,
  Map & Correlation, Forecast, Site finder
- **5 data networks + 1 tile service**: USGS NWIS (IV/DV/site/OGC), NWS `api.weather.gov`,
  Open-Meteo forecast/archive, CoCoRaHS CSV export, Monitor My Watershed ODM2, OpenStreetMap
- **130 tests**, offline, stdlib `unittest`; CI on Python 3.10/3.12/3.13 plus a headless Xvfb job
- **Zero third-party runtime dependencies** — Tk charts, `urllib`, `tk.PhotoImage` for map tiles
- **~9,800 lines** of Python including tests, **16 commits** at the time of writing

## Credit

- **Human:** idea, requirements, example gage, reviews, corrections, decision to publish.
- **Implementation:** DeepSeek V4.1 Flash in LM Studio Bionic.
- **Data:** USGS, NWS, Open-Meteo, CoCoRaHS, Monitor My Watershed / WikiWatershed / EnviroDIY,
  OpenStreetMap contributors.

See [CREDITS.md](../CREDITS.md) for the per-area log, and [INSTALL.md](../INSTALL.md) if you just
want to run it. This is an experimental toy: use it to explore, not to make safety decisions.
