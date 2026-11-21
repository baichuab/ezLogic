"""Run Lean and collect the raw lemma-dependency data. See README.md.

Everything that needs Lean's environment happens in one metaprogram (`_META`), appended to the
source and run in the same REPL command on top of the preloaded Mathlib environment
(`agent.lean.run_raw`). It walks theorem -> theorem links breadth-first with
`ConstantInfo.getUsedConstantsAsSet`, and prints the result as one JSON info message.
`build.py` turns that output into a `LemmaGraph`.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from lean_interact.interface import Pos

from agent import lean

log = logging.getLogger(__name__)

MARKER = "EZLOGIC_LEMMA_GRAPH "

# Theorems Lean's elaborator and tactics insert as plumbing. They would be children of almost every
# node, so they are dropped (not expanded). Adapted from origin/proof-graph-v2's graph/build.py.
PLUMBING = sorted(
    """
    Eq.mpr Eq.mp Eq.trans Eq.symm Eq.refl Eq.subst Eq.substr Eq.ndrec Eq.propIntro congr congrArg
    congrFun congrFun' eq_self eq_true eq_false of_eq_true of_eq_false iff_self propext id rfl trivial
    implies_congr forall_congr forall_congr' Decidable.byContradiction Classical.byContradiction
    Not.intro absurd False.elim Iff.rfl Iff.intro HEq.refl cast_eq of_decide_eq_true
    of_decide_eq_false eq_of_heq heq_of_eq Eq.mpr_prop Eq.mpr_not id_eq ne_eq not_false_eq_true
    Bool.true_eq_false Bool.false_eq_true eq_iff_iff iff_true true_iff and_self or_self
    implies_true true_and and_true Nat.rawCast Iff.mp Iff.mpr eq_false' Eq.mp_prop ne_of_beq_false
    ne_eq not_true_eq_false Ne.symm Bool.of_not_eq_true
    """.split()
)
# Name prefixes (whole components) whose theorems are tactic internals, e.g. what `ring`,
# `norm_num`, `omega`, `simp_arith`, `aesop` build their proofs from.
DENY_PREFIXES = [
    "Lean",
    "Mathlib.Tactic",
    "Mathlib.Meta",
    "Std.Tactic",
    "Batteries.Tactic",
    "Aesop",
    "Qq",
    "Nat.Linear",
    "Int.Linear",
    "Std.Sat",
    "noConfusion_of_Nat",  # and its `.aux`: what `decide` / `simp` use to tell constructors apart
]

# `#eval` of a `MetaM` program, appended after the source. `PARAMS` is replaced by a JSON string
# literal (JSON string escapes are valid Lean string escapes). Only iterative loops, no auxiliary
# `def`s: those would become constants of the source's environment, and could pick up the
# source's `variable`s and open namespaces.
#
# Output: MARKER + {"lean_version", "nodes": [...], "axioms": [...]}, where each node is
#   {"id", "kind": "theorem" | "virtual", "local", "class_field", "depth", "truncated", "uses": [ids],
#    "direct_axioms": [...], "axioms": [...] | null, "statement", "module", "range"}
_META = r"""

