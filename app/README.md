# GAMIT-Agent (app/) — LLM-driven GAMIT processing software

A model-agnostic standalone agent + HTML frontend that operates native GAMIT end to end:
RINEX + natural-language intent → run sh_gamit → read logs to self-diagnose / self-correct →
metadata audit / multi-day std / GLOBK frame solution → QC report.
Defaults to DeepSeek (cheap and accessible); the engine is OpenAI-compatible with a swappable
base_url (Claude / GPT / local).

## Run
```bash
pip install -r ../requirements-app.txt
# configure the key: copy app/.env.example -> app/.env and set DEEPSEEK_API_KEY (or use Settings in the UI)
cd app && uvicorn backend.server:app --host 0.0.0.0 --port 8765
# open http://localhost:8765
# remote over SSH: ssh -L 8765:localhost:8765 user@host, then open it locally
```

## Layout
```
backend/
  server.py    FastAPI+SSE: /api/{project,stations,init_project,run(SSE),qc,drops,geometry,
               browse,config,logs,runs,health}
  agent.py     DeepSeek ReAct loop (Thought/Action/Args + loop guard + GAMIT hard-stop discipline)
  engine.py    OpenAI-compatible engine (model-agnostic)
  config.py    .env + /api/config override (bring-your-own-key, never persisted)
  knowledge.py loads ../skill/references/*.md as the system prompt
  applog.py    centralized logging (rotating file + console + in-memory ring buffer for /api/logs)
  gamit_rag.py local BM25 search over the GAMIT/GLOBK manual (.hlp + sh_* scripts)
  tools/       deterministic tools (the LLM only orchestrates):
    gamit_tools     list/read/run_sh_gamit/parse_summary/parse_qfile/check_status
    init_project    bare RINEX -> full control files (station.info etc.) + sh_rx2apr a priori
    rinex_audit     RINEX header <-> station.info audit (milestone: reproduced 8 antenna errors)
    multiday_std    multi-day per-station coordinate std
    stations        station GeoJSON (ECEF -> geodetic, for the map)
    globk_frame     GLOBK multi-station Helmert frame solution (htoglb->globk->glorg->.org)
    diagnose_drops  diagnose silently dropped stations (NoPrefit/NoPostfit)
    network_geometry quick network-geometry health check
    qc_report       one-stop QC verdict (pass/warn/fail)
    registry        tool registry + descriptions for the system prompt
frontend/      index.html / app.js / style.css (Leaflet map + station detail + agent chat SSE
               + folder browser + analysis-tool panel + Settings + logs viewer)
probe/         decision validation: probe_deepseek.py (A/C/D competence), ablation.py
               (knowledge/discipline ablation), milestone_rinex_audit.py (8/8)
tests/         pytest regression suite over the backend tools
```

## Validated (see probe/*_RESULT.md)
- DeepSeek driving the GAMIT diagnosis loop: classes A/C/D, real faults, 7/7 each.
- rinex_audit reproducing the 8 antenna errors from a nine-year operational project: 8/8 (+3 real findings, 0 false positives).
- run_sh_gamit calling native GAMIT: na01 nrms 0.218 / WL 92.5 / NL 90.3, consistent with the reference.
- End-to-end SSE: frontend -> server -> agent -> DeepSeek -> tools -> streamed display; class-A diagnosis converges in 7 rounds.
- Station coordinates: DAEJ 116.8 m matches an independent GLOBK reference value (avoids the geocentric-latitude bug).
- globk_frame: htoglb->globk->glorg->.org runs end to end; height parsing correct.
- Bare RINEX from scratch: 16-station Korean network, all coordinates from sh_rx2apr, nrms 0.186, GLOBK heights within cm of the reference.
- Knowledge-base ablation: with the knowledge base 2/3 vs without it 0/3 — correct classification comes from the architecture, not the model.
```
