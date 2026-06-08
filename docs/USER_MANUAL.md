# GAMIT-Agent — User Manual

This manual covers installation, the web UI, the agent, the analysis tools, and a reproducible
worked example. It assumes you already have a working GAMIT/GLOBK installation.

## 1. Installation

### 1.1 Prerequisites
- **GAMIT/GLOBK** installed and runnable (`sh_gamit` on your `PATH` or under `~/gg`). Set
  `GG_DIR` if it is not at `~/gg`. GAMIT is not redistributed with this software.
- **Python 3.11+**.
- **csh/tcsh** (GAMIT scripts use it), plus `gfortran`+`make` if the `kf` modules
  (e.g. `svpos`) are not yet compiled — the agent will auto-build them on first need.
- An **OpenAI-compatible API key** (DeepSeek by default).

### 1.2 Install
```bash
git clone https://github.com/geumjin99/GAMIT-Agent.git
cd GAMIT-Agent
pip install -r requirements-app.txt
cp app/.env.example app/.env      # edit: DEEPSEEK_API_KEY=sk-...
```
You can also leave the key blank and enter it later in the UI (**Settings**); it is kept in
memory only and never written to disk.

### 1.3 Run
```bash
cd app && uvicorn backend.server:app --host 0.0.0.0 --port 8765
```
Open `http://localhost:8765`. For a remote host: `ssh -L 8765:localhost:8765 user@host` first.

Docker users: see `DOCKER.md` (GAMIT is mounted via a volume; the image does not contain it).

## 2. The web UI

The window has three panels.

- **Left — Project & analysis.**
  - *＋ New project (from bare RINEX)*: **Browse…** to pick a local RINEX folder (the green
    number is the RINEX count per folder), set an experiment name + year, then **Build project**.
    This runs `init_project` and loads the result on the map.
  - *Project*: point at an existing project directory and **Load stations**.
  - *Analysis*: enter a `doy` and click **QC verdict**, **Dropped sites**, or **Network geometry**.
    Day chips above are clickable and run the QC verdict for that day.
- **Center — Map.** Stations are colored by status: green = OK, red = antenna mismatch,
  orange = high multi-day std. Click a station for details and audit findings.
- **Right — Agent.** Type an instruction and **Run** (or press **Ctrl/⌘+Enter**). The agent's
  thoughts, tool calls, observations, and final report stream live.

Top bar: **Logs** opens the backend log viewer (auto-refresh available); **Settings** sets the
API key / base URL / model.

## 3. Talking to the agent
Give natural-language instructions, e.g.:
- "Run 2023 DOY 200 and give me a QC report."
- "Why did this day abort?"
- "Audit the antenna metadata for this network."
- "Set the autcln elevation cutoff to 10 degrees — which file and option?"

The agent follows a Plan → Execute → Diagnose/Self-correct → Report loop. On a fatal it reads
`GAMIT.fatal` first, matches the exact fingerprint in the knowledge base, changes one item at a
time, and retries up to three times before asking for human help.

## 4. Analysis tools (also available to the agent)
| Tool | What it does |
|---|---|
| `init_project` | Bare RINEX → full control files + `sh_rx2apr` *a priori* |
| `run_sh_gamit` | Run a single-day native GAMIT solution |
| `rinex_audit` | RINEX header vs. `station.info` — finds "legal but wrong" antennas |
| `multiday_std` | Per-station multi-day coordinate repeatability |
| `globk_frame` | GLOBK Helmert frame solution (htoglb → globk → glorg) |
| `diagnose_drops` | Stations silently removed by autcln (NoPrefit/NoPostfit) |
| `network_geometry` | Baselines, span, isolated stations |
| `qc_report` | One-stop verdict: pass / warn / fail + reasons |
| `gamit_help` | Search the GAMIT/GLOBK manuals (local BM25) |

## 5. Worked example
The repository ships sample data for a small from-scratch run in
[`sample_data/korea_doy200_2023.zip`](../sample_data/) (4 stations: DAEJ, INCH, SKMA, SONP;
year 2023, day-of-year 200). The archive contains `_INBOX_korea_200/` (bare RINEX, the Browse
target) and `orbits/` (IGS products for an offline run).

0. Unzip the sample data:
   ```bash
   unzip sample_data/korea_doy200_2023.zip -d sample_run
   # -> sample_run/_INBOX_korea_200/  (bare RINEX)
   # -> sample_run/orbits/            (igs22713.sp3, gigsg3.200, brdc2000.23n)
   ```
1. In **＋ New project**, Browse to the sample RINEX folder `sample_run/_INBOX_korea_200`,
   set experiment `ktst`, year `2023`, and **Build project**.
   - Expected: `ready ✓`, 4 stations, 3 missing-apr stations resolved by `sh_rx2apr`. The network
     appears on the map.
2. In the **Agent** panel: *"Run 2023 DOY 200 and give me a QC report."*
   - **Online (default):** `sh_gamit` downloads the IGS orbit and EOP products automatically.
   - **Offline:** copy `sample_run/orbits/igs22713.sp3` into the built project's `igs/` folder
     (and `gigsg3.200` into `gfiles/`), then run with the `-noftp` option; EOP tables come from
     your GAMIT installation. No internet is then needed.
   - Expected: a clean solution (nrms ≈ 0.2), no fatal; the map refreshes.
3. In **Analysis**: click the `200` day chip (QC verdict), then **Network geometry**.

The full 16-station reproduction (postfit nrms 0.186; GLOBK heights within 1–3 cm of the
multi-year reference) is reported in the accompanying *GPS Toolbox* article.

## 6. Logs, runs, and memory
- Backend logs are written to `app/logs/gamit-agent.log` (size-rotated) and viewable via the UI
  **Logs** button or `GET /api/logs`.
- Each agent run is saved to `app/runs/<timestamp>.json` (`GET /api/runs`, `/api/runs/{id}`).
- The agent bounds its own context (recent history + a hard character cap) so long loops do not
  grow memory without limit.

## 7. Troubleshooting
| Symptom | Action |
|---|---|
| "No API key configured" | Set the key in **Settings** or `app/.env`. |
| `init_project` not ready, unresolved a priori | A non-IGS station lacks usable nav for `sh_rx2apr`; provide a `.yyn`/brdc, or check the RINEX. |
| `svpos: Command not found` | The GAMIT `kf` module is uncompiled; the agent auto-builds it if `gfortran`/`make` are present. |
| A station is missing from the solution | Run **Dropped sites** (`diagnose_drops`) for the cause. |
| Unsure of a command option | Ask the agent, or call `gamit_help`. |

## 8. API reference (selected)
`GET /api/health`, `GET /api/browse?path=`, `POST /api/init_project`, `GET /api/project`,
`GET /api/stations`, `POST /api/run` (SSE), `GET /api/qc`, `GET /api/drops`, `GET /api/geometry`,
`GET /api/logs`, `GET /api/runs`, `GET|POST /api/config`.
