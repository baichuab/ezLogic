"""Run Lean on a proof and collect the raw data the graph is built from.

One REPL command does all the work. The source is sent as

    import Lean          <- gives the metaprogram access to Lean's API (shifts lines by 1)
    <user source>
    <metaprogram>        <- prints every constant the source defined, with its dependencies

with `all_tactics` (each tactic, its position, the goal before it and the constants it used) and
`declarations` (each declaration's name, kind and range). Positions are shifted back so they
refer to the user's source.

A failed declaration is stored as `sorry`, so its tactics can use lemmas that the metaprogram
never sees. Those are classified with a second, cheap command that only imports the same headers.
"""

import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field

from agent import lean
from config import Config

log = logging.getLogger(__name__)

MARKER = "EZLOGIC_GRAPH "
PRELUDE = "import Lean\n"
LINE_SHIFT = PRELUDE.count("\n")

# Prints {"lean_version", "locals": [{name, kind, uses}], "constants": [{name, canonical, kind,
# statement}]}. `locals` are constants defined after the imports (the user's declarations plus
# auxiliary ones Lean generates: match_1, proof_1, structure projections, ...). `constants`
# classifies each imported constant those use, plus the names in NAMES. `canonical` drops
# internal name components, so `Nat.foo._simp_1` maps to the lemma `Nat.foo`.
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


