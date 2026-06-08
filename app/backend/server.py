"""GAMIT-Agent backend: FastAPI + Server-Sent Events.

An LLM-driven agent that operates native GAMIT/GLOBK end to end, served behind a
single-page web UI (station map + chat + live logs). Model-agnostic (DeepSeek by
default; base_url is swappable). The API key is bring-your-own-key, read from .env
and overridable at runtime via /api/config (never persisted to disk).

Run:  cd app && uvicorn backend.server:app --host 0.0.0.0 --port 8765
SSH:  ssh -L 8765:localhost:8765 <host>, then open http://localhost:8765
"""
import os
import sys
import json
import time
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # backend/ on path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from applog import setup_logging, get_logger, recent_logs
from config import settings, REPO_DIR
from engine import LLMEngine
from agent import GamitAgent
from tools import rinex_audit as ra
from tools import multiday_std as ms
from tools import stations as st
from tools import init_project as ip
from tools import diagnose_drops as dd
from tools import network_geometry as ng
from tools import qc_report as qr

setup_logging()
log = get_logger("gamit.server")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="GAMIT-Agent")


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    t0 = time.time()
    resp = await call_next(request)
    dt = (time.time() - t0) * 1000
    # keep noise down: skip static asset polling
    if not request.url.path.endswith((".js", ".css")):
        log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path,
                 resp.status_code, dt)
    return resp


def _engine():
    return LLMEngine(settings.api_key, settings.base_url, settings.model,
                     temperature=settings.temperature, max_tokens=settings.max_tokens)


def _resolve_project(project: str) -> Path:
    """Resolve a project path from the UI to an absolute path (relative -> repo root)."""
    p = Path(project).expanduser()
    if not p.is_absolute():
        p = (REPO_DIR / project).resolve()
    return p


# ----------------------------------------------------------------- static frontend
@app.get("/", response_class=HTMLResponse)
async def root():
    return (FRONTEND / "index.html").read_text()


@app.get("/app.js")
async def appjs():
    return FileResponse(FRONTEND / "app.js", media_type="application/javascript")


@app.get("/style.css")
async def css():
    return FileResponse(FRONTEND / "style.css", media_type="text/css")


# ----------------------------------------------------------------- config (API key)
@app.get("/api/config")
async def get_config():
    return JSONResponse(settings.masked())


@app.post("/api/config")
async def set_config(request: Request):
    body = await request.json()
    settings.update(api_key=body.get("api_key"), base_url=body.get("base_url"),
                    model=body.get("model"))
    log.info("config updated (model=%s, has_key=%s)", settings.model, bool(settings.api_key))
    return JSONResponse({"ok": True, **settings.masked()})


# ----------------------------------------------------------------- project / map
@app.get("/api/project")
async def api_project(dir: str, expt: str = None):
    proj = _resolve_project(dir)
    if not proj.is_dir():
        return JSONResponse({"error": f"project directory not found: {proj}"}, status_code=404)
    days = sorted(p.name for p in proj.iterdir()
                  if p.is_dir() and p.name[:3].isdigit())
    # guess expt from a q-file name if not given
    if not expt:
        qf = next(proj.rglob("q????a.*"), None)
        expt = qf.name[1:5] if qf else None
    return JSONResponse({"project": str(proj), "expt": expt, "days": days})


@app.get("/api/stations")
async def api_stations(dir: str, expt: str = None, audit: bool = False,
                       std: bool = False):
    proj = _resolve_project(dir)
    if not proj.is_dir():
        return JSONResponse({"error": f"project directory not found: {proj}"}, status_code=404)
    notes = []
    audit_rep = std_rep = None
    if audit:
        try:
            audit_rep = ra.audit_project(str(proj))
            if audit_rep and "error" in audit_rep:
                notes.append("audit skipped: " + audit_rep["error"]); audit_rep = None
        except Exception as e:
            notes.append(f"audit failed (ignored): {e}"); audit_rep = None
    if std and expt:
        try:
            std_rep = ms.multiday_std(str(proj), expt)
            if std_rep and "error" in std_rep:
                notes.append("multiday-std skipped: " + std_rep["error"]); std_rep = None
        except Exception as e:
            notes.append(f"multiday-std failed (ignored): {e}"); std_rep = None
    gj = st.stations_geojson(str(proj), expt=expt, audit_report=audit_rep, std_report=std_rep)
    gj.setdefault("meta", {})["notes"] = notes
    return JSONResponse(gj)


