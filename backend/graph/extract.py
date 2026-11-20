"""Run Lean on a proof and collect what the graph is built from. See README.md."""

import json
import logging
import re
import shutil

from lean_interact import Command
from lean_interact.interface import LeanError, Message, Pos, Range, Tactic
from pydantic import BaseModel

from agent import lean
from config import Config

log = logging.getLogger(__name__)

MARKER = "EZLOGIC_GRAPH "
PRELUDE = "import Lean\n"  # the metaprogram needs Lean's API; shifts every line by one

# Prints MARKER + {"lean_version", "locals": [{name, kind, uses}], "constants": [{name, canonical,
# kind, statement}]}. `locals`: every constant defined after the imports (the user's declarations
# and the auxiliary ones Lean generates for them). `constants`: the imported constants those use,
# plus NAMES. `canonical` drops internal name parts (`Nat.foo._simp_1` -> `Nat.foo`).
_META = r"""

open Lean Meta in
#eval show MetaM Unit from do
  let env ← getEnv
  let strip (n : Name) : Name :=
    let kept := n.components.takeWhile (fun c => !c.isInternal)
    if kept.isEmpty then n else kept.foldl Name.append .anonymous
  let kindOf : ConstantInfo → String
    | .axiomInfo _ => "axiom" | .defnInfo _ => "definition" | .thmInfo _ => "theorem"
    | .opaqueInfo _ => "opaque" | .quotInfo _ => "quot" | .inductInfo _ => "inductive"
    | .ctorInfo _ => "constructor" | .recInfo _ => "recursor"
  let mut refs : NameSet :=
    (#[NAMES] : Array String).foldl (fun s str => (Syntax.decodeNameLit ("`" ++ str)).elim s s.insert) {}
  let mut locals : Array Json := #[]
  if INCLUDE_LOCALS then
    for (n, ci) in env.constants.map₂.toList do
      let used := ci.getUsedConstantsAsSet.toArray
      for m in used do
        if (env.getModuleIdxFor? m).isSome then refs := refs.insert m
      locals := locals.push (Json.mkObj [("name", toJson n.toString), ("kind", toJson (kindOf ci)),
        ("uses", toJson (used.map Name.toString))])
  let mut consts : Array Json := #[]
  for n in refs.toArray do
    let s := strip n
    let (kind, stmt) ← match env.find? s with
      | none => pure ("unknown", none)
      | some ci => do
        if env.isProjectionFn s then pure ("projection", none)
        else if isInstanceCore env s then pure ("instance", none)
        else if kindOf ci == "theorem" then
          let pp ← try pure (some (toString (← ppExpr ci.type))) catch _ => pure none
          pure ("theorem", pp)
        else pure (kindOf ci, none)
    consts := consts.push (Json.mkObj [("name", toJson n.toString), ("canonical", toJson s.toString),
      ("kind", toJson kind), ("statement", toJson stmt)])
  IO.println ("MARKER" ++ (Json.mkObj [("lean_version", toJson Lean.versionString),
    ("locals", Json.arr locals), ("constants", Json.arr consts)]).compress)
"""


class ExtractionError(Exception):
    """Lean could not be run (not installed, REPL failure, timeout, ...)."""


class Declaration(BaseModel):
    name: str  # full name; "_example" for examples
    kind: str  # theorem, definition, structure, instance, example, ...
    range: Range
    statement: str | None = None  # pretty-printed type


class LocalConstant(BaseModel):
    name: str
    kind: str
    uses: list[str]


class ConstantInfo(BaseModel):
    name: str
    canonical: str
    kind: str  # theorem, definition, projection, instance, ... or "unknown"
    statement: str | None = None


class Extraction(BaseModel):
    """Lean's output for one source. Positions are as Lean reported them: subtract `line_offset`
    to get lines in the submitted source."""

    line_offset: int = PRELUDE.count("\n")
    declarations: list[Declaration]
    tactics: list[Tactic]
    messages: list[Message]
    local_constants: dict[str, LocalConstant] | None  # None if the metaprogram did not run
    constants: dict[str, ConstantInfo] = {}
    lean_version: str | None = None


