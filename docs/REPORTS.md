# Historical PDF reports

StreamStudy can turn the daily record for a creek — or every creek within a radius — into a
multi-page PDF. It is built for **looking back**, not for forecasting: temperatures, flows,
threshold duration, extreme days, and the storms that produced them.

> [!WARNING]
> This is an experimental screening report, not an engineering or safety product. Daily means hide
> short peaks, rating curves change, sensors fail, and the rainfall series is a point/grid estimate.
> Always check the authoritative USGS and agency records before using a number.

## Generate one

1. Load a USGS site in the app (site number, recent-sites list, map click or name search).
2. Choose **File → Generate PDF report…**.
3. Set:
   - **History window** — 24 h, 7 d, 30 d, 90 d, 1 y, 2 y, 5 y, 10 y, or custom `YYYY-MM-DD` dates.
   - **Nearby region** — tick it to add every active USGS discharge gage within the radius.
     Radius is 1–100 km; at most 12 sites are included (the loaded gage is always first).
   - **Include MMW sensors** — also look for a nearby Monitor My Watershed water-temperature
     sensor; on by default, useful for gages whose USGS record lacks `00010`.
   - **Temperature threshold** — the water-temperature duration threshold (default 20 °C); the
     same value is saved for the Temperature tab.
   - **PDF file** — the default is your home folder, named with the site and window.
4. Press **Generate**. The dialog shows the current site, a progress bar, elapsed time, and a
   warning if no new data has arrived for 20 seconds. **Cancel** stops between sites.
5. When it finishes, **Open report** launches your PDF viewer. Sites that failed after two retries
   are listed on the references page instead of aborting the whole job.

A single-gage report is normally 5 pages. A region report adds 3 pages per nearby creek plus a
region table on the cover.

## What is inside

| Page | Contents |
| --- | --- |
| Cover | Site name/number/coordinates, window, radius, threshold, precipitation source, a plain-language warning, summary cards, schematic locator map, region table |
| Flow | Mean/median/min/max, 10th–90th percentiles, daily hydrograph with rain bars, highest and lowest daily flows with dates and that day's rain |
| Temperature | Water (USGS `00010`, daily mean) and air (ERA5) series, threshold line, mean/min/max with dates, days and hours above the threshold, longest warm run, warmest/coldest water days, sunshine, and the fitted rainfall–runoff response with the largest storms |
| Temperature correlations | Air and sunshine vs water temperature at lags −5 to +5 days for **USGS and nearby Monitor My Watershed** sensors, in absolute and rise-over-normal (rolling-mean anomaly) forms; signed scatter plots with regression lines, best r/lag, paired days, confidence and the full lag table; plus a **sunlight sensitivity** table ranking the primary gage against its region peers by °C of water rise per sunshine-hour above normal |
| Region site | Compact flow page, a temperature/response page, and a temperature-correlation page (3 pages per creek) |
| References | USGS, CoCoRaHS, Open-Meteo/ERA5 and OSM links; methods; health warnings; how to reproduce |

The locator map is **schematic** (no basemap image). It preserves relative positions and labels
each USGS site number; the app's interactive OpenStreetMap tab is the place to explore geography.

## How the numbers are made

- **Flow** — USGS daily values, parameter `00060`, statistic `00003` (daily mean). Units are cfs.
- **Water temperature** — USGS daily values, parameter `00010`, statistic `00003`, °C. Many gages
  do not report it; the report says so instead of inventing a value.
- **Precipitation** — the same historical source as the app: CoCoRaHS volunteer gauge when it
  covers at least 35 % of the flow days, otherwise Open-Meteo ERA5. CoCoRaHS totals are 24 h reads
  around 7 AM local time; ERA5 is a gridded model.
- **Air temperature and sunshine** — Open-Meteo ERA5 daily mean/max/min and sunshine duration.
- **Threshold duration** — daily means above the threshold count as 24 h each. This is a screening
  statistic; short-window work in the Temperature tab integrates 15-minute samples instead.
