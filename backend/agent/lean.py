"""Lean verification.

Two modes:
  * check_file    - runs the `lean` CLI (or `lake env lean` inside a Lake project)
                    on a file in the workspace. Best for full proofs.
  * check_snippet - sends a short code snippet to a Lean REPL via lean-interact.
                    Best for quick experiments; the REPL is started lazily and reused.
"""

import asyncio
import logging
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field

from config import Config

from .workspace import Workspace

log = logging.getLogger(__name__)


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

    log.info("check_lean_file start path=%s is_lake=%s", path, is_lake)
    t0 = time.monotonic()
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
        await proc.wait()  # reap the killed process so it doesn't linger as a zombie
        log.warning("check_lean_file timeout path=%s after %.1fs", path, time.monotonic() - t0)
        return LeanResult(ok=False, error=f"Lean timed out after {Config.LEAN_TIMEOUT}s")

    output = stdout.decode(errors="replace")
    # `sorry` only produces a warning, but the proof is not complete.
    ok = proc.returncode == 0 and "declaration uses 'sorry'" not in output
    log.info("check_lean_file done path=%s ok=%s elapsed=%.1fs", path, ok, time.monotonic() - t0)
    return LeanResult(ok=ok, output=output)


# --- lean-interact REPL -----------------------------------------------------------
#
# The REPL process and the "Mathlib already imported" environment it builds are both
# reused across every check_lean_snippet call (and across requests/users): building
# them is slow -- starting the REPL and loading Mathlib the first time can take a
# minute or more -- but once done, a snippet that reuses that environment typically
# checks in well under a second instead of ~40s for a fresh `import Mathlib`.

_server = None
_server_lock = threading.Lock()

_mathlib_env: int | None = None
_env_lock = threading.Lock()


def _is_lake_project() -> bool:
    root = Config.WORKSPACE_DIR
    return any((root / f).exists() for f in ("lakefile.lean", "lakefile.toml"))


def _get_server():
    """Start (once) and return a lean-interact REPL server. Blocking."""
    global _server
    with _server_lock:
        if _server is None:
            from lean_interact import AutoLeanServer, LeanREPLConfig, LocalProject

            root = Config.WORKSPACE_DIR
            if _is_lake_project():
                # Run snippets inside the workspace's Lake project so they get the same
                # toolchain and Mathlib as check_file. lean-interact reads the Lean
                # version from the project and rejects an explicit lean_version.
                repl_config = LeanREPLConfig(
                    project=LocalProject(directory=str(root), lake_path=Config.LAKE_PATH),
                    cache_dir=Config.LEAN_INTERACT_CACHE,
                    lake_path=Config.LAKE_PATH,
                )
            else:
                repl_config = LeanREPLConfig(
                    lean_version=Config.LEAN_VERSION,
                    cache_dir=Config.LEAN_INTERACT_CACHE,
                    lake_path=Config.LAKE_PATH,
                )
            log.info("starting lean-interact REPL (first use; building/downloading can take a while)")
            t0 = time.monotonic()
            _server = AutoLeanServer(repl_config, max_total_memory=Config.LEAN_MAX_TOTAL_MEMORY)
            log.info("lean-interact REPL ready in %.1fs", time.monotonic() - t0)
        return _server


def _get_base_env(server) -> int | None:
    """Environment id with Mathlib already imported, built once and reused. `None`
    when the workspace isn't a Lake project (no Mathlib available to preload)."""
    global _mathlib_env
    if not _is_lake_project():
        return None
    with _env_lock:
        if _mathlib_env is None:
            from lean_interact import Command
            from lean_interact.interface import LeanError

            log.info("loading Mathlib into the REPL (first snippet check; can take ~30-60s)")
            t0 = time.monotonic()
            response = server.run(
                Command(cmd="import Mathlib"),
                timeout=Config.LEAN_STARTUP_TIMEOUT,
                add_to_session_cache=True,
            )
            if isinstance(response, LeanError):
                raise RuntimeError(f"Failed to load Mathlib into the REPL: {response.message}")
            _mathlib_env = response.env
            log.info("Mathlib loaded in %.1fs (env=%s)", time.monotonic() - t0, _mathlib_env)
        return _mathlib_env


