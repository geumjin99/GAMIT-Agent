# Running / distributing GAMIT-Agent with Docker

The GAMIT/GLOBK license is not redistributable, so **the image does not contain GAMIT itself** —
it assumes you already have GAMIT installed somewhere and mount it into the container with a volume.
The image only carries the agent + Python dependencies + the system packages GAMIT scripts need
(csh / gfortran / wget).

## 1. Prerequisites
- A working GAMIT/GLOBK installation (i.e. `sh_gamit` runs on your machine); note its root (e.g. `/home/you/gg`).
- An OpenAI-compatible API key (DeepSeek by default; you can also enter it in the UI Settings).
- That GAMIT must be **binary-compatible** with the container runtime (linux x86_64 / glibc) — usually fine on same-arch Linux (see "Notes").

## 2. Quick start (compose)
1. Edit the 4 spots in `docker-compose.yml`: `GG_PATH` (your gg), `DATA_PATH` (your RINEX data), `DEEPSEEK_API_KEY`.
   Or use environment variables:
   ```bash
   export GG_PATH=/home/you/gg
   export DATA_PATH=/mnt/your/rinex
   export DEEPSEEK_API_KEY=sk-xxxx
   ```
2. Start:
   ```bash
   docker compose up --build
   ```
3. Open `http://localhost:8765` (wait for the container to report `healthy`).
   - Left "＋ New project (from bare RINEX)" → Browse…: the picker opens at `/data` (your mounted pool),
     so you click down to the folder instead of typing a path. Add experiment name + year → Build project.
   - It auto-loads onto the map; the chat panel lets the agent run/diagnose/produce QC.

## 3. Plain docker run (without compose)
```bash
docker build -t gamit-agent .
docker run --rm -p 8765:8765 \
  -v /home/you/gg:/gg \
  -v /mnt/your/rinex:/data:ro \
  -v $PWD/experiments:/opt/gamit-agent/app/experiments \
  -e DEEPSEEK_API_KEY=sk-xxxx \
  gamit-agent
```

## 4. Mount points
| In container | Purpose | Required |
|---|---|---|
| `/gg` | Your installed GAMIT/GLOBK (`GG_DIR` points here) | ✅ |
| `/data` | Your bare RINEX / data pool (read-only; the UI folder browser opens here) | recommended |
| `/opt/gamit-agent/app/experiments` | Persist project outputs back to the host | recommended |
| `/opt/gamit-agent/app/runs` | Persist agent run history | optional |
| `/opt/gamit-agent/app/logs` | Persist backend logs | optional |

The folder browser starts at `GAMIT_BROWSE_ROOT` (default `/data` in the image), so the mounted data
pool is reachable without typing a full path. Override it to browse elsewhere (e.g.
`/opt/gamit-agent/app/experiments` if you do not mount `/data`).

## 5. Notes / troubleshooting
- **Binary compatibility**: the mounted `/gg` was compiled on the host; if `gamit/bin` won't run in the
  container due to a glibc mismatch, the image ships `gfortran`+`make` and the agent's **svpos self-healing**
  recompiles the kf modules; if the main programs are incompatible, recompile GAMIT in an environment matching the container.
- **Key never persisted**: you can omit it from the command and enter it in the UI Settings after startup (memory only).
- **Orbits/ephemeris**: offline, the agent uses the nav/sp3 sitting in your mounted data; online, the container's `wget` drives `sh_get_nav` (SOPAC anonymous).
- **Port**: 8765 inside the container; remap on the host with `-p HOST:8765`.
- **Health check**: the image polls `/api/health`; `docker ps` shows `healthy` once the server is up. The
  backend also exposes `/api/health`, `/api/logs`, and `/api/runs` for monitoring.

## 6. What's in / not in the image
- In: the agent backend (FastAPI+SSE) + frontend + all deterministic tools + the GAMIT manual RAG + the knowledge base (skill/references).
- Not in: GAMIT/GLOBK itself (mounted), your data, your API key.
