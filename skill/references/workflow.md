# GAMIT command sequence, parameters, and product inventory (basis for execution layer ②)

> Environment: `GG=~/gg`, `sh_gamit` version 10.76 (2022/02/13). All commands are csh scripts.
> Online sources: **SOPAC garner.ucsd.edu anonymous access available (preferred)**; CDDIS now requires Earthdata authentication; UNAVCO is not reachable from this machine.
> → In `process.defaults`, `set rinex_ftpsites = (sopac cddis)`, with sopac given priority.

## 0. Experiment directory structure (created automatically by sh_gamit)
```
<expt>/                 experiment root directory (give an absolute path with -dir)
  tables/               control files (copied from gg/templates then patched)
  brdc/                 broadcast ephemeris
  igs/                  IGS sp3 precise orbits + g/t files
  rinex/                RINEX observation files
  gfiles/  control/  figs/  gsoln/  glbf/
  <doy>[netext]/        per-day processing directory (e.g. 100 or 100G; with -yrext, 2023_100)
```

## 1. Standard end-to-end commands (single/multiple days)
```csh
setenv procdir <absolute path of expt>
# Single day:
sh_gamit -expt <4charexpt> -d <yr> <doy> -orbit igsf -copt x k ao -dopt c \
         -aprfile <frame>.apr -nopngs >&! sh_gamit.log
# Consecutive multiple days:  -s <yr> <d1> <d2>
```
Key options (from sh_gamit -help):
- `-expt`: 4-character experiment name (= the expt in the control files).
- `-d yr doy [doy...]` or `-s yr d1 d2` (start/stop day).
- `-orbit`: `igsf` (IGS final, default) / `igsr` (rapid) / `codf codm` (CODE, multi-GNSS), etc.
- `-gnss G|R|C|E|J|I` (default G=GPS).
- `-aprfile <name>.apr`: a priori coordinates (must be consistent with the sittbl./aprf frame).
- `-eops`: EOP series (default usno).
- `-noftp`: **offline mode** (this task uses online sources, so usually omitted).
- `-copt/-dopt/-aopt`: file types to compress/delete/archive.
- `-pres YES|ELEV` / `-nopngs`: residual sky-plot switches.
- `-sessinfo "<sint> <nepc> <stime>"`: sampling/epochs/start (default 30 2880 0 0).
- `-netext` / `-yrext`: day-directory suffix / year prefix.

## 2. Orbit retrieval (called internally by sh_gamit, can also be run standalone)
```csh
sh_get_orbits -orbit igsf -yr <yr> -doy <doy> -nofit   # download sp3 only
```
Orbit type → sp3 three-letter name: `igsf→igs, igsr→igr, codf→cof, code→cod, codm→com, codr→cor`.
Products: `igs/<prod><gpsw><d>.sp3` + the fitted g-file/t-file.

## 3. Key products and logs (parsed by name in diagnosis layer ③)
Inside the day directory `<expt>/<doy>/`:
- `GAMIT.status` — running flow log.
- `GAMIT.warning` — non-fatal warnings (antennas, data gaps, etc.).
- `GAMIT.fatal` — **fatal errors; if present the run has failed, and the diagnosis layer reads this first**.
- `sh_gamit_<doy>.summary` — **QC summary** (prefit/postfit nrms, number of sites, WL/NL fixing rates).
- `autcln.out.prefit` / `autcln.out.postfit` — data-cleaning reports (deleted points/SNR/data volume).
- `q<expt>a.<doy>` — SOLVE solution (q-file): coordinate adjustments, nrms, ambiguities.
- `o<expt>a.<doy>` — o-file (full solution, for post-processing).
- `h<expt>a.<doy>` — h-file (loosely constrained solution, for GLOBK, v2 format).
- `DPH.<site>` / sky png (figs/) — phase-residual diagnostics.

## 4. Diagnosis-layer reading order (recommended)
1. Exit code + tail of `sh_gamit.log` ("Normal stop" vs error).
2. `GAMIT.fatal` (if present, localize the root cause → consult errors.md).
3. `sh_gamit_<doy>.summary` to obtain QC metrics → consult qc.md to decide pass/fail.
4. Substandard but no fatal → inspect `autcln.out.postfit` (data volume/deleted points) and the q-file (nrms/ambiguities) to determine the cause.