@app.get("/api/audit")
async def api_audit(dir: str):
    proj = _resolve_project(dir)
    return JSONResponse(ra.audit_project(str(proj)))


@app.post("/api/init_project")
async def api_init_project(request: Request):
    """Build a runnable GAMIT project from a folder of bare RINEX (the newcomer's first jump).
    body: {project_dir, rinex_src, expt, year, doy?, apr?, frame?}"""
    body = await request.json()
    rinex_src = (body.get("rinex_src") or "").strip()
    expt = (body.get("expt") or "").strip()
    year = body.get("year")
    if not rinex_src or not expt or not year:
        return JSONResponse({"error": "rinex_src, expt and year are required"}, status_code=400)
    src = Path(rinex_src).expanduser()
    if not src.exists():
        return JSONResponse({"error": f"local path does not exist: {src}"}, status_code=404)
    proj = _resolve_project(body.get("project_dir") or f"experiments/{expt}")
    log.info("init_project: src=%s expt=%s year=%s -> %s", src, expt, year, proj)
    try:
        r = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ip.init_project(
                str(proj), expt, int(year), str(src),
                doy=body.get("doy"),
                apr=body.get("apr", "igb20_comb.apr"),
                frame=body.get("frame", "IGb20")))
    except Exception as e:
        log.exception("init_project failed")
        return JSONResponse({"error": f"init_project failed: {e}"}, status_code=500)
    log.info("init_project done: ready=%s sites=%s", r.get("ready"), len(r.get("sites", [])))
    return JSONResponse(r)


# ----------------------------------------------------------------- agent SSE
def _save_run(meta, events):
    """Persist one agent run (input + streamed events + result) under runs/ for replay."""
    rid = time.strftime("%Y%m%d_%H%M%S") + f"_{meta.get('expt') or 'run'}"
    try:
        (RUNS_DIR / f"{rid}.json").write_text(
            json.dumps({**meta, "events": events}, ensure_ascii=False, indent=1, default=str))
    except Exception:
        log.exception("failed to persist run %s", rid)
    return rid


@app.post("/api/run")
async def api_run(request: Request):
    body = await request.json()
    instruction = body.get("instruction", "")
    proj = _resolve_project(body.get("dir", "."))
    max_rounds = int(body.get("max_rounds", 20))

    if not settings.api_key:
        async def err():
            yield {"event": "error", "data": json.dumps(
                {"message": "No API key configured. Set your key in Settings."})}
        return EventSourceResponse(err())

    agent = GamitAgent(str(proj), _engine(), max_rounds=max_rounds)
    log.info("agent run start: project=%s rounds=%d instruction=%r", proj, max_rounds, instruction[:120])

    async def gen():
        events = []
        yield {"event": "start", "data": json.dumps(
            {"project": str(proj), "model": settings.model})}
        loop = asyncio.get_event_loop()
        it = agent.run_stream(instruction)
        while True:
            try:
                # the agent is a sync generator; pull it step by step in a thread
                # pool so we never block the event loop
                ev = await loop.run_in_executor(None, lambda: next(it, None))
            except Exception as e:
                log.exception("agent run error")
                yield {"event": "error", "data": json.dumps({"message": str(e)})}
                break
            if ev is None:
                break
            events.append(ev)
            if ev.get("type") in ("observation", "final", "error"):
                log.info("agent round %s: %s", ev.get("round"), ev.get("action") or ev.get("type"))
            if await request.is_disconnected():
                log.info("client disconnected; aborting run")
                break
            yield {"event": ev["type"], "data": json.dumps(ev, ensure_ascii=False, default=str)}
        rid = _save_run({"instruction": instruction, "project": str(proj),
                         "model": settings.model, "expt": body.get("expt")}, events)
        log.info("agent run finished: %d events, saved as %s", len(events), rid)
        yield {"event": "done", "data": json.dumps({"run_id": rid})}

    return EventSourceResponse(gen())


