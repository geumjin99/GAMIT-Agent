# QC metric definitions and pass/fail thresholds (criteria for diagnosis layer ③)

> Sources: `sh_gamit_<doy>.summary` and the q-file. The thresholds are empirical industry ranges, **to be back-filled after calibration with real cases in P2**.

## Core metrics
| Metric | Taken from | Pass | Warning | Fail → triggers self-correction |
|---|---|---|---|---|
| **postfit nrms** | summary / q-file | ~0.18–0.25 | 0.25–0.5 | >0.5 (model/data/frame problem) |
| **prefit nrms** | summary / q-file | < ~5, and being far larger than postfit is normal | — | huge (>10) usually indicates poor a priori coordinates → errors.md B |
| **WL (wide-lane) fixing rate** | summary | > 90% | 80–90% | < 80% (metadata/data quality/baseline too long) |
| **NL (narrow-lane) fixing rate** | summary | > 80–90% | 70–80% | < 70% (same as above + troposphere/ionosphere constraints) |
| Number of sites in the solution | summary | = expected site count | short by 1–2 | several sites missing → errors.md A/D |
| Per-site observation count / deletion rate | autcln.out.postfit | low deletion rate, ample observations | — | observation count at a site drops sharply → errors.md D |

## Interpretation logic (pseudocode)
```
if exists(GAMIT.fatal):              -> fail, localize the root cause per errors.md
elif postfit_nrms > 0.5:             -> fail, check data volume (autcln) → frame (sestbl/apr) → metadata
elif WL% < 80 or NL% < 70:           -> warn/fail, check station.info & baselines & troposphere constraints
elif sites in solution < expected:   -> warn, check the cause of missing sites (A/D)
else:                                -> pass, produce the report
```

## The report should contain
- Per day: postfit nrms, prefit nrms, WL/NL fixing rates, number of sites in the solution.
- Trends: multi-day nrms / fixing-rate time series (anomalous days highlighted).
- Self-correction trace: each "hypothesis → change → result" (reproducible, can be written into the methods section of a paper).

## Measured baseline (calibrated in this environment, 2023 DOY100, 4 sites ALBH/DRAO/NLIB/PIE1, igb20, ~1.5 min)
This is what a "passing solution" on clean IGS data looks like, and can serve as a reference anchor for the diagnosis layer:
- Postfit nrms **0.210–0.219** (prefit ~1.00) → confirms the pass range ~0.2 is genuinely achievable.
- WL fixing rate **92.5%**, NL **90.3%** (93 ambiguities, 93 expected).
- Per-site postfit RMS: PIE1 5.6 / ALBH 5.7 / DRAO ~6 / NLIB 8.0 mm.
- Coordinate corrections 1–2 cm, formal errors ~2.5 cm (loosely constrained single-day solution), 14113 double differences.
- Products: `qna01a.100` (q-file), `ona01a.100` (o-file), `hna01a.23100` (h-file), `sh_gamit_100.summary`.
→ The "pass" column in the threshold table is already consistent with this; the "warning/fail" boundaries will be refined later only when degraded cases appear.