def _metaprogram(names: list[str], include_locals: bool) -> str:
    # JSON string escapes are valid Lean string escapes.
    return (
        _META.replace("NAMES", ", ".join(json.dumps(n, ensure_ascii=False) for n in names))
        .replace("INCLUDE_LOCALS", "true" if include_locals else "false")
        .replace("MARKER", MARKER)
    )


def import_header(source: str) -> str:
    """The leading `import` lines of a source (blank lines and `--` comments allowed)."""
    header = []
    for line in source.splitlines():
        if not re.match(r"\s*(--.*)?$|\s*(public\s+|meta\s+)*import\s", line):
            break
        header.append(line)
    return "\n".join(header)


def _run(cmd: Command):
    try:
        response = lean.run_command(cmd)
    except Exception as e:  # REPL build/startup failures, timeouts, ...
        raise ExtractionError(f"{type(e).__name__}: {e}") from e
    if isinstance(response, LeanError):
        raise ExtractionError(response.message)
    return response


def _meta_output(messages: list[Message]) -> dict | None:
    return next((json.loads(m.data[len(MARKER) :]) for m in messages if m.data.startswith(MARKER)), None)


def source_messages(messages: list[Message], last_line: int, meta_ran: bool) -> list[Message]:
    """Lean's messages about the submitted source (whose last line is `last_line`, in Lean's
    numbering). If the metaprogram did not run, the source broke it (e.g. an unclosed comment
    swallowed it), so errors reported past the end are kept, moved to the source's last line."""
    end = Pos(line=last_line, column=0)
    out = []
    for m in messages:
        if m.data.startswith(MARKER):
            continue
        if m.start_pos.line <= last_line:
            out.append(m)
        elif not meta_ran and m.severity == "error":
            out.append(m.model_copy(update={"start_pos": end, "end_pos": end}))
    return out


def extract(source: str) -> Extraction:
    """Elaborate `source` and collect declarations, tactics and dependencies. Blocking."""
    if not shutil.which(Config.LAKE_PATH):
        raise ExtractionError(lean.LEAN_MISSING)

    offset = PRELUDE.count("\n")
    last_line = source.count("\n") + 1 + offset
    response = _run(
        Command(
            cmd=PRELUDE + source + "\n\n" + _metaprogram([], include_locals=True),
            all_tactics=True,
            declarations=True,
        )
    )
    meta = _meta_output(response.messages)
    if meta is None:
        log.warning("graph metaprogram produced no output; declaration dependencies unavailable")

    ex = Extraction(
        declarations=[
            Declaration(name=d.full_name, kind=d.kind, range=d.range, statement=d.type and d.type.pp)
            for d in response.declarations
            if d.range.start.line <= last_line
        ],
        tactics=[t for t in response.tactics if t.start_pos.line <= last_line],
        messages=source_messages(response.messages, last_line, meta_ran=meta is not None),
        local_constants=meta and {x["name"]: x for x in meta["locals"]},
        constants=meta and {x["name"]: x for x in meta["constants"]} or {},
        lean_version=meta and meta["lean_version"],
    )

    # A failed declaration is stored as `sorry`, so lemmas its tactics used are not in `constants`
    # yet. Classify them with a second command that only repeats the imports.
    known = set(ex.constants) | set(ex.local_constants or ())
    missing = sorted({c for t in ex.tactics for c in t.used_constants} - known)
    if missing:
        response = _run(
            Command(cmd=PRELUDE + import_header(source) + "\n\n" + _metaprogram(missing, False))
        )
        for x in (_meta_output(response.messages) or {}).get("constants", []):
            ex.constants[x["name"]] = ConstantInfo(**x)
    return ex
