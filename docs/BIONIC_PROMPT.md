# Start prompt for a new Bionic project

Open this repository folder as a Bionic project, start a new chat, and paste the prompt below.
`AGENTS.md` is the standing contract; this prompt points the new agent at the portable context pack.

```text
You are continuing StreamStudy, an experimental Python 3.10+ / Tkinter desktop app for USGS stream
gages, NWS and Open-Meteo weather, CoCoRaHS rain, Monitor My Watershed sensors, rainfall-runoff
analysis, 10-day flow forecasts, temperature-driver correlations, and historical PDF reports.

Repository: <this folder>
Attribution: human-prompted; implementation by DeepSeek V4.1 Flash in LM Studio Bionic.

Before changing anything:
1. Read AGENTS.md (hard constraints and traps).
2. Read docs/BIONIC_CONTEXT.md (portable state snapshot).
3. Skim README.md, docs/REPORTS.md and docs/HOW_THIS_WAS_MADE.md.
4. Run the full test suite:
   xvfb-run -a python3 -m unittest discover -s tests -t . -v
   The working tree should be clean; do not revert unrelated changes.
5. Check `git log --oneline -10` and `git status --short` to see the actual current state.

Hard rules: standard library only at runtime; Python 3.10 compatibility; Tk only on the main
thread; tests never touch the network; fail soft for providers; keep the experimental warning and
attribution; update CREDITS.md and docs for meaningful work.

My current task is:
<describe the change here>

When done: run the tests, inspect any rendered UI/PDF, update the docs and build story, commit with
a clear message, and push to main only if I ask you to.
```

## Why this exists

Bionic stores project registration, session databases and chat history under the local LM Studio
application data directory. `git clone` carries the code and the docs but not that local state.
This context pack is the portable substitute: `AGENTS.md` + `BIONIC_CONTEXT.md` +
`BIONIC_PROMPT.md` + the repository itself.

If you want to copy local Bionic state as well, copy the whole project folder from the old
machine's LM Studio application data **only when you understand that it contains chat history and
local paths**; it is not needed for a clean continuation and should not be committed.
