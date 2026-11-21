# Contributing

StreamStudy is an **experimental sandbox** for public hydrology/weather data. Issues and pull
requests are welcome, but there is no support guarantee. See [AGENTS.md](AGENTS.md) for the
agent-facing guide (architecture, invariants, gotchas).

## Development setup

New to Python/Git? Start with the beginner-friendly [INSTALL.md](INSTALL.md).

- Python **3.10+** with Tk (`sudo apt install python3-tk` on Debian/Ubuntu).
- No dependencies to install — the app and tests use the standard library only.
- Optional: `python3 -m pip install -e .` to get a `streamstudy` command.

```bash
git clone git@github.com:llascari/RFD_LL_StreamStudy.git
cd RFD_LL_StreamStudy
python3 -m streamstudy --site 0423205010
```

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
xvfb-run -a python3 -m unittest discover -s tests -t . -v   # includes Tk tests
```

Tests are offline by design. Provider fixtures live in `tests/fixtures/` and are trimmed real
API responses; the model tests use synthetic series with known answers.

To refresh fixtures after an API change:

```bash
python3 scripts/capture_fixtures.py   # network required
xvfb-run -a python3 -m unittest discover -s tests -t . -v
```

Keep tests resilient to values that legitimately change between captures (assert structure,
units, ranges and ordering rather than one magic number).

## Style

- Standard library, `from __future__ import annotations`, 4-space indent, ~99 columns.
- Type hints on public functions and dataclasses; docstrings that explain *why*.
- Pure logic in `response.py` / `correlation.py` / `analysis.py`; I/O only in `providers/` and
  `http.py`; widgets only in `ui/`.
- No new runtime dependencies without a good reason.

## Data etiquette

- Keep requests small, cached and attributable: USGS/NWS/Open-Meteo/CoCoRaHS/OSM are public
  services.
- Send a descriptive `User-Agent` (already set in `http.py`).
- Do not bulk-download OSM tiles or scrape HTML when an API or bulk export exists.
- Never commit API keys, personal paths, or non-public data.

## AI-assisted contributions

This project was implemented by an LLM from human prompts. If you use a model/agent for a
substantial change, record it in [CREDITS.md](CREDITS.md) (area, model, human review) — that keeps
the attribution honest and useful.

## Pull request checklist

- [ ] `xvfb-run -a python3 -m unittest discover -s tests -t . -v` passes.
- [ ] New/changed parsing has a fixture-backed test.
- [ ] New UI has a headless smoke assertion (tab renders, key values present).
- [ ] Data-source failures still render the rest of the app.
- [ ] Experimental warning and attribution remain intact.
- [ ] README/CREDITS updated when behavior or provenance changes.
