import os
from pathlib import Path
from secrets import token_urlsafe

from dotenv import load_dotenv

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default)).expanduser()
    return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


class Config:
    """Application configuration (read from environment / .env)."""

    API_TITLE = "ezLogic API"
    API_VERSION = "0.1.0"

    # OpenRouter (OpenAI-compatible API)
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    OPENROUTER_MODEL = os.getenv(
        "OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free"
    )
    AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "20"))
    # Give up early (asking the model for its best attempt so far, clearly marked
    # unverified) instead of using every one of AGENT_MAX_STEPS on a model that's
    # stuck: after this many check_lean_file/check_lean_snippet failures in a row,
    AGENT_MAX_FAILED_CHECKS = int(os.getenv("AGENT_MAX_FAILED_CHECKS", "4"))
    # ... or after this long, whichever comes first.
    AGENT_TIMEOUT = float(os.getenv("AGENT_TIMEOUT", "300"))
    # Per OpenRouter call. A stuck free-tier model plus the default client retries
    # could otherwise each silently cost up to a couple of minutes.
    LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "90"))

    # Sandbox directory the agent is allowed to read/write
    WORKSPACE_DIR = _path("WORKSPACE_DIR", "./workspace")

    # Lean CLI (installed via elan)
    LEAN_PATH = os.getenv("LEAN_PATH", "lean")
    LAKE_PATH = os.getenv("LAKE_PATH", "lake")
    LEAN_TIMEOUT = float(os.getenv("LEAN_TIMEOUT", "120"))

    # lean-interact (REPL used for quick snippet checks)
    LEAN_VERSION = os.getenv("LEAN_VERSION") or None  # e.g. "v4.19.0"; None = latest
    LEAN_INTERACT_CACHE = _path("LEAN_INTERACT_CACHE", "./.lean_cache")
    # Safety ceiling for starting the REPL and loading Mathlib into it the first time
    # (can take a minute or more); LEAN_TIMEOUT applies to each check after that.
    LEAN_STARTUP_TIMEOUT = float(os.getenv("LEAN_STARTUP_TIMEOUT", "180"))
    # lean-interact's AutoLeanServer kills and restarts the Lean process whenever
    # *system-wide* memory usage crosses this fraction (checked before every single
    # request, not just while the REPL itself is heavy). On a machine that's
    # otherwise often near this threshold, that means the Mathlib-loaded
    # environment check_lean_snippet relies on gets rebuilt (replayed) far more
    # often than intended, defeating the point of reusing it. Raise this (e.g. to
    # 0.95) on a memory-constrained dev machine; keep it lower on a shared/
    # production server where an OOM from a runaway Lean process is the bigger risk.
    LEAN_MAX_TOTAL_MEMORY = float(os.getenv("LEAN_MAX_TOTAL_MEMORY", "0.9"))

    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

    GUEST_JWT_SECRET = os.getenv("GUEST_JWT_SECRET") or token_urlsafe(32)
    GUEST_COOKIE_SECURE = os.getenv("GUEST_COOKIE_SECURE", "false").lower() == "true"


Config.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
