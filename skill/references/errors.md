# GAMIT error → root cause → fix catalog (core of the diagnosis and self-correction layer ③)

> This is the core asset of the agent's novelty. The initial version is based on general experience + control-file consistency constraints, and is **continuously supplemented with real samples during the P2 live runs** (record the original GAMIT.fatal/warning text, the root cause, the configuration changed, and the result).
> Source of error messages: `report_stat` writes to `GAMIT.status / GAMIT.warning / GAMIT.fatal`. When diagnosing, grab the fatal first, then trace back to the status/warning context.
> **Every fix must obey the hard-stop criteria in SKILL.md**: change only one localizable configuration item at a time, record the "hypothesis → change → result", and retry at most 3 times.

## A. station.info / metadata class (most frequent)
| Symptom (keywords) | Root cause | Fix action |
|---|---|---|
| `no match in station.info` / a site is missing an entry | station.info does not contain that site or that time span | Use `mstinf -f rinex -o station.info` to add the entry from the RINEX header; or `sh_upd_stnfo`; confirm `sites.defaults` has not locked it with `xstinfo` |
| Anomalous antenna height/measurement method, systematic bias in the U direction | Incorrect antenna height (ARP/slant) in station.info | Cross-check the RINEX-header antenna height and measurement type; correct the HtCod field in station.info |
| `antenna ... not found` / phase-center warning | Antenna model not in `tables/antmod.dat` | Use the IGS standard antenna name; when no AZEL model is available, downgrade `sestbl.` to `Antenna Model = ELEV`; if necessary add `NONE` to get a run through temporarily |
| Receiver-model warning | The rcvr is not in `rcvant.dat`/`guess_rcvant.dat` | Map it to a known model or update the table |

## B. a priori coordinate / frame class
| Symptom | Root cause | Fix action |
|---|---|---|
| Huge prefit nrms (>1), ambiguities barely fixed | Poor a priori coordinates in apr/lfile (errors of a meter or more) | Recompute the a priori with `sh_rx2apr` from pseudoranges; or set `use_rxc=Y` in `process.defaults` to use the RINEX-header coordinates; update the lfile |
| Solution drift, frame inconsistency | aprf↔sittbl.↔sestbl. tides/earth-rotation bit codes do not match | Unify them per the "frame triad" in the final section of control-files.md (IGb20↔igb20_*.apr↔tides=79/erotation=83) |
| Missing core-site benchmark | sittbl. has no tightly constrained global sites | Keep several IGS core sites in the network and constrain them to 0.05 m |

## C. orbit / EOP class
| Symptom | Root cause | Fix action |
|---|---|---|
| No sp3 / g-file, sh_get_orbits fails | Online source unreachable or the product for that GPS week not yet released | Switch to `-orbit igsr` (rapid) or `codf`; confirm the GPS week/day; prefer sopac; avoid CDDIS if it requires authentication |
| `orbit misfit > ofit` | sp3-to-model fit exceeds the limit | Relax `-ofit`; check that the radiation model `Radiation Model for ARC` is consistent with the orbit |
| EOP download fails | Problem with the usno source | `-eops bull_b` or `-localeop` to use a local table |

## D. RINEX / data-volume class
| Symptom | Root cause | Fix action |
|---|---|---|
| `no data` / site does not enter the solution | RINEX missing, naming nonconforming, span too short | Check the rinex/ naming (ssssdddf.yyo); lower `-minspan`; use `-rx_doy_minus` to widen the search |
| autcln deletes too many points, observation count drops sharply | Poor data quality / multipath / cycle slips | Inspect autcln.out.postfit; relax the editing criteria in `autcln.cmd`; raise the `Elevation Cutoff` to exclude low-elevation-angle noise |
| Sampling/epochs mismatch | sint/nepc do not match the RINEX | Align with the actual sampling and duration in `process.defaults` or via `-sessinfo` |
| Too few satellites / no double differences | Insufficient common view, missing ephemeris | Confirm brdc and sp3 coverage; for mixed GNSS use multi-system products via `-gnss`/`-orbit` |

