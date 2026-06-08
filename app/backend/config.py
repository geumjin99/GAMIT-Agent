"""Runtime configuration: read DeepSeek (OpenAI-compatible) credentials from app/.env; the
in-memory settings can be overridden by the front-end /api/config.

Design: the product model is "bring your own token". The engine layer uses an OpenAI-compatible
interface (base_url swappable), DeepSeek by default (cheap and readily available); users wanting
the highest performance simply switch base_url/model to Claude/GPT.
"""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent          # .../GAMITagent/app
REPO_DIR = APP_DIR.parent                                  # .../GAMITagent
ENV_PATH = APP_DIR / ".env"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (avoids a hard dependency on python-dotenv; compatible if it is installed)."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv(ENV_PATH)


class Settings:
    """In-memory configuration; the front-end /api/config can temporarily override it (not persisted to disk)."""

    def __init__(self):
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.temperature = float(os.environ.get("GAMIT_AGENT_TEMP", "0.1"))
        self.max_tokens = int(os.environ.get("GAMIT_AGENT_MAXTOK", "2048"))

    def update(self, **kw):
        for k in ("api_key", "base_url", "model"):
            if kw.get(k):
                setattr(self, k, kw[k])
        return self

    def masked(self) -> dict:
        k = self.api_key
        return {
            "api_key": (k[:6] + "…" + k[-4:]) if len(k) > 12 else ("set" if k else ""),
            "base_url": self.base_url,
            "model": self.model,
            "has_key": bool(self.api_key),
        }


settings = Settings()
