"""Benchmark graph extraction on large generated proofs with small edits (run from backend/).
Needs Lean (`lake` on PATH). See README.md ("Benchmark").

    python -m graph.bench                         # 50 and 200 declarations
    python -m graph.bench --sizes 200 --repeat 3 --out bench.json
    python -m graph.bench --timeouts              # also check what a timeout does to the REPL
    python -m graph.bench --print-source 8        # print a generated file and exit (no Lean)

For each file size it times a rebuild after each kind of edit, from a REPL that has just processed
the unedited file:

- `pipeline`: today's `create_graph_sync` on the shared REPL (lean-interact's incrementality on);
- `incr on` / `incr off`: the source command alone on a separate REPL, Lean's incrementality on
  or off;
- `incr on + other`: like `incr on`, with an unrelated command sent in between, as when other
  users share the REPL.

It also checks what an incremental, declaration-by-declaration design would rely on: positions in
a command continued from a saved state, `namespace`/`variable` carrying over, a saved state after a
restart, and (with `--timeouts`) a timeout.
"""

import argparse
import json
import shutil
import statistics
import sys
import time

from config import Config

PRELUDE = "import Lean\n"
OTHER_COMMAND = "theorem bench_other (n : Nat) : n + 0 = n := by simp"
EDIT_LINE = "  have _bench : True := trivial\n"  # a proof edit that keeps the statement


# --- generated sources (pure Python) ----------------------------------------------------------


def generate(n: int) -> str:
    """A Lean file of `n` declarations, core Lean only: definitions, and theorems proved with
    `simp only`, `have`, `omega` and `induction`. Each theorem's proof starts on its own line."""
    parts = []
    for k in range(n):
        j = k - k % 4  # the definition of this group of four
        match k % 4:
            case 0:
                parts.append(f"def f{k} (n : Nat) : Nat := n + {k}\n")
            case 1:
                parts.append(f"theorem t{k} (n : Nat) : f{j} n + 1 = n + {j} + 1 := by\n  simp only [f{j}]\n")
            case 2:
                parts.append(
                    f"theorem s{k} (a b : Nat) (h : a ≤ b) : a + {k} ≤ b + {k} + 1 := by\n"
                    f"  have h2 : a + {k} ≤ b + {k} := Nat.add_le_add_right h {k}\n  omega\n"
                )
            case 3:
                parts.append(
                    f"theorem i{k} (n : Nat) : 2 * n + {k} = n + n + {k} := by\n"
                    f"  induction n with\n  | zero => simp\n  | succ m ih => omega\n"
                )
    return "\n".join(parts)


def _theorem_lines(source: str) -> list[int]:
    """Indexes of the lines that start a theorem."""
    return [i for i, line in enumerate(source.split("\n")) if line.startswith("theorem ")]