## E. general fallback
- Any `GAMIT.fatal`: take the last segment of the fatal text + the triggering module (MODEL/AUTCLN/SOLVE/ARC), map it to the tables above; if it cannot be classified, report the original text back to a human (trigger the hard stop).
- Two consecutive changes with no QC improvement → stop and produce a diagnostic report.

## F. benign-warning whitelist (the diagnosis layer **must not** raise errors/rerun based on these)
A live run (na01 2023 DOY100) confirmed that the following GAMIT.warning messages are normal and require no intervention:
| warning original text (keywords) | Meaning | Disposition |
|---|---|---|
| `MAKEX/lib/lread: Multiple entries for site X but no eq_rename file; last entry used` | station.info has multiple time-span entries for that site; the last one is used | Ignore (normal when the data span falls within the last entry) |
| `MODEL/setup: Ocean tidal loading model read but not used` | sestbl has not enabled ocean tidal loading (Use otl.grid=N) | Ignore (modeling choice) |
| `MAKEX/settim: Unknown firmware version ... jav ...` | The receiver firmware string is not in the known list | Ignore (informational only) |
| `MAKEX/rhead: Wavelength factors missing from RINEX header, set=1` | Modern RINEX headers have no wavelength-factor field | Ignore |
| `MAKEJ/makej: SP3 file not specified ... use the nav-file` | The j-file clock falls back to the navigation file | Ignore (GPS default) |
| `*/rsesfo: Session number is zero; setting to 1` | Single-session default | Ignore |
> The diagnosis layer triggers self-correction only on `GAMIT.fatal` and substandard QC; warnings are incorporated into root-cause analysis only when QC is simultaneously degraded.

## G. verified live-run fingerprints (injection-based, na01 2023 DOY100, complete inject→detect→fix→recover loop)
The diagnosis layer matches on these **exact fingerprints** (original substrings) to avoid generalized misjudgment. They were verified through a complete inject -> detect -> fix -> recover loop on a live GAMIT run.

| Class | Injection | Abort stage | Exact GAMIT.fatal / log fingerprint | Fix action | Recovery |
|---|---|---|---|---|---|
| **A** missing station.info | Delete a site's entry | MAKEX (after makexp) | `MAKEX/lib/rstnfo: No match for <SITE> <yr> <doy>  0  0  0 in station.info`; then `FIXDRV: GAMIT.fatal exists: FIXDRV not executed` | Rebuild the site entry from the RINEX header with mstinf | ✅ 4 sites/nrms 0.21 |
| **D** illegal antenna name | Change the antenna to a model outside antmod/rcvant | **MAKEXP (earlier)** | `MAKEXP/lib/read_rcvant: Antenna name <ANT> not found in rcvant.dat`; then `Failure in sh_preproc. STATUS 14` | Correct using the real antenna name from the RINEX header; when no PCV is available, downgrade sestbl to `Antenna Model=ELEV` | ✅ 4 sites/nrms 0.21 |
| **C** orbit unavailable | `-orbit codf -noftp` (not present locally) | **orbit stage (earliest, before makex)** | `No g- or sp3-files available and noftp = Y, cannot continue` | Switch to an available orbit product (igsf) or go online and change source (local > sopac anonymous > cddis requires authentication) | ✅ 4 sites/nrms 0.21 |

**Two cross-cutting lessons (already incorporated into workflow.md/qc.md)**:
1. After all three failure-class aborts, `sh_gamit_<doy>.summary` holds the **previous stale value** → the diagnosis layer **must read `GAMIT.fatal`/the exit status first, then read the summary**.
2. Failure stages have a temporal order: orbit (earliest) → MAKEXP antenna name → MAKEX station.info → MODEL/SOLVE; localizing in this order quickly hits the root cause.

