# GAMIT-Agent

**An LLM agent that operates native GAMIT/GLOBK end to end — from a folder of bare RINEX to a quality-controlled solution.**

GAMIT/GLOBK is a reference-standard package for high-precision GNSS geodesy, but it has a steep
learning curve: dozens of fixed-format control files, terse logs, and manual error recovery.
Existing wrappers automate *running* the pipeline; GAMIT-Agent adds the missing layer —
**diagnosis and decision-making**. It builds a runnable project from raw RINEX, drives native
`sh_gamit`/GLOBK, reads the logs to classify and self-correct failures, audits metadata for
"legal but wrong" errors that raise no message, and produces a QC verdict — behind a web UI and
a model-agnostic, bring-your-own-key LLM engine.

This repository accompanies a paper that is currently under submission.

---

## Highlights
- **Bare RINEX → trustworthy solution.** `init_project` builds the full control-file set
  (incl. `station.info` from RINEX headers) and supplies non-IGS *a priori* coordinates via
  `sh_rx2apr`. On a 16-station Korean network built entirely from scratch: postfit nrms **0.186**,
  GLOBK heights within **1–3 cm** of an independent multi-year reference.
- **Self-correction.** An error → root-cause → fix knowledge base with exact log fingerprints;
  validated on injected faults (missing `station.info`, unavailable orbit, illegal antenna name)
  and long-tail errors distilled from a 9-year operational record and the official issue list.
- **Autonomous metadata audit.** `rinex_audit` independently reproduced 8 mis-recorded antennas
  in a real project (8/8, zero false positives) — errors that raise no GAMIT message.
- **Model-agnostic.** OpenAI-compatible engine; DeepSeek by default; bring your own key.
  An ablation shows correct fault classification comes from the architecture (knowledge base +
  deterministic tools), not from any specific model.
- **Local manual RAG.** Pure-Python BM25 over the GAMIT `.hlp` manuals and `sh_*` scripts, so the
  agent looks up exact options instead of inventing them. No embedding model, no network.

## Requirements
- A working **GAMIT/GLOBK** installation (not redistributable; install it yourself).
- Python 3.11+; `pip install -r requirements-app.txt`.
- An OpenAI-compatible API key (DeepSeek by default).

## Quick start
```bash
pip install -r requirements-app.txt
cp app/.env.example app/.env       # add your DEEPSEEK_API_KEY (or set it in the UI later)
cd app && uvicorn backend.server:app --host 0.0.0.0 --port 8765
# open http://localhost:8765   (remote: ssh -L 8765:localhost:8765 user@host)
```
In the UI: **＋ New project** → *Browse…* a local RINEX folder → **Build project** → the network
loads on the map → use the analysis panels (QC / dropped sites / network geometry) or chat with
the agent.

Docker (GAMIT mounted as a volume, not baked in): see [`DOCKER.md`](DOCKER.md).

## Reproduce the worked example
A four-station sample dataset ships in [`sample_data/`](sample_data/). See
[`docs/USER_MANUAL.md`](docs/USER_MANUAL.md#5-worked-example) for a step-by-step run and the
expected output.

## Repository layout
```
app/            agent backend (FastAPI+SSE), web frontend, deterministic tools, tests
skill/          knowledge base (references/*.md) — also the agent's system-prompt source
docs/           user manual
sample_data/    sample RINEX dataset (zip) for the worked example
DOCKER.md       containerized deployment
```

## License
Apache License 2.0 — see [`LICENSE`](LICENSE). GAMIT/GLOBK is **not** included and is governed by
its own license from MIT.

## Citation
If you use GAMIT-Agent, please cite the accompanying paper (currently under submission).
