# Installing StreamStudy

StreamStudy is a desktop app for exploring stream gages and rainfall. It runs entirely on your own
computer and talks to public USGS / NWS / Open-Meteo / CoCoRaHS / OpenStreetMap services.

This guide assumes **no programming experience**. Everything is copy-and-paste. If a step fails,
see [Troubleshooting](#troubleshooting).

**What you need**

- A computer running Windows 10/11, macOS 12+, or a common Linux desktop
- Python **3.10 or newer, with Tk** (the graphical toolkit; included in the official Windows and
  macOS installers)
- The project folder (download a ZIP or use Git)
- An internet connection (the app streams live data and map tiles)

You do **not** need Git, a code editor, an account, or an API key.

---

## 1. Get the project folder

### Option A — Download a ZIP (no Git, easiest)

1. Open <https://github.com/llascari/RFD_LL_StreamStudy> in your browser.
2. Click the green **Code** button → **Download ZIP**.
3. **Extract** it:
   - Windows: right-click the ZIP → **Extract All…** → Extract.
   - macOS: double-click the ZIP.
   - Linux: right-click → **Extract Here** (or `unzip RFD_LL_StreamStudy-main.zip`).
4. Move the extracted folder somewhere permanent, e.g. **Documents**, and open it. You should see
   `README.md`, `streamstudy`, `tests`, and this file. That folder is the one you will run from.

### Option B — Use Git

Install Git first (see the platform section), then:

```bash
git clone https://github.com/llascari/RFD_LL_StreamStudy.git
cd RFD_LL_StreamStudy
```

---

## 2. Install Python

### Windows

1. Go to <https://www.python.org/downloads/windows/> and download the latest **Python 3.12**
   (or newer) **64-bit installer**.
2. Run it and **tick “Add python.exe to PATH”** at the bottom of the first screen. This is the
   single most important checkbox.
3. Click **Install Now**, then **Close**.

Open PowerShell (Start menu → type `PowerShell` → Enter) and check:

```powershell
python --version
python -c "import tkinter; print('Tk', tkinter.TkVersion)"
```

You should see something like `Python 3.12.x` and `Tk 8.6`. If `python` opens the Microsoft
Store, install Python from python.org instead, or use the `py` launcher in every command below
(`py -3 -m streamstudy`).

**Git (optional, only for Option B):** download from <https://git-scm.com/download/win> and accept
the defaults. Then check with `git --version`.

### macOS

1. Open **Terminal** (press `Cmd+Space`, type `Terminal`, press Enter).
2. Download the **macOS 64-bit universal2 installer** from
   <https://www.python.org/downloads/macos/> and run it. It includes Tk.
3. If macOS blocks the installer (“unidentified developer”), open **System Settings → Privacy &
   Security** and click **Open Anyway**.
4. Check:

```bash
python3 --version
python3 -c "import tkinter; print('Tk', tkinter.TkVersion)"
```

If you prefer Homebrew: `brew install python-tk@3.12` (match the version you have). The python.org
installer is the least surprising option.

**Git (optional):** `xcode-select --install` installs Apple’s command line tools, including Git.
Check with `git --version`.

### Linux

Open a terminal (`Ctrl+Alt+T` on most desktops) and run the command for your distribution.

**Ubuntu / Debian / Linux Mint / Pop!_OS**

```bash
sudo apt update
sudo apt install -y python3 python3-tk git
```

**Fedora / RHEL / Rocky**

```bash
sudo dnf install -y python3 python3-tkinter git
```

**Arch / Manjaro**

```bash
sudo pacman -S --needed python tk git
```

Check:

```bash
python3 --version
python3 -c "import tkinter; print('Tk', tkinter.TkVersion)"
```

If you do not have administrator rights, skip the system packages and use your distribution’s
software center to install “Python 3” and “python3-tk”, or ask an administrator.

---

## 3. Run the app

Open a terminal **in the project folder** (the one containing `README.md`).

- **Windows (PowerShell):**

  ```powershell
  cd "$HOME\Documents\RFD_LL_StreamStudy-main"
  python -m streamstudy
  ```

- **macOS / Linux:**

  ```bash
  cd ~/Documents/RFD_LL_StreamStudy-main
  python3 -m streamstudy
  ```

If you cloned with Git, use the folder name you created (`RFD_LL_StreamStudy`). If you are unsure
where the folder is, drag it onto the terminal window after typing `cd ` (with a space).

The window opens on the example gage **Irondequoit Creek above Blossom Rd near Rochester, NY**
(USGS `0423205010`). It loads current conditions, history, rainfall, sensors, map and forecast in
the background.

Try another gage:

```bash
python3 -m streamstudy --site 0423205010 --days 30
```

Windows users: replace `python3` with `python` above.

### Optional: a `streamstudy` command

Inside the project folder:

```bash
python3 -m pip install -e .
streamstudy
```

(On Windows use `python -m pip install -e .`.) This is optional; the `-m streamstudy` form always
works.

---

## 4. First-run tips

- **Be patient on first load.** It queries five public services; a slow network can take a few
  seconds. The status bar shows progress, and each source may be retried.
- **Warnings are normal.** If one service is down, the others still render and the warning is
  listed on the Overview tab. Click **Refresh** to retry.
- **The map needs internet** for OpenStreetMap tiles. If tiles are blocked, the gage positions are
  still shown on a plain grid and remain clickable.
- **No account or key is required.** All sources are public.
- **Making a PDF report:** **File → Generate PDF report…** builds a historical report for the
  loaded creek, or every creek within a radius. It needs no extra packages; a region report can
  take a few minutes. See [docs/REPORTS.md](docs/REPORTS.md).

---

## 5. Where settings live

Recent sites, the time window and map preferences are stored outside the project, so updating or
deleting the app does not lose them.

| Platform | File |
| --- | --- |
| Windows | `%APPDATA%\streamstudy\settings.json` |
| macOS | `~/Library/Application Support/streamstudy/settings.json` |
| Linux | `~/.config/streamstudy/settings.json` (respects `XDG_CONFIG_HOME`) |

Override with `--settings PATH` or the `STREAMSTUDY_SETTINGS` environment variable.

---

## 6. Updating, reverting and uninstalling

**Checking:** the app checks GitHub after launch. When a newer version exists, a blue
**“Update available”** label appears in the footer; click it or use **Help → Check for updates…**
to see copyable instructions.

**Updating**

- Git install: open the project folder and run `git pull`, then start the app again.
- ZIP install: download a new ZIP, extract it, and replace the old folder. Your settings are kept.

**Reverting:** `git log --oneline` then `git checkout <commit>`, or download
`…/archive/<commit>.zip` and run that folder.

**Your own variation:** fork the repo, change the name/branding and `REPO` in
`streamstudy/updates.py`.

All of this, with commands and troubleshooting, is in **[docs/UPDATING.md](docs/UPDATING.md)**.

**Uninstalling**

Delete the project folder. If you also want to remove your saved settings, delete the file listed
in section 5.

---

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `python` or `python3` is not recognised | Reinstall Python and tick **Add python.exe to PATH** (Windows). On macOS/Linux use `python3`. On Windows you can also use `py -3 -m streamstudy`. |
| `No module named tkinter` | Windows/macOS: use the python.org installer (it includes Tk). Linux: install `python3-tk` (Debian/Ubuntu), `python3-tkinter` (Fedora), or `tk` (Arch). |
| `No module named streamstudy` | You are in the wrong folder. `cd` into the folder that contains `README.md` and `streamstudy/`. |
| `SSL: CERTIFICATE_VERIFY_FAILED` (macOS) | Run `/Applications/Python 3.12/Install Certificates.command` once, then try again. |
| Window opens but data stays empty | Check your internet connection, corporate proxy or firewall. USGS/NWS/Open-Meteo/CoCoRaHS/OSM must be reachable. Click **Refresh**. |
| Map is blank or plain grey | Tile server blocked or offline; gages still work. Try again later or check the proxy. |
| Fonts look tiny on a 4K screen | Use your OS display scaling, or enlarge the window; Tk follows the system DPI on Windows/macOS. |
| Antivirus warns on first launch | The app only makes outbound HTTPS calls to the public data services listed in the README. |
| Corporate network blocks Python downloads | Use your organisation’s software centre, or try the ZIP on a personal machine. |

Still stuck? Open an issue at
<https://github.com/llascari/RFD_LL_StreamStudy/issues> and include your OS, Python version
(`python --version`), and the exact message.

---

## What the app does (so you know it is working)

- **Overview** — current gage height / discharge, today’s rain, source status
- **Hydrograph** — discharge and gage height charts
- **Sensors** — nearby Monitor My Watershed / EnviroDIY temperature and relative depth sensors
- **Temperature** — water vs air temperature, sunshine, and hours above a settable threshold
- **Temp Drivers** — air/sunshine correlations with water temperature for USGS and MMW sensors
- **Precipitation** — gauges vs models day by day
- **Rainfall → Flow** — historical storms vs flow response, plus a forecast scenario
- **Map & Correlation** — clickable gages, drag to pan, scroll to zoom, cross-correlations
- **Forecast** — NWS forecast text, QPF bars and precipitation probability
- **Flow forecast** — a 10-day predicted hydrograph, confidence band and similar past storms
- **Site finder** — find gages by state, distance or station name, and **Rank by data value**
  to suggest the best nearby hub
- **File → Generate PDF report…** — historical PDF for one gage or a radius of nearby gages

Use **Settings → Reset settings to defaults…** in the menu bar to restore every preference
(threshold, remembered metrics, recent sites) while keeping the current gage loaded.

This is an experimental tool for exploring data, **not** a flood-warning or engineering system.