_IMPORT_LINE = re.compile(r"^[ \t]*import\s+\S.*$", re.MULTILINE)


def _without_imports(code: str) -> str:
    """Blank out every `import ...` line, wherever it appears.

    Once a command runs inside an existing environment (`env=...`), Lean rejects an
    `import` anywhere in it, even after a comment -- not just outside a leading
    block (https://github.com/augustepoiroux/LeanInteract: "invalid 'import'
    command, it must be used in the beginning of the file"). The snippet already
    has Mathlib via that environment, so the model's own import line (if it wrote
    one, as the system prompt tells it to for files) is redundant anyway.

    Each import line is replaced with an empty line, rather than removed, so every
    other line keeps its original line number -- Lean's error messages (and the
    step's own logged `target=`) still point at the line the model actually wrote.
    """
    return _IMPORT_LINE.sub("", code)


def _check_snippet_sync(code: str) -> LeanResult:
    from lean_interact import Command
    from lean_interact.interface import LeanError

    if not shutil.which(Config.LAKE_PATH):
        return LeanResult(ok=False, error=LEAN_MISSING)

    t0 = time.monotonic()
    try:
        server = _get_server()
        base_env = _get_base_env(server)  # may legitimately take ~30-60s on the very first call
        body = _without_imports(code) if base_env is not None else code
        t_run = time.monotonic()
        response = server.run(Command(cmd=body, env=base_env), timeout=Config.LEAN_TIMEOUT)
        run_elapsed = time.monotonic() - t_run
    except Exception as e:  # REPL build/startup failures, timeouts, ...
        log.warning("check_lean_snippet failed after %.1fs: %s: %s", time.monotonic() - t0, type(e).__name__, e)
        return LeanResult(ok=False, error=f"{type(e).__name__}: {e}")

    if isinstance(response, LeanError):
        log.info("check_lean_snippet rejected after %.1fs: %s", time.monotonic() - t0, response.message)
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
    if base_env is not None and run_elapsed > 10:
        # Mathlib was supposedly already loaded by _get_base_env (that cost is
        # deliberately excluded from run_elapsed), so running one small snippet
        # against it should take well under a second. This long instead almost
        # always means lean-interact silently killed and restarted the Lean process
        # (its AutoLeanServer does this on its own, see Config.LEAN_MAX_TOTAL_MEMORY)
        # and had to replay the cached environment from scratch -- i.e. re-import
        # Mathlib -- before it could run this snippet.
        log.warning(
            "check_lean_snippet's own Lean call took %.1fs despite reusing a loaded "
            "environment; the Lean REPL likely restarted under memory pressure and "
            "replayed Mathlib from scratch (see LEAN_MAX_TOTAL_MEMORY in backend/.env.example)",
            run_elapsed,
        )
    log.info("check_lean_snippet done ok=%s elapsed=%.1fs", ok, time.monotonic() - t0)
    return LeanResult(ok=ok, messages=messages)


async def check_snippet(code: str) -> LeanResult:
    try:
        # The inner lean-interact `timeout=` (LEAN_TIMEOUT, in _check_snippet_sync)
        # covers the normal per-snippet case once the REPL is warm. This outer bound
        # is just a safety net for the rare case of the REPL/Mathlib build itself
        # hanging, which isn't covered by that inner timeout.
        return await asyncio.wait_for(
            asyncio.to_thread(_check_snippet_sync, code), timeout=Config.LEAN_STARTUP_TIMEOUT
        )
    except asyncio.TimeoutError:
        log.warning("check_lean_snippet exceeded the %.0fs safety timeout", Config.LEAN_STARTUP_TIMEOUT)
        return LeanResult(ok=False, error=f"Lean snippet check timed out after {Config.LEAN_STARTUP_TIMEOUT:.0f}s")


async def warm_up() -> None:
    """Best-effort: start the REPL and preload Mathlib ahead of the first real
    request, instead of making whoever sends the first message pay for it. Safe to
    call even when Lean/Lake aren't installed, or the workspace isn't a Lake
    project -- it just does nothing in those cases. Failures aren't fatal: the next
    check_lean_snippet call will simply try again (and report any error normally)."""
    if not shutil.which(Config.LAKE_PATH):
        return
    await asyncio.to_thread(lambda: _get_base_env(_get_server()))