@dataclass
class Span:
    """A source range. Lines are 1-based, columns 0-based (in characters)."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int

    @property
    def start(self) -> tuple[int, int]:
        return (self.start_line, self.start_col)

    @property
    def end(self) -> tuple[int, int]:
        return (self.end_line, self.end_col)

    def contains(self, other: "Span") -> bool:
        return self.start <= other.start and other.end <= self.end

    def contains_pos(self, pos: tuple[int, int]) -> bool:
        return self.start <= pos < self.end or pos == self.start


@dataclass
class Declaration:
    name: str  # full name; "_example" for examples
    kind: str  # theorem, definition, structure, instance, example, ...
    span: Span
    statement: str | None  # pretty-printed type, when the declaration has one


@dataclass
class Tactic:
    span: Span
    text: str  # pretty-printed by Lean; may be "<failed to pretty print>"
    goals: str  # goal state before the tactic runs
    used_constants: list[str]


@dataclass
class Message:
    severity: str  # error, warning, info
    span: Span
    text: str


@dataclass
class LocalConstant:
    name: str
    kind: str
    uses: list[str]


@dataclass
class ConstantInfo:
    name: str
    canonical: str
    kind: str  # theorem, definition, projection, instance, ... or "unknown"
    statement: str | None = None


@dataclass
class Extraction:
    declarations: list[Declaration]
    tactics: list[Tactic]
    messages: list[Message]
    # None when the metaprogram produced no output (e.g. the source left a comment unclosed)
    local_constants: dict[str, LocalConstant] | None
    constants: dict[str, ConstantInfo] = field(default_factory=dict)
    lean_version: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Extraction":
        locals_ = d.get("local_constants")
        return cls(
            declarations=[Declaration(**{**x, "span": Span(**x["span"])}) for x in d["declarations"]],
            tactics=[Tactic(**{**x, "span": Span(**x["span"])}) for x in d["tactics"]],
            messages=[Message(**{**x, "span": Span(**x["span"])}) for x in d["messages"]],
            local_constants=None
            if locals_ is None
            else {k: LocalConstant(**v) for k, v in locals_.items()},
            constants={k: ConstantInfo(**v) for k, v in d.get("constants", {}).items()},
            lean_version=d.get("lean_version"),
        )


def _lean_strings(xs) -> str:
    # JSON string escapes are valid Lean string literal escapes.
    return ", ".join(json.dumps(x, ensure_ascii=False) for x in xs)


def _metaprogram(names: list[str], include_locals: bool) -> str:
    return (
        _META.replace("NAMES", _lean_strings(names))
        .replace("INCLUDE_LOCALS", "true" if include_locals else "false")
        .replace("MARKER", MARKER)
    )


_HEADER_LINE = re.compile(r"\s*(--.*)?$|\s*(public\s+|meta\s+)*import\s")


def import_header(source: str) -> str:
    """The leading `import` lines of a source file (blank lines and line comments allowed)."""
    lines = []
    for line in source.splitlines():
        if not _HEADER_LINE.match(line):
            break
        lines.append(line)
    return "\n".join(lines)


def _pos(p) -> tuple[int, int]:
    return (p.line - LINE_SHIFT, p.column)


def _span(start, end) -> Span:
    s = _pos(start)
    e = _pos(end) if end is not None else s
    return Span(s[0], s[1], e[0], e[1])


def _parse_meta_output(data: str) -> dict:
    return json.loads(data[len(MARKER) :])


def _run(cmd):
    from lean_interact.interface import LeanError

    try:
        response = lean.run_command(cmd)
    except Exception as e:  # REPL build/startup failures, timeouts, ...
        raise ExtractionError(f"{type(e).__name__}: {e}") from e
    if isinstance(response, LeanError):
        raise ExtractionError(response.message)
    return response


def extract(source: str) -> Extraction:
    """Elaborate `source` with Lean and collect declarations, tactics and dependencies. Blocking."""
    from lean_interact import Command

    if not shutil.which(Config.LAKE_PATH):
        raise ExtractionError(lean.LEAN_MISSING)

    n_lines = source.count("\n") + 1
    response = _run(
        Command(
            cmd=PRELUDE + source + "\n\n" + _metaprogram([], include_locals=True),
            all_tactics=True,
            declarations=True,
        )
    )

    def in_source(span: Span) -> bool:
        return 1 <= span.start_line <= n_lines

    meta = None
    messages = []
    for m in response.messages:
        if m.data.startswith(MARKER):
            meta = _parse_meta_output(m.data)
            continue
        span = _span(m.start_pos, m.end_pos)
        if span.start_line < 1:  # reported on the `import Lean` line
            span = Span(1, 0, 1, 0)
        if in_source(span):
            messages.append(Message(severity=m.severity, span=span, text=m.data))
        else:
            log.warning("graph metaprogram message: %s: %s", m.severity, m.data)
    if meta is None:
        log.warning("graph metaprogram produced no output; declaration dependencies are unavailable")

    declarations = []
    for d in response.declarations:
        span = _span(d.range.start, d.range.finish)
        if not in_source(span):
            continue
        statement = d.type.pp if d.type is not None else None
        declarations.append(Declaration(name=d.full_name, kind=d.kind, span=span, statement=statement))

    tactics = []
    for t in response.tactics:
        span = _span(t.start_pos, t.end_pos)
        if in_source(span):
            tactics.append(
                Tactic(span=span, text=t.tactic, goals=t.goals, used_constants=list(t.used_constants))
            )

    extraction = Extraction(
        declarations=declarations,
        tactics=tactics,
        messages=messages,
        local_constants=None
        if meta is None
        else {x["name"]: LocalConstant(**x) for x in meta["locals"]},
        constants={} if meta is None else {x["name"]: ConstantInfo(**x) for x in meta["constants"]},
        lean_version=None if meta is None else meta["lean_version"],
    )

    # Classify tactic constants the first pass did not see (used inside failed declarations).
    known = set(extraction.constants) | set(extraction.local_constants or ())
    missing = sorted({c for t in tactics for c in t.used_constants} - known)
    if missing:
        header = import_header(source)
        response = _run(Command(cmd=PRELUDE + header + "\n\n" + _metaprogram(missing, False)))
        for m in response.messages:
            if m.data.startswith(MARKER):
                for x in _parse_meta_output(m.data)["constants"]:
                    extraction.constants[x["name"]] = ConstantInfo(**x)
                break
        else:
            log.warning("graph constant classification produced no output")

    return extraction
