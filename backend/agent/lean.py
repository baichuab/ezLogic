"""Lean verification.

Two modes:
  * check_file    - runs the `lean` CLI (or `lake env lean` inside a Lake project)
                    on a file in the workspace. Best for full proofs.
  * check_snippet - sends a short code snippet to a Lean REPL via lean-interact.
                    Best for quick experiments; the REPL is started lazily and reused.
"""

import asyncio
import shutil
import threading
from dataclasses import asdict, dataclass, field

from config import Config

from .workspace import Workspace


@dataclass
class LeanResult:
    ok: bool  # True when Lean reports no errors
    messages: list[dict] = field(default_factory=list)
    output: str = ""
    error: str | None = None  # tooling failure (Lean missing, timeout, ...)

    def to_dict(self) -> dict:
        return asdict(self)


LEAN_MISSING = (
    "Lean is not installed or not on PATH. Install it with elan: "
    "https://lean-lang.org/lean4/doc/setup.html"
)


async def check_file(workspace: Workspace, path: str) -> LeanResult:
    target = workspace.resolve(path)
    if not target.is_file():
        return LeanResult(ok=False, error=f"No such file: {path}")

    # Use Lake when the workspace is a Lake project so imports (e.g. Mathlib) resolve.
    is_lake = any((workspace.root / f).exists() for f in ("lakefile.lean", "lakefile.toml"))
    if is_lake:
        if not shutil.which(Config.LAKE_PATH):
            return LeanResult(ok=False, error=LEAN_MISSING)
        cmd = [Config.LAKE_PATH, "env", Config.LEAN_PATH, workspace.rel(target)]
    else:
        if not shutil.which(Config.LEAN_PATH):
            return LeanResult(ok=False, error=LEAN_MISSING)
        cmd = [Config.LEAN_PATH, workspace.rel(target)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=workspace.root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=Config.LEAN_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return LeanResult(ok=False, error=f"Lean timed out after {Config.LEAN_TIMEOUT}s")

    output = stdout.decode(errors="replace")
    # `sorry` only produces a warning, but the proof is not complete.
    ok = proc.returncode == 0 and "declaration uses 'sorry'" not in output
    return LeanResult(ok=ok, output=output)


# --- lean-interact REPL -----------------------------------------------------------

_server = None
_server_lock = threading.Lock()
_run_lock = threading.Lock()  # the REPL handles one command at a time


def _get_server():
    """Start (once) and return a lean-interact REPL server. Blocking."""
    global _server
    with _server_lock:
        if _server is None:
            from lean_interact import AutoLeanServer, LeanREPLConfig

            repl_config = LeanREPLConfig(
                lean_version=Config.LEAN_VERSION,
                cache_dir=Config.LEAN_INTERACT_CACHE,
                lake_path=Config.LAKE_PATH,
            )
            _server = AutoLeanServer(repl_config)
        return _server


def run_command(command, timeout: float | None = None):
    """Send a `lean_interact` command to the shared REPL. Blocking; calls are serialised.

    Raises on REPL startup/build failures; returns the response or a `LeanError`.
    """
    server = _get_server()
    with _run_lock:
        return server.run(command, timeout=timeout or Config.LEAN_TIMEOUT)


def _check_snippet_sync(code: str) -> LeanResult:
    from lean_interact import Command
    from lean_interact.interface import LeanError

    if not shutil.which(Config.LAKE_PATH):
        return LeanResult(ok=False, error=LEAN_MISSING)
    try:
        response = run_command(Command(cmd=code))
    except Exception as e:  # REPL build/startup failures, timeouts, ...
        return LeanResult(ok=False, error=f"{type(e).__name__}: {e}")

    if isinstance(response, LeanError):
        return LeanResult(ok=False, error=response.message)

    messages = [
        {
            "severity": m.severity,
            "line": m.start_pos.line if m.start_pos else None,
            "column": m.start_pos.column if m.start_pos else None,
            "message": m.data,
        }
        for m in response.messages
    ]
    # Count `sorry` as not proven.
    for s in response.sorries:
        messages.append(
            {
                "severity": "warning",
                "line": s.start_pos.line if s.start_pos else None,
                "column": s.start_pos.column if s.start_pos else None,
                "message": f"unsolved goal (sorry): {s.goal}",
            }
        )
    ok = not response.has_errors() and not response.sorries
    return LeanResult(ok=ok, messages=messages)


async def check_snippet(code: str) -> LeanResult:
    return await asyncio.to_thread(_check_snippet_sync, code)