| **D′** receiver-name letter case | RINEX header mixed case (e.g. `Trimble NetR9`) written verbatim into station.info | **MAKEXP** | `MAKEXP/lib/read_rcvant: Receiver name <name> not found in rcvant.dat` | rcvant.dat follows the IGS convention of **all uppercase**; when building station.info yourself, normalize the rec/ant/dome names with `.upper()` | ✅ knet16 SDSM, 2026-06-04 |

## H. silently dropped sites (NoPrefit/NoPostfit — a solution is produced but a site quietly disappears, **no fatal**)
When GAMIT encounters a bad site it often does not raise an error; it simply removes it from the solution and continues. The whole-network summary looks normal but is missing a site. **Use the `diagnose_drops` tool** (reads the summary + autcln.out + prefit.sum + station.info) to proactively flush these out.
- **Detection signal**: `sh_gamit_<doy>.summary` shows `<SITE> NoPrefit` / `<SITE> NoPostfit`; that site's RMS/NUM/AMS lines are all 0.
- **Evidence sources**: `C R <SITE> No Data` / `Removing <SITE> ... missing satellite` in `autcln.out(.gz)`; the obs count in `autcln.prefit.sum`.
- **Candidate root causes (ranked)**: ① autcln judges there is no usable data (reduced to zero after double-differencing); ② missing common-view satellites; ③ **the only receiver of a given brand in the network** (e.g. the sole Septentrio) → RINEX observation-code/signal incompatibility; ④ missing antenna phase-center model (check antmod.dat); ⑤ too few observations.
- **Fix**: depending on the root cause — drop the site and accept a downgrade / correct its RINEX observation types / add antmod / change the data.
- ✅ Empirical: knet16 2023/100, GKPG (the sole SEPT POLARX5 + SEPCHOKE_B3E6) was judged `No Data` and dropped; the 15 valid sites still gave nrms 0.186.