- **Temperature correlations** — daily water temperature is paired with Open-Meteo daily air
  temperature and sunshine at lags from −5 to +5 days. Positive lag means water follows the driver.
  Pearson r and the best absolute lag are reported for each USGS/MMW water source. MMW sensors are
  recent-only; correlation is not causation.
- **Rise over normal** — the same fits are repeated after subtracting each series' centred 15-day
  rolling mean, isolating day-to-day departures from the seasonal norm. On long windows the
  absolute correlations mostly track the seasons; the anomaly rows track the weather.
- **Driver split** — water anomalies are also regressed on air and sunshine anomalies together
  (lag grid 0–5 days per driver). Each slope is then one driver's effect with the other held
  constant: sun °C per sunshine-hour and air °C per °C, each with a partial correlation (pr) and
  the joint R².
- **Sunlight sensitivity** — in region reports, every gage with water temperature is ranked by the
  held-constant sunshine slope (°C of water rise per sunshine-hour above its own normal, air
  constant), strongest first, so relative sunlight dependence across nearby streams can be
  compared directly.
- **Storm response** — storms are ≥ 0.10 in rain; baseflow is a smoothed 7-day rolling minimum;
  a rise is the peak above baseflow within four days. The fitted rate, lag percentiles and
  recession half-life describe the observed events; they are not calibrated hydrologic parameters.
- **Extremes** — the highest and lowest daily means in the window, with their dates and that day's
  rainfall. For a crest, use instantaneous USGS data, not this report.

## Long region reports

Each site needs a USGS daily-values request, an ERA5 archive request, and (when enabled) a
Monitor My Watershed site/sensor lookup. Ten years × twelve sites is a lot of public API traffic,
so the app:

- includes the loaded gage first, then nearby gages sorted by distance;
- makes **two retries** per site with a short delay;
- keeps going when a site fails and records the reason;
- shows a live **elapsed timer**, a rotating activity indicator and the **current stage**
  (USGS daily flow, CoCoRaHS/ERA5 precipitation, air temperature, fitting, retry, writing);
- warns after **20 s with no new data** (network stalls happen) and still allows **Cancel**;
- runs the whole job on a worker thread, so the window stays responsive.

Start with a single site and a shorter window to check the output, then widen the radius or window.
The USGS and Open-Meteo services are free and unauthenticated; please do not hammer them.

## Reproduce, customize, or revert

The report is deterministic for the same inputs and source data. To reproduce one, use the same
site, window, threshold and radius; the cover records the source and generation time.

To customize:

1. Fork the repository (or copy the folder).
2. Edit `streamstudy/report.py` for statistics and page layout, or `streamstudy/pdf.py` for the
   low-level writer. Both are standard-library-only.
3. Keep the experimental warning and attribution in the PDF.
4. Run `xvfb-run -a python3 -m unittest discover -s tests -t . -v` and render a sample with
   `pdftoppm -png` before shipping changes.

If a new version changes the layout, [docs/UPDATING.md](UPDATING.md) explains how to `git pull`,
revert to an earlier commit, or run your own variation. Settings live outside the checkout, so
updating does not erase them.

## Troubleshooting

| Symptom | What to try |
| --- | --- |
| “no daily flow values” for a nearby site | That gage has no `00060` daily record for the window. Increase the window or exclude it; the report continues without it. |
| Report seems to take forever | Check the elapsed/stall text. Cancel and retry with a smaller radius or a shorter window. |
| No water temperature | Normal at many gages. The report still includes air temperature, flow and the threshold note. |
| PDF opens but a page looks sparse | A short window or a site with missing temperature/flow; sources and notes explain what was unavailable. |
| Output path is not writable | Choose **Browse…** and save somewhere in your home folder. |

See also [README.md](../README.md#historical-pdf-reports) and
[docs/HOW_THIS_WAS_MADE.md](HOW_THIS_WAS_MADE.md).
