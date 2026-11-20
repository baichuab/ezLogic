import os
from pathlib import Path

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

    # Sandbox directory the agent is allowed to read/write
    WORKSPACE_DIR = _path("WORKSPACE_DIR", "./workspace")

    # Lean CLI (installed via elan)
    LEAN_PATH = os.getenv("LEAN_PATH", "lean")
    LAKE_PATH = os.getenv("LAKE_PATH", "lake")
    LEAN_TIMEOUT = float(os.getenv("LEAN_TIMEOUT", "120"))

    # lean-interact (REPL used for quick snippet checks)
    LEAN_VERSION = os.getenv("LEAN_VERSION") or None  # e.g. "v4.19.0"; None = latest
    LEAN_INTERACT_CACHE = _path("LEAN_INTERACT_CACHE", "./.lean_cache")

    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


Config.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
