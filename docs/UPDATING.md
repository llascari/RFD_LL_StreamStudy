# Updating, reverting, and making your own version

StreamStudy is a moving target — this is an experimental project. This page covers the three
things people actually need: **get a newer version**, **go back to an older one**, and **fork it
into your own variation**.

Your settings are stored **outside** the project folder, so updating, reverting or copying the
project never wipes your recent sites, thresholds or saved metrics (unless the settings format
changes; then use **Settings → Reset settings to defaults…**).

---

## 1. Check for updates (in the app)

- StreamStudy checks upstream **once after launch**. If a newer version exists, a blue
  **“Update available (commit …)”** label appears in the footer and the status bar says so.
- Click that label, or use **Help → Check for updates…**, to see the details and copyable update
  commands.
- The dialog tells you whether you are running a **git clone** (update with `git pull`) or a
  **downloaded ZIP** (download a new ZIP and replace the folder), and has buttons to copy the
  instructions or open the repository/download page.
- The check is read-only. Offline, or if GitHub rate-limits, it silently does nothing (manual
  checks show a warning).

How it decides:

| Install type | Compared against |
| --- | --- |
| `git clone` | your `HEAD` commit vs the latest commit on `main` |
| ZIP / copied folder | the local `VERSION` file vs `VERSION` on `main` |

The check goes to `github.com/llascari/RFD_LL_StreamStudy` (public, no login). If you fork the
project, change `REPO` in `streamstudy/updates.py` so your copy checks your fork instead.

---

## 2. Update

### If you cloned with Git

```bash
cd ~/git/RFD_LL_StreamStudy      # wherever you cloned it
git pull
```

Close and restart the app. If git refuses because you changed files locally:

```bash
git status          # see what you changed
git stash           # or commit your changes
git pull
git stash pop       # optional: re-apply your changes
```

### If you downloaded a ZIP

1. Download the latest ZIP:
   <https://github.com/llascari/RFD_LL_StreamStudy/archive/refs/heads/main.zip>
2. Extract it.
3. Replace the old project folder with the new one (or point your shortcut at it).
4. Restart the app.

Settings are kept; they live in the per-user config folder (see below).

---

## 3. Revert to a previous version

Every version is a commit on `main`. The [build log](HOW_THIS_WAS_MADE.md) lists the milestone
commits, and the [commits page](https://github.com/llascari/RFD_LL_StreamStudy/commits/main) has
the full list.

### Git: try an older commit

```bash
cd ~/git/RFD_LL_StreamStudy
git log --oneline -20          # find the commit you want
git checkout <commit-sha>      # e.g. 4ff96fb — detached HEAD is fine for trying it
```

Restart the app. This does not delete your work; use `git switch main` (or `git checkout main`)
to return to the latest version.

To keep the old version while still tracking new ones:

```bash
git switch -c rollback <commit-sha>
```

### ZIP: download a specific commit

GitHub archives any commit:

```
https://github.com/llascari/RFD_LL_StreamStudy/archive/<commit-sha>.zip
```

Extract it and run that folder. The in-app update checker will keep telling you a newer version
exists — that is expected when you intentionally run an old one.

### If a revert looks wrong

Settings are shared between versions. If the older version behaves oddly, reset:
**Settings → Reset settings to defaults…** (keeps the current gage loaded).

---

## 4. Make your own variation

You can fork the app, rename it, change the branding, or adapt it to another region or network.

### Fork on GitHub (recommended)

1. Click **Fork** on <https://github.com/llascari/RFD_LL_StreamStudy>.
2. Clone **your** fork:
   ```bash
   git clone https://github.com/YOUR-USER/RFD_LL_StreamStudy.git
   cd RFD_LL_StreamStudy
   git remote add upstream https://github.com/llascari/RFD_LL_StreamStudy.git
   ```
3. Keep up with upstream when you want:
   ```bash
   git fetch upstream
   git merge upstream/main
   ```
4. Make it yours:
   - `streamstudy/app.py` → `APP_NAME`, the header labels, the default site
   - `pyproject.toml` → project name/description
   - `README.md`, `INSTALL.md`, `CREDITS.md` → your naming and credits
   - `streamstudy/updates.py` → `REPO` constant (point the checker at your fork)
   - bump `VERSION` (and `streamstudy/__init__.py` / `pyproject.toml`) when you publish changes
5. Run the tests and the app:
   ```bash
   xvfb-run -a python3 -m unittest discover -s tests -t . -v
   python3 -m streamstudy
   ```

Please keep the **MIT license**, the **experimental / not-for-decisions warning**, and the data
attribution (USGS, NWS, Open-Meteo, CoCoRaHS, Monitor My Watershed, OpenStreetMap). If you publish
a fork, say clearly which parts you changed.

### No Git needed

Copy the extracted folder, edit the files, and run it. To share, zip it up. Keep `VERSION` in
sync with what you changed so the update checker behaves sensibly (or change `REPO` to your own
repo once you publish).

### Run several variations side by side

Settings are per-user, so different copies share them by default. Give each copy its own file:

```bash
STREAMSTUDY_SETTINGS=~/my-variant.json python3 -m streamstudy
```

On Windows (PowerShell):

```powershell
$env:STREAMSTUDY_SETTINGS="$HOME\my-variant.json"; python -m streamstudy
```

### Where settings live

| Platform | File |
| --- | --- |
| Windows | `%APPDATA%\streamstudy\settings.json` |
| macOS | `~/Library/Application Support/streamstudy/settings.json` |
| Linux | `~/.config/streamstudy/settings.json` |

---

## Troubleshooting the update check

| Symptom | Explanation / fix |
| --- | --- |
| “Update available” but `git pull` says up to date | You may be on another branch or a detached commit. `git switch main && git pull`. |
| ZIP copy keeps showing an update | Its `VERSION` is older than the repo’s. Download the newer ZIP, or edit `VERSION` if you intentionally maintain a fork. |
| Check silently does nothing on launch | Offline, blocked by a firewall/proxy, or GitHub rate-limited. Try **Help → Check for updates…** later. |
| The update dialog’s path is wrong | You moved the app since it was installed; the `cd` shown is the folder Python is running from. |
| Reverted version crashes | Python version too old/new for that commit, or settings from a newer version. Reset settings, or check the commit’s README. |

---

## Why this matters

This app was built by prompting; it changes quickly. Keeping a visible update path, a clear
revert path and an easy fork path is part of treating it as a **playground** rather than a
product. See [HOW_THIS_WAS_MADE.md](HOW_THIS_WAS_MADE.md) for the timeline and
[CREDITS.md](../CREDITS.md) for who built what.
