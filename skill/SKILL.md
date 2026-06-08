---
name: gamit-agent
description: An agent that drives native GAMIT for end-to-end processing of high-precision GPS/GNSS data. Given RINEX data and a natural-language intent (sites, date range, reference frame, desired products), it automatically generates GAMIT control files, runs sh_gamit to produce solutions, parses logs and self-diagnoses/self-corrects, and delivers QC reports together with coordinates/time series. Use when the user wants to process GPS data with GAMIT, set up a GAMIT experiment, fix GAMIT/sh_gamit errors, generate sestbl./sittbl./station.info, or get coordinates/time series from RINEX.
---

# GAMIT-Agent (skeleton — under development)

Drives the native GAMIT installation at `~/gg` for end-to-end processing. **Use only real GAMIT commands; never fabricate results.**

## Workflow (four layers)
1. **Planning layer** — parse the intent (sites / date range / reference frame / products), select templates, and generate control files.
   Reference: `references/control-files.md`.
2. **Execution layer** — `sh_setup` → `sh_get_orbits` → `sh_gamit`, capturing all stdout/logs.
   Reference: `references/workflow.md` (to be written).
3. **Diagnosis and self-correction layer** — parse `*.fatal` / `sh_gamit.log` / q-file / `autcln.out` / `sh_gamit.summary`,
   compute QC metrics (nrms, postfit rms, WL/NL ambiguity fixing rates), decide pass/fail → locate the root cause → apply a patch → rerun.
   Reference: `references/errors.md` + `references/qc.md` (to be written).
4. **Reporting layer** — output a QC report + coordinate/time-series plots.

## Hard-stop criteria (to prevent infinite reruns)
- Maximum of **N=3** retries per experiment; each retry must change at least one localizable configuration item, and must record the "hypothesis → change → result".
- Two consecutive retries with no improvement in QC metrics → stop and produce a diagnostic report for human review.
- Any required online download fails with no local fallback → stop and clearly report the missing resource.

## Key constraints
- Hard configuration-consistency checks (see the final section of control-files.md): reference-frame triad consistency, station.info coverage, sampling match, and zeroing-out of offline sources.
- Paths: GAMIT installation `GG=~/gg`, standard tables `~/gg/tables`, help `~/gg/help`.

## references/
- `control-files.md` ✅ Control-file schemas and hard consistency constraints
- `workflow.md` ⏳ Command sequence, parameters, product inventory, log locations
- `errors.md` ⏳ Error → root cause → fix catalog
- `qc.md` ⏳ QC metric definitions and pass/fail thresholds
