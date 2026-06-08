# GAMIT control-file schemas (distilled from ~/gg/tables)

> This is the basis for the planning layer (①) to generate configurations and for the diagnosis layer (③) to localize "configuration-class" errors.
> All five files reside under the experiment directory's `tables/`; `sh_setup` copies the standard versions from `~/gg/tables`, and this agent patches them in place.

## 1. `process.defaults` — paths and global run options (csh variables)
Key variables (`set name = value`):
- Directories: `rawpth/rpth/bpth/ipth/gpth/tpth/glbpth/glfpth` (rinex, brdc, igs, gfiles, tables, globk, etc.).
- Sampling: `sint` (seconds, default 30), `nepc` (number of epochs, 2880 = 30s × 24h), `stime` ('0 0').
- station.info update: `stinf_unique="-u"`, `stinf_nosort="-nosort"`, `stinf_slthgt`.
- `use_rxc`: Y uses the RINEX header coordinates (when no lfile/apr a priori is available).
- `aprf`: default globk apr file (e.g. `igb14_comb.apr` / `igb20_*`).
- `dopts/copts/aopts`: delete/compress/archive options (e.g. `copts=(x k ao)`).
- `rinex_ftpsites`: download sources (`cddis sopac unavco`).
- **agent note**: when network access is restricted, empty out the ftp-related entries and switch to local rinex/orbits.

## 2. `sites.defaults` — site selection and station.info policy
Format: `site expt keyword ...` (site is 4/8 characters, expt is the experiment name).
- Sites with local RINEX are **included automatically** and need not be listed.
- Keywords: `ftprnx` (download from the rinex archive), `ftpraw`, `localrx`, `xstinfo` (exclude from automatic station.info update), `xsite[:yyyy_ddd-yyyy_ddd]` (exclude from processing / specified dates).
- Convention: `all_sites expt xstinfo` locks station.info against automatic rewriting.
- **agent note**: replace `expt` with the real experiment name; in offline mode remove `ftprnx`.

## 3. `station.info` — site metadata (receiver/antenna/antenna height)
- Huge (the MIT version is ~10 MB, a global library); only the entries for the relevant sites are needed for processing.
- Fields: site, start/stop time, receiver model/serial number/firmware, antenna model/serial number, antenna height (and ARP offset), antenna height measurement method.
- **Most frequent error source**: missing site entry / antenna model not matching the antmod table / incorrect antenna height → MODEL/AUTCLN failure.
- **agent strategy**: use `mstinf`/`sh_upd_stnfo` to generate a minimal station.info from the RINEX headers; the antenna model must be findable in `tables/antmod.dat`/the IGS antenna table.

## 4. `sestbl.` — session/analysis options (`Key = Value ; comment`)
Decision-tree-style key items:
- `Choice of Experiment`: **BASELINE** (regional / fixed orbits, recommended default) / RELAX. (estimate orbits simultaneously) / ORBIT.
- `Type of Analysis`: **1-ITER** (includes postfit autcln, standard) / 0-ITER / PREFIT.
- `Choice of Observable`: **LC_AUTCLN** (standard dual-frequency) / L1_ONLY / LC_HELP, etc.
- `Station Error = ELEVATION 10 5`: observation weighting (mm, ppm).
- `Ionospheric Constraints = 0.0 mm + 8.00 ppm`.
- `Ambiguity resolution WL/NL`: ambiguity fixing parameters (relax for long baselines).
- Troposphere: `Zenith Delay Estimation=Y`, `Interval zen=2`, `Zenith Constraints/Variation`, `Atmospheric gradients=Y`, `Number gradients`.
- Model family (affects accuracy/version consistency): `Radiation Model for ARC` (ECOMC/ECOM1/ECOM2), `DMap/WMap` (GMF/VMF1), `Tides applied` (bit-coded, ITRF2014→31, ITRF2020→79), `Earth Rotation` (27/83), `Etide model`, `Antenna Model=AZEL`, `SV antenna model`.
- `Update T/L files`, `Update tolerance=.3`, `Decimation Factor`, `Elevation Cutoff`.
- **agent note**: the satellite-constraint block is coupled with the radiation model (toggle the leading whitespace of the ECOMC vs ECOM1 line); reference-frame consistency (the tides/earth-rotation bit codes must match the chosen ITRF/apr).

## 5. `sittbl.` — per-site coordinate constraints (choose IGb20/IGS20/IGb14… to match the apr frame)
Format: `SITE  FIX  --COORD.CONSTR.--` (N/E/U three directions, meters).
- `ALL  NNN  100. 100. 100.`: default loose constraint for regional sites.
- Core frame sites: `AREQ NNN 0.050 0.050 0.050` (tight constraint, defines the reference frame).
- The three characters in the FIX column: per direction N (estimated) / can be fixed.
- **agent note**: the `sittbl.` frame version must be consistent with `process.defaults`'s `aprf` and apr file (IGb20↔igb20_*.apr); always keep at least several tightly constrained global core sites in a run as a benchmark.

---
## Configuration-consistency "hard constraints" (diagnosis-layer checks)
1. Reference-frame triad consistency: `aprf` (apr file) ↔ `sittbl.` version ↔ `sestbl.` tides/earth-rotation bit codes.
2. station.info covers all sites to be processed and every antenna model is present in the antmod table.
3. `sint/nepc` match the actual RINEX sampling/duration.
4. Offline mode: the ftp sources in `process.defaults` and the ftprnx keyword in `sites.defaults` are zeroed out.