_RINEX_GLOBS = ("*.??o", "*.??o.gz", "*.??o.Z", "*.??d", "*.??d.gz", "*.??d.Z", "*.crx*")


@app.get("/api/browse")
async def api_browse(path: str = ""):
    """Server-side directory browser for the folder picker. Returns sub-directories
    plus the count of recognizable RINEX files in each. The default start directory is
    GAMIT_BROWSE_ROOT (set to /data in the Docker image) so the mounted data is reachable;
    it falls back to the user's home directory outside a container."""
    default_root = os.environ.get("GAMIT_BROWSE_ROOT") or str(Path.home())
    base = Path(path).expanduser() if path else Path(default_root)
    base = base.resolve()
    if not base.is_dir():
        return JSONResponse({"error": f"not a directory: {base}"}, status_code=404)
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except PermissionError:
        return JSONResponse({"error": f"permission denied: {base}"}, status_code=403)
    dirs = []
    for p in entries:
        if p.is_dir() and not p.name.startswith("."):
            try:
                rc = sum(1 for g in _RINEX_GLOBS for _ in p.glob(g))
            except Exception:
                rc = 0
            dirs.append({"name": p.name, "path": str(p), "rinex_count": rc})
    self_rc = sum(1 for g in _RINEX_GLOBS for _ in base.glob(g))
    return JSONResponse({"path": str(base), "parent": str(base.parent) if base.parent != base else None,
                         "dirs": dirs, "rinex_count": self_rc})


@app.get("/api/qc")
async def api_qc(dir: str, doy: int, expt: str = None):
    proj = _resolve_project(dir)
    return JSONResponse(qr.qc_report(str(proj), doy, expt=expt))


@app.get("/api/drops")
async def api_drops(dir: str, doy: int, expt: str = None):
    proj = _resolve_project(dir)
    return JSONResponse(dd.diagnose_drops(str(proj), doy, expt=expt))


@app.get("/api/geometry")
async def api_geometry(dir: str):
    proj = _resolve_project(dir)
    return JSONResponse(ng.network_geometry(str(proj)))


# ----------------------------------------------------------------- logs & run history
@app.get("/api/logs")
async def api_logs(n: int = 200, level: str = None):
    """Recent backend log lines (from the in-memory ring buffer)."""
    return JSONResponse({"lines": recent_logs(n=n, level=level)})


@app.get("/api/runs")
async def api_runs(limit: int = 30):
    """List persisted agent runs (most recent first)."""
    files = sorted(RUNS_DIR.glob("*.json"), reverse=True)[:limit]
    out = []
    for f in files:
        try:
            d = json.loads(f.read_text())
            out.append({"run_id": f.stem, "instruction": (d.get("instruction") or "")[:120],
                        "project": d.get("project"), "n_events": len(d.get("events", []))})
        except Exception:
            continue
    return JSONResponse({"runs": out})


@app.get("/api/runs/{run_id}")
async def api_run_detail(run_id: str):
    f = RUNS_DIR / f"{run_id}.json"
    if not f.is_file():
        return JSONResponse({"error": "run not found"}, status_code=404)
    return JSONResponse(json.loads(f.read_text()))


@app.get("/api/health")
async def health():
    return {"ok": True, "has_key": bool(settings.api_key), "model": settings.model}
