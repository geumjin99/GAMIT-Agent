"""Centralized logging for GAMIT-Agent.

Provides:
  - A rotating file handler  (logs/gamit-agent.log, size-based rotation)
  - A console handler
  - An in-memory ring buffer of recent records, so the web UI can show logs
    via /api/logs without shipping the log file around.

Import `get_logger(name)` everywhere; call `setup_logging()` once at startup.
"""
import logging
import logging.handlers
from collections import deque
from pathlib import Path
from threading import Lock

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "gamit-agent.log"

_FMT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

# in-memory ring buffer (thread-safe) of the last N formatted lines
_RING_MAX = 1000
_ring = deque(maxlen=_RING_MAX)
_ring_lock = Lock()
_configured = False


class _RingHandler(logging.Handler):
    """Keep the last N formatted log lines in memory for the /api/logs endpoint."""

    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:
            return
        with _ring_lock:
            _ring.append(line)


def setup_logging(level=logging.INFO):
    """Configure root logging once (file rotation + console + ring buffer)."""
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    root = logging.getLogger()
    root.setLevel(level)

    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    rh = _RingHandler()
    rh.setFormatter(fmt)
    root.addHandler(rh)

    _configured = True
    logging.getLogger("gamit.startup").info("logging initialized -> %s", LOG_FILE)


def get_logger(name):
    return logging.getLogger(name)


def recent_logs(n=200, level=None):
    """Return the last n buffered log lines (optionally filtered by level token)."""
    with _ring_lock:
        lines = list(_ring)
    if level:
        lvl = level.upper()
        lines = [ln for ln in lines if f" {lvl} " in ln or f" {lvl:<7} " in ln]
    return lines[-n:]