def edits(source: str) -> dict[str, str]:
    """The edits to time, each a small change to `source`."""
    lines = source.split("\n")
    theorems = _theorem_lines(source)

    def proof_edit(theorem_line: int) -> str:  # insert a line at the start of that theorem's proof
        return "\n".join(lines[: theorem_line + 1]) + "\n" + EDIT_LINE + "\n".join(lines[theorem_line + 1 :])

    first_def = next(i for i, line in enumerate(lines) if line.startswith("def "))
    body = lines[first_def].rsplit(":= ", 1)
    def_edit = lines[:first_def] + [f"{body[0]}:= ({body[1]})"] + lines[first_def + 1 :]
    return {
        "no change": source,
        "proof edit, last theorem": proof_edit(theorems[-1]),
        "proof edit, middle theorem": proof_edit(theorems[len(theorems) // 2]),
        "proof edit, first theorem": proof_edit(theorems[0]),
        "def edit, first declaration": "\n".join(def_edit),
    }


# --- timing (needs Lean) ----------------------------------------------------------------------


def _server(incremental: bool):
    from lean_interact import LeanREPLConfig, LeanServer

    config = LeanREPLConfig(
        lean_version=Config.LEAN_VERSION,
        cache_dir=Config.LEAN_INTERACT_CACHE,
        lake_path=Config.LAKE_PATH,
        enable_incremental_optimization=incremental,
    )
    return LeanServer(config)


def _command(source: str, **options):
    from lean_interact import Command

    return Command(cmd=PRELUDE + source, all_tactics=True, declarations=True, **options)


def _timed(run) -> float:
    start = time.perf_counter()
    response = run()
    elapsed = time.perf_counter() - start
    from lean_interact.interface import LeanError

    if isinstance(response, LeanError):
        raise RuntimeError(f"Lean failed: {response.message}")
    return elapsed


def _errors(response) -> list[str]:
    return [m.data for m in getattr(response, "messages", []) if m.severity == "error"]


def time_edits(base: str, edited: dict[str, str], repeat: int, servers: dict) -> dict:
    """Median seconds per (edit, mode). Each sample builds `base` first, then the edit."""
    from graph import create_graph_sync

    def pipeline(source):
        return lambda: create_graph_sync(source)

    def repl(server, source):
        return lambda: server.run(_command(source), timeout=Config.LEAN_TIMEOUT)

    results: dict[str, dict[str, float]] = {}
    for name, source in edited.items():
        row = {}
        for mode in ("pipeline", "incr on", "incr off", "incr on + other"):
            samples = []
            for _ in range(repeat):
                if mode == "pipeline":
                    create_graph_sync(base)
                    samples.append(_timed(pipeline(source)))
                    continue
                server = servers["off" if mode == "incr off" else "on"]
                server.run(_command(base), timeout=Config.LEAN_TIMEOUT)
                if mode == "incr on + other":
                    from lean_interact import Command

                    server.run(Command(cmd=PRELUDE + OTHER_COMMAND), timeout=Config.LEAN_TIMEOUT)
                samples.append(_timed(repl(server, source)))
            row[mode] = statistics.median(samples)
        results[name] = row
    return results


def check_facts(server, timeouts: bool) -> dict:
    """What a declaration-by-declaration design would rely on, as observed."""
    from lean_interact import Command
    from lean_interact.interface import LeanError

    facts = {}
    env0 = server.run(Command(cmd="import Lean")).env

    r = server.run(Command(cmd="\ntheorem a : 1 = 1 := by\n  rfl", env=env0, all_tactics=True))
    facts["tactic line in a continued command (1-based in that command: 3)"] = r.tactics[0].start_pos.line

    r1 = server.run(Command(cmd="namespace Foo\nvariable (k : Nat)", env=env0))
    r2 = server.run(Command(cmd="theorem bar : k = k := rfl", env=r1.env, declarations=True))
    facts["namespace/variable carry over (name, errors)"] = (
        [d.full_name for d in r2.declarations],
        _errors(r2),
    )

    # After a restart, state ids start again from 0. Create states until the old id exists again,
    # then use it: an error means stale ids are caught; "accepted" means they silently point to a
    # different state.
    facts["memory MB before restart"] = round(server.get_memory_usage())
    old = r2.env
    server.restart()
    env = server.run(Command(cmd="import Lean")).env
    while env < old and env < 5000:
        env = server.run(Command(cmd="#check 1", env=env)).env
    stale = server.run(Command(cmd="#check bar", env=old))
    facts["old state id after restart, once that id exists again"] = (
        f"LeanError: {stale.message}" if isinstance(stale, LeanError) else f"accepted, errors: {_errors(stale)}"
    )

    if timeouts:
        env0 = server.run(Command(cmd="import Lean")).env
        slow = "#eval Id.run do\n  let mut s := 0\n  for i in [0:200000000] do s := s + i\n  return s"
        try:
            server.run(Command(cmd=slow, env=env0), timeout=2)
            facts["timeout"] = "finished within 2 s (no timeout)"
        except Exception as e:  # noqa: BLE001 - reporting whatever lean-interact raises
            after = server.run(Command(cmd="#check Nat", env=env0)) if server.is_alive() else None
            facts["timeout"] = {
                "raised": type(e).__name__,
                "server alive": server.is_alive(),
                "earlier state still usable": after is not None and not isinstance(after, LeanError),
            }
    return facts


def _table(size: int, results: dict) -> str:
    modes = ["pipeline", "incr on", "incr off", "incr on + other"]
    out = [f"\n{size} declarations (seconds, median)", f"{'edit':<30}" + "".join(f"{m:>18}" for m in modes)]
    for name, row in results.items():
        out.append(f"{name:<30}" + "".join(f"{row[m]:>18.2f}" for m in modes))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m graph.bench")
    parser.add_argument("--sizes", type=int, nargs="+", default=[50, 200], help="declarations per file")
    parser.add_argument("--repeat", type=int, default=3, help="samples per measurement (median)")
    parser.add_argument("--timeouts", action="store_true", help="also check what a timeout does")
    parser.add_argument("--out", help="also write the results as JSON to this path")
    parser.add_argument("--print-source", type=int, metavar="N", help="print a generated file of N declarations")
    args = parser.parse_args(argv)

    if args.print_source:
        print(generate(args.print_source))
        return
    if not shutil.which(Config.LAKE_PATH):
        sys.exit("Lean is not installed: `lake` is not on PATH (see the main README).")

    report = {"sizes": {}}
    print("Starting REPLs (the first run builds the Lean REPL, which takes a few minutes)...")
    servers = {"on": _server(True), "off": _server(False)}
    for size in args.sizes:
        base = generate(size)
        check = servers["on"].run(_command(base))
        if errors := _errors(check):
            sys.exit(f"The generated file has errors (fix generate()): {errors[:3]}")
        cold_server = _server(True)
        cold = _timed(lambda: cold_server.run(_command(base), timeout=Config.LEAN_TIMEOUT))
        cold_server.kill()
        results = time_edits(base, edits(base), args.repeat, servers)
        report["sizes"][size] = {
            "cold build, fresh REPL": cold,
            "edits": results,
            "memory MB, incr on REPL": round(servers["on"].get_memory_usage()),
        }
        print(f"\ncold build of {size} declarations on a fresh REPL: {cold:.2f} s")
        print(_table(size, results))
    report["facts"] = check_facts(servers["on"], args.timeouts)
    print("\nFacts for a declaration-by-declaration design:")
    for key, value in report["facts"].items():
        print(f"  {key}: {value}")
    for server in servers.values():
        server.kill()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, ensure_ascii=False)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