## I. latent quality errors (**no error raised**, distilled from a nine-year operational GAMIT/GLOBK project; confidence: high unless otherwise noted)
These throw no fatal yet determine the quality of the results — this is the main battlefield of the "expert 20%".
| Pattern | Latent symptom | Stage | Root cause | Fix / detection |
|---|---|---|---|---|
| **Antenna "legal but mistyped"** | No error, abnormally high height std (44→11mm) | Planted before MAKEXP | station.info antenna model ≠ the true value in the RINEX header | `rinex_audit` scans the header to compare and correct; inspect multi-day std (already tooled) |
| **Missing GLOBK frame** | Height drifts/bimodal with network geometry (DAEJ 14.8→5.7mm) | After SOLVE | The loose solution has no absolute datum | `globk_frame` two-pass method (htoglb→globk→glorg) (already tooled) |
| **Unmodeled break point** | Huge std at a site (SDSM 1305mm) | GLOBK statistics | Real jump from monument relocation/antenna change not split into separate site segments | GLOBK `eq_file` rename to split segments + exclude from the stab site set |
| **Network-geometry asymmetry** | Systematic offset at reference sites on dates corresponding to gap sites | baseline geometry | Changing participant site set biases the network geometry | GLOBK frame stabilization / tighten anchor-site constraints / filter dates |
| **Height-extraction bug** | Absolute height systematically too low by ~65m | Post-processing | Geocentric latitude wrongly fed into the geodetic-latitude formula | Bowring closed-form solution (already correct in this project's stations.py) |
| **IGS product rename** | After 2022-11-27 (wk2238) sp3 downloads are empty files | Orbit retrieval | IGS 3.0 long file names | Switch long/short names + source by GPS week (IGN FTP requires no authentication) |

## J. community/official reported errors (distilled online 2026-06-04, with sources; confidence: high = official / well-known educator, labeled "externally reported, not locally reproduced")
Sources: GAMIT official Known Issues/FAQ (geoweb.mit.edu/gg/issues.php, faqs.php), Eric Lindsey tutorial Appendix B
(planetmechanic.net/gamit-globk-tutorial), Hidayat Panuntun blog (hidayatpanuntun.staff.ugm.ac.id).
Exact fingerprints are recorded verbatim from these sources for the diagnosis layer to match; **not yet reproduced locally**, so trust with caution.

| Class | Exact fingerprint (original text) | Stage | Root cause | Fix |
|---|---|---|---|---|
| **EOP/UT1 out of date** | `NGSTOT/lib/ut1red: JD= <n> out of range of ut1 table` | sh_sp3fit/orbit | Observation date exceeds the ut1 table range; automatic update failed | Download new `pole.usno`/`ut1.usno`/`pmu.bull_a` (SOPAC) into gg/tables and rerun |
| **Pole table out of date** | `ARC/lib/polred: JD= <n> out of range of pole table` | ARC/sh_sp3fit | Same as above, the pole table predates the observation date | Same as above (update the three EOP files) |
| **Grid out of date** | `GRDTAB/grdtab: Requested day beyond grid: Range <y1> <y2>` | GRDTAB | The atmosphere/loading grid date range does not cover the observation date, or the RINEX is not a complete single day | Update the grid/EOP files; check the RINEX span against the sh_gamit date |
| **Ocean-loading file missing** | `FIXDRV/bmake: Ocean loading requested no list or grid file` | FIXDRV | Missing otl*.grid (not shipped with the default installation) | Download `otl*.grid` from everest.mit.edu (pub/GRIDS/) into ~/gg/tables, delete the day directory and rerun |
| **Missing navigation file (-noftp)** | `-noftp = Y : You must have .../brdcDDD0.YYn or .Z available to continue` | Preprocessing | -noftp set but no local brdc | `cd brdc; sh_get_nav -yr <y> -doy <d> -ndays <n>` (corresponds to the in-place priority chain of our `_ensure_brdc`) |
| **sestbl/sittbl format error** | `FIXDRV/fixdrv: Sestbl or sittbl errors--see GAMIT.warning` | FIXDRV | sittbl column misalignment / contains tabs (whitespace-sensitive) | Check column alignment, copy a fresh sittbl from gg/tables and reconfigure (corroborates our STATION_INFO_ALIGNMENT) |
| **SOLVE inversion failure** | `SOLVE/lcloos: Inversion error in LCNORM(2)` | SOLVE | Singular normal equations (ill-conditioned site/parameter constraints, too little data) | Check the valid site count/constraints for that day; drop bad sites, loosen/add constraints, then re-solve |
| **Small x-file discarded** | autcln "too few data" / site has no solution, an oversized-small x-file is ignored | MAKEX/AUTCLN | Observation file too small (< threshold) | Adjust `minxf` in `process.defaults` (minimum observation file in KB, default about 300KB) |
| **Non-IGS device name (supplements D′)** | `read_rcvant: ... not found in rcvant.dat` | MAKEXP | RINEX-header rec/ant name is not IGS standard | Official method: add to `~/gg/tables/guess_rcvant.dat` a mapping that uniquely matches a substring in the header (we additionally use `.upper()` normalization) |

Cross-cutting corroboration: ① the official "a good solution has postfit nrms < 0.2 (often ~0.18), 0.21 counts as poor" — consistent with the baseline in our qc.md;
② site RMS expected < 10mm; ③ paths must not contain spaces/periods/non-alphanumeric characters; ④ the missing-orbit fingerprint matches our class C verbatim.

## To be added
- [ ] **Injection-based local reproduction** of several class-J items (EOP out of date, ocean-loading file missing, SOLVE inversion), adding the "verified" mark.
- [ ] Deposit class-B fingerprints (bad a priori, QC-driven rather than hard fatal); live-run fingerprints for mixed multi-GNSS.
- [ ] The **fix** path for the GKPG-class Septentrio incompatibility (currently only diagnosis is reached; need to verify whether correcting the observation types can recover it).
