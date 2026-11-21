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

    # Anthropic, via its OpenAI-compatible endpoint
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_BASE_URL = os.getenv(
        "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/"
    )
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "20"))
    # Give up early (asking the model for its best attempt so far, clearly marked
    # unverified) instead of using every one of AGENT_MAX_STEPS on a model that's
    # stuck: after this many check_lean_file/check_lean_snippet failures in a row,
    AGENT_MAX_FAILED_CHECKS = int(os.getenv("AGENT_MAX_FAILED_CHECKS", "4"))
    # ... or after this long, whichever comes first.
    AGENT_TIMEOUT = float(os.getenv("AGENT_TIMEOUT", "300"))
    # Per LLM call. A stuck model plus the default client retries could otherwise
    # each silently cost up to a couple of minutes.
    LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "90"))

    # Explaining agent (agent/explainer.py): turns the writer's final Lean into
    # step cards that point at line ranges. Empty model = same as the writer's.
    ANTHROPIC_EXPLAIN_MODEL = os.getenv("ANTHROPIC_EXPLAIN_MODEL") or None
    EXPLAIN_TIMEOUT = float(os.getenv("EXPLAIN_TIMEOUT", "60"))

    # Sandbox directory the agent is allowed to read/write
    WORKSPACE_DIR = _path("WORKSPACE_DIR", "./workspace")

    # Lake (installed via elan); lean-interact uses it to build and run the REPL
    LAKE_PATH = os.getenv("LAKE_PATH", "lake")
    LEAN_TIMEOUT = float(os.getenv("LEAN_TIMEOUT", "120"))

    # lean-interact (REPL used for quick snippet checks)
    LEAN_VERSION = os.getenv("LEAN_VERSION") or None  # e.g. "v4.19.0"; None = latest
    LEAN_INTERACT_CACHE = _path("LEAN_INTERACT_CACHE", "./.lean_cache")
    # REPL repository lean-interact builds. The official repo tags every Lean
    # release (e.g. `v4.37.0-rc1`); lean-interact's default fork often lags behind
    # new Mathlib toolchains. LEAN_REPL_REV empty = the tag matching the
    # workspace's `lean-toolchain`.
    LEAN_REPL_GIT = os.getenv(
        "LEAN_REPL_GIT", "https://github.com/leanprover-community/repl"
    )
    LEAN_REPL_REV = os.getenv("LEAN_REPL_REV") or None
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
    # The built frontend (`npm run build` output). When it holds an index.html, main.py
    # serves the site itself, at the same origin as /api (the hosted image does this).
    STATIC_DIR = _path("STATIC_DIR", "./static")

    GUEST_JWT_SECRET = os.getenv("GUEST_JWT_SECRET") or token_urlsafe(32)
    GUEST_COOKIE_SECURE = os.getenv("GUEST_COOKIE_SECURE", "false").lower() == "true"


Config.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