set_option maxHeartbeats 0 in
open Lean Meta in
#eval show MetaM Unit from do
  let env ← getEnv
  let cfg ← match Json.parse PARAMS with
    | .ok j => pure j
    | .error e => throwError "lemma graph: bad parameters: {e}"
  let toName (s : String) : Name := (Syntax.decodeNameLit ("`" ++ s)).getD s.toName
  let strs (k : String) : Array String := ((cfg.getObjValAs? (Array String) k).toOption).getD #[]
  let maxDepth : Nat := ((cfg.getObjValAs? Nat "depth").toOption).getD 3
  let maxNodes : Nat := ((cfg.getObjValAs? Nat "max_nodes").toOption).getD 300
  let localRoots : Bool := ((cfg.getObjValAs? Bool "local_roots").toOption).getD true
  let withAxioms : Bool := ((cfg.getObjValAs? Bool "axioms").toOption).getD true
  let denyNames : NameSet := (strs "deny_names").foldl (fun s x => s.insert (toName x)) {}
  let denyPrefixes : Array Name := (strs "deny_prefixes").map toName
  let isDenied (n : Name) : Bool := denyNames.contains n || denyPrefixes.any (·.isPrefixOf n)
  -- `foo._simp_1`, `foo.proof_1`, `foo.match_1` -> `foo`. Private names stay as they are.
  let strip (n : Name) : Name :=
    let kept := n.components.takeWhile (fun c => !c.isInternal)
    if kept.isEmpty then n else kept.foldl Name.append .anonymous
  -- Equation lemmas of a definition (`double.eq_1`, `double.eq_def`): not theorems of the proof.
  let isEqnLemma (n : Name) : Bool :=
    match n with
    | .str p s =>
      let generated := s == "eq_def" || s == "eq_unfold" ||
        (s.startsWith "eq_" && s.length > 3 && (s.toList.drop 3).all Char.isDigit)
      generated && (match env.find? p with | some (.defnInfo _) => true | _ => false)
    | _ => false
  -- Recursion machinery Lean generates for an inductive type or predicate (`Nat.le.brecOn`): the
  -- tags `isAuxRecursor` reads are missing for some of them, so go by name as well.
  let isRecursorAux (n : Name) : Bool :=
    isAuxRecursor env n || isNoConfusion env n ||
    match n with
    | .str p s =>
      ["rec", "recOn", "casesOn", "brecOn", "binductionOn", "below", "ibelow", "noConfusion",
        "noConfusionType", "ctorIdx", "induct"].contains s &&
        (match env.find? p with | some (.inductInfo _) => true | _ => false)
    | _ => false
  let isThm (n : Name) : Bool := match env.find? n with | some (.thmInfo _) => true | _ => false
  let sortNames (xs : Array Name) : Array Name := xs.qsort (fun a b => a.toString < b.toString)
  -- The theorems and axioms `raw` refers to, looking through auxiliary constants.
  let neighbours (self : Name) (raw : Array Name) : Array Name × Array Name := Id.run do
    let mut thms : Std.HashSet Name := {}
    let mut axs : Std.HashSet Name := {}
    let mut seen : Std.HashSet Name := {}
    let mut stack := raw
    let mut steps := 0
    while !stack.isEmpty && steps < 200000 do
      steps := steps + 1
      let n := stack.back!
      stack := stack.pop
      if seen.contains n then continue
      seen := seen.insert n
      match env.find? n with
      | none => pure ()
      | some (.axiomInfo _) => axs := axs.insert n
      | some ci =>
        let s := strip n
        if s != n && s != self && isThm s then
          if !isDenied s then thms := thms.insert s
        else if s != n then
          -- an auxiliary lemma with no theorem behind it (or self's own `_proof_1`): look through
          stack := stack ++ ci.getUsedConstantsAsSet.toList.toArray
        else if isEqnLemma n || n == self || isDenied n || isRecursorAux n then pure ()
        else match ci with
          | .thmInfo _ =>
            -- an instance of a Prop-valued class (`Distrib.leftDistribClass`) is plumbing too:
            -- look through it to the lemmas it is built from
            if isInstanceCore env n then stack := stack ++ ci.getUsedConstantsAsSet.toList.toArray
            else thms := thms.insert n
          | _ => pure ()
    return (sortNames thms.toArray, sortNames axs.toArray)
  -- Roots: the source's own theorems (sorted: the map's order is not stable), the theorems to
  -- expand, and virtual roots whose used constants are given (examples, failed proofs).
  let mut roots : Array Name := #[]
  let mut rawOf : Std.HashMap Name (Array Name) := {}
  let mut virtual : Std.HashSet Name := {}
  let mut isLocal : Std.HashSet Name := {}
  if localRoots then
    for (n, ci) in env.constants.map₂.toList do
      let user := (privateToUserName? n).getD n
      if ci matches .thmInfo _ && !user.isInternalDetail && !isEqnLemma n then
        isLocal := isLocal.insert n
    roots := roots ++ sortNames isLocal.toArray
  for s in strs "roots" do
    let n := toName s
    if (env.find? n).isSome && !roots.contains n then roots := roots.push n
  match cfg.getObjVal? "virtual_roots" with
  | .ok (.arr vs) =>
    for v in vs do
      let id := (v.getObjValAs? String "id").toOption.getD ""
      let uses := ((v.getObjValAs? (Array String) "uses").toOption.getD #[]).map toName
      if id.isEmpty then continue
      let n := Name.mkSimple id  -- "example@14": one component, not a name to parse
      rawOf := rawOf.insert n uses
      if env.find? n |>.isNone then virtual := virtual.insert n
      if !roots.contains n then roots := roots.push n
  | _ => pure ()
  -- Breadth-first search over theorem -> theorem links.
  let mut order : Array Name := #[]
  let mut depthOf : Std.HashMap Name Nat := {}
  let mut usesOf : Std.HashMap Name (Array Name) := {}
  let mut directAx : Std.HashMap Name (Array Name) := {}
  let mut truncated : Std.HashSet Name := {}
  for r in roots do
    order := order.push r
    depthOf := depthOf.insert r 0
  let mut i := 0
  while i < order.size do
    let n := order[i]!
    i := i + 1
    let d := depthOf.getD n 0
    let raw := match rawOf.get? n with
      | some r => r
      | none => match env.find? n with
        | some ci => ci.getUsedConstantsAsSet.toList.toArray
        | none => #[]
    let (thms, axs) := neighbours n raw
    directAx := directAx.insert n axs
    if thms.isEmpty then continue
    let fresh := thms.filter (fun m => !depthOf.contains m)
    -- Roots are always expanded, so the source's own lemmas always show their direct dependencies.
    if d > 0 && (d >= maxDepth || order.size + fresh.size > maxNodes) then
      truncated := truncated.insert n
      usesOf := usesOf.insert n (thms.filter (fun m => depthOf.contains m))
      continue
    usesOf := usesOf.insert n thms
    for m in fresh do
      order := order.push m
      depthOf := depthOf.insert m (d + 1)
  -- Describe each node.
  let moduleOf (n : Name) : Json :=
    match env.getModuleIdxFor? n with
    | some idx => match env.header.moduleNames[idx.toNat]? with
      | some m => toJson m.toString
      | none => Json.null
    | none => Json.null
  let names (xs : Array Name) : Json := toJson (xs.map Name.toString)
  let mut allAxioms : Std.HashSet Name := {}
  let mut nodes : Array Json := #[]
  for n in order do
    let direct := directAx.getD n #[]
    let mut axioms : Json := Json.null
    if withAxioms then
      let mut ax : Std.HashSet Name := {}
      if virtual.contains n then
        for a in direct do ax := ax.insert a
        for m in usesOf.getD n #[] do
          for a in ← collectAxioms m do ax := ax.insert a
      else
        for a in ← collectAxioms n do ax := ax.insert a
      let sorted := sortNames ax.toArray
      for a in sorted do allAxioms := allAxioms.insert a
      axioms := names sorted
    for a in direct do allAxioms := allAxioms.insert a
    let (statement, range) ← match env.find? n with
      | none => pure (Json.null, Json.null)
      | some ci => do
        let pp ← try pure (toJson (toString (← ppExpr ci.type))) catch _ => pure Json.null
        let r ← if isLocal.contains n then
            match ← findDeclarationRanges? n with
            | some r => pure (toJson [r.range.pos.line, r.range.endPos.line])
            | none => pure Json.null
          else pure Json.null
        pure (pp, r)
    nodes := nodes.push (Json.mkObj [
      ("id", toJson n.toString),
      ("kind", toJson (if virtual.contains n then "virtual" else "theorem")),
      ("local", toJson (isLocal.contains n)),
      -- a field of a class (`MulOneClass.mul_one`), not of any structure (`And.left`)
      ("class_field", toJson ((env.getProjectionFnInfo? n).any (·.fromClass))),
      ("depth", toJson (depthOf.getD n 0)),
      ("truncated", toJson (truncated.contains n)),
      ("uses", names (usesOf.getD n #[])),
      ("direct_axioms", names direct),
      ("axioms", axioms),
      ("statement", statement),
      ("module", moduleOf n),
      ("range", range)])
  let mut axiomInfo : Array Json := #[]
  for a in sortNames allAxioms.toArray do
    let pp ← match env.find? a with
      | some ci => try pure (toJson (toString (← ppExpr ci.type))) catch _ => pure Json.null
      | none => pure Json.null
    axiomInfo := axiomInfo.push (Json.mkObj [
      ("id", toJson a.toString), ("statement", pp), ("module", moduleOf a)])
  IO.println ("MARKER" ++ (Json.mkObj [
    ("lean_version", toJson Lean.versionString),
    ("nodes", Json.arr nodes),
    ("axioms", Json.arr axiomInfo)]).compress)
"""


@dataclass
class Params:
    depth: int = 3
    max_nodes: int = 300
    local_roots: bool = True  # start from the source's own theorems
    roots: list[str] = field(default_factory=list)  # existing constants to start from (expand)
    virtual_roots: list[dict] = field(default_factory=list)  # [{"id", "uses": [names]}]
    include_core: bool = False  # keep plumbing / tactic-internal theorems
    axioms: bool = True  # run `collectAxioms` for every node

    def to_json(self) -> dict[str, Any]:
        return {
            "depth": self.depth,
            "max_nodes": self.max_nodes,
            "local_roots": self.local_roots,
            "roots": self.roots,
            "virtual_roots": self.virtual_roots,
            "axioms": self.axioms,
            "deny_names": [] if self.include_core else PLUMBING,
            "deny_prefixes": [] if self.include_core else DENY_PREFIXES,
        }


def metaprogram(params: Params) -> str:
    literal = json.dumps(json.dumps(params.to_json(), ensure_ascii=False), ensure_ascii=False)
    return _META.replace("PARAMS", literal).replace('"MARKER"', json.dumps(MARKER))


def meta_output(messages) -> dict | None:
    """The metaprogram's JSON, from the REPL's messages; None if it didn't print any."""
    for m in messages:
        if m.data.startswith(MARKER):
            return json.loads(m.data[len(MARKER) :])
    return None


@dataclass
class RawResult:
    """What one extraction produced, before `build.py` interprets it."""

    meta: dict | None  # metaprogram output; None if it could not run
    messages: list  # lean-interact `Message`s about the source (the metaprogram's are dropped)
    tactics: list  # lean-interact `Tactic`s in the source
    declarations: list  # lean-interact `DeclarationInfo`s in the source
    source_lines: int  # number of lines in the submitted source


def source_messages(messages, last_line: int, meta_ran: bool) -> list:
    """Lean's messages about the source, whose last line is `last_line`. When the appended
    metaprogram ran, messages after that line are about the metaprogram and are dropped. When it
    didn't, the source swallowed it (an unclosed `/-`, an unfinished `by` at the end), so errors
    after the end are the source's: they are kept, moved to its last line. (Same rule as
    origin/proof-graph-v2.)"""
    end = Pos(line=last_line, column=0)
    out = []
    for m in messages:
        if m.data.startswith(MARKER):
            continue
        line = m.start_pos.line if m.start_pos else 0
        if line <= last_line:
            out.append(m)
        elif not meta_ran and m.severity == "error":
            out.append(m.model_copy(update={"start_pos": end, "end_pos": end}))
    return out


def run_source(source: str, params: Params, timeout: float) -> RawResult:
    """Elaborate `source` with the metaprogram appended. Blocking; raises `lean.LeanUnavailable`."""
    last_line = source.count("\n") + 1
    response = lean.run_raw(
        source + "\n\n" + metaprogram(params),
        all_tactics=True,
        declarations=True,
        timeout=timeout,
    )
    meta = meta_output(response.messages)
    meta_ran = meta is not None
    if not meta_ran:
        # The end of the source swallowed the metaprogram (an unclosed `/-`, an unfinished `by`).
        # Run it again on the state the source left. That state only exists while the REPL hasn't
        # restarted in between (lean-interact restarts it under memory pressure), so this can fail.
        try:
            again = lean.run_raw(metaprogram(params), env=response.env, timeout=timeout)
            meta = meta_output(again.messages)
        except lean.LeanUnavailable as e:
            log.warning("lemma graph: metaprogram rerun on the source's state failed: %s", e)
        if meta is None:
            log.warning("lemma graph: the metaprogram did not run after the source")
    return RawResult(
        meta=meta,
        messages=source_messages(response.messages, last_line, meta_ran),
        tactics=[t for t in response.tactics if t.start_pos.line <= last_line],
        declarations=[d for d in response.declarations if d.range.start.line <= last_line],
        source_lines=last_line,
    )


def run_meta(params: Params, timeout: float) -> dict | None:
    """Run only the metaprogram on the plain Mathlib environment (no source): for expanding
    library theorems and for virtual roots. Blocking; raises `lean.LeanUnavailable`."""
    response = lean.run_raw(metaprogram(params), timeout=timeout)
    meta = meta_output(response.messages)
    if meta is None:
        errors = [m.data for m in response.messages if m.severity == "error"]
        raise lean.LeanUnavailable("lemma graph metaprogram failed: " + "; ".join(errors[:3]))
    return meta
