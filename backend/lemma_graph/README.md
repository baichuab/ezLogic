# Lemma dependency graph

Proofs rest on lemmas, which rest on other lemmas. Given a Lean 4 source (for example the final Lean of
a chat turn), this package builds the **directed graph of theorem → theorem dependencies**: the
source's own theorems, the Mathlib theorems they use, the theorems *those* use, and so on, with the
axioms everything ends in (`propext`, `Classical.choice`, `Quot.sound`, and `sorryAx` for anything
unproven) as leaf nodes.

The structure comes from Lean itself, not from an LLM: it reads which constants each proof term
refers to.

## Usage

```python
from lemma_graph import build_lemma_graph, expand_lemma_graph

graph = await build_lemma_graph(lean_source)                # LemmaGraph (pydantic)
more = await expand_lemma_graph(["Finset.sum_range_succ"])  # follow truncated nodes further
```

- **API:** `POST /api/lemma-graph` (guest session required, like `/api/chat`):
  - `{"code": "<lean source>", "depth"?: 3, "max_nodes"?: 300, "include_core"?: false}` builds a graph;
  - `{"expand": ["Finset.sum_range_succ", ...], "depth"?: 2}` returns the chain below those library
    theorems, which are its roots at depth 0 (the frontend offsets depths when merging).

  Nothing is stored; every call re-runs Lean. `503` when Lean is unavailable.
- **Terminal** (from `backend/`): `python -m lemma_graph proof.lean [--depth N] [--json]`, or
  `python -m lemma_graph --expand Finset.sum_insert`.
- **Tests:** `pytest tests/test_lemma_graph.py`. They run from saved Lean output in
  `tests/fixtures/lemma_graph/`, without Lean. The one test against real Lean (it loads Mathlib,
  ~1 min) runs only with `RUN_LEAN_TESTS=1`. After changing the metaprogram,
  re-record with `python tests/fixtures/lemma_graph/regenerate.py`.

Needs the Lake workspace with Mathlib that `agent/lean.py` uses (see the main README); the first
call loads Mathlib into the REPL (~30–60 s). After that a graph takes well under a second.

## How it works

```
source ─► extract.py ─────────────────────► raw JSON ─► build.py ─► LemmaGraph
          source + metaprogram, one REPL                (pure Python)
          command on the Mathlib environment
```

### The metaprogram (`extract.py`)

The source is sent to the shared REPL (`agent.lean.run_raw`) **in one command** with a short Lean
program (`#eval show MetaM Unit`) appended, on top of the preloaded `import Mathlib` environment.
One command, because a later command could only continue from the source's state while the REPL
keeps running, and lean-interact restarts it under memory pressure. `import` lines are blanked
(line numbers stay the same), and Mathlib already includes Lean's API, so there is no prelude.

The metaprogram does a breadth-first search:

1. **Roots:** the source's own theorems (`env.constants.map₂`: constants added after the imports),
   sorted by name; or, for `expand`, the given names.
2. **Neighbours** of a theorem: `ConstantInfo.getUsedConstantsAsSet` gives every constant its
   statement and proof term mention, one level down. From those it keeps:
   - **theorems**, except denylisted plumbing (`congrArg`, `Eq.mpr`, `of_eq_true`, `id`, …), tactic
     internals (`Lean.*`, `Mathlib.Tactic.*`, `Mathlib.Meta.*`, …: what `ring`, `norm_num`, `omega`
     build proofs from), equation lemmas of definitions (`double.eq_1`) and generated recursors
     (`Nat.le.brecOn`). `include_core` turns the denylist off.
   - **axioms**, as direct axiom uses.

   It **looks through**, instead of showing:
   - auxiliary constants (`foo._simp_1`, `foo.proof_1`, `_auxLemma.3`, `match_1`): mapped to `foo`
     when that is a theorem, otherwise their own used constants are followed;
   - **instances** that are theorems (`Distrib.leftDistribClass`): replaced by the lemmas they are
     built from (`Distrib.left_distrib`).

   Everything else (definitions, structures, instances that are data) is not a theorem and is dropped.
3. **Limits:** a node at `depth`, or one whose new neighbours would exceed `max_nodes`, is not
   expanded and is marked `truncated` (its edges to nodes already in the graph are kept). The roots
   are always expanded, so the source's own theorems always show their direct dependencies.
4. **Axioms:** `Lean.collectAxioms` (what `#print axioms` uses) for every node. A depth-limited
   search never reaches the axioms itself, and axioms can also come in through definitions, which
   the search doesn't follow.
5. Each node's statement (`ppExpr` of its type), module and, for local theorems, its source lines
   (`findDeclarationRanges?`). One info message `EZLOGIC_LEMMA_GRAPH {json}` carries it all.

**Examples** have no constant, so they aren't in `map₂`. They are found in the source text
(`build.find_examples`), and their dependencies are resolved in a second, source-free command on the
Mathlib environment as *virtual roots*. A virtual root's used constants are the constants its tactics
used (REPL `all_tactics`) plus the identifiers in its text, which also covers term-mode examples. Links
to the source's own theorems are added in Python, because those don't exist in the plain environment.

**An unfinished source** (an unclosed `/-`, an unfinished `by` at the end) swallows the appended
metaprogram. It is then run again on the state the source left. That fails only if the REPL restarted
in between, in which case the graph says so in `notes`. Errors Lean reported past the end are moved to
the source's last line.

### Building the graph (`build.py`)

- **Edges** `uses`: theorem → theorem it depends on. `axiom`: node → axiom, **only for the axioms none
  of its shown dependencies already account for**. Following edges from any node therefore reaches
  exactly the axioms `#print axioms` lists for it (tested), without an arrow from every node to
  `propext`.
- **`ok`** of a local node: no Lean error in its lines and no `sorryAx`. A failed proof keeps its
  links (Lean's error recovery keeps the rest of the proof term) and gets a `sorryAx` edge.
- **`mutual` theorems** depend on each other, so `edges` can contain cycles.
- **Order:** by depth, local nodes by line, axioms last. `roots` = local theorems and examples by line.

## Output

```json
{
  "ok": true, "truncated": true, "roots": ["double_sum"],
  "nodes": [
    {"id": "double_sum", "label": "double_sum", "kind": "theorem", "origin": "local",
     "statement": "∀ (n : ℕ), 2 * (Finset.range (n + 1)).sum id = n * (n + 1)",
     "depth": 0, "truncated": false, "ok": true, "start_line": 3, "end_line": 6,
     "axioms": ["Classical.choice", "Quot.sound", "propext"], "module": null, "class_field": false},
    {"id": "Finset.sum_range_succ", "kind": "theorem", "origin": "mathlib",
     "module": "Mathlib.Algebra.BigOperators.Group.Finset.Basic", "depth": 1, ...},
    {"id": "propext", "kind": "axiom", "origin": "core", "module": "Init.Core", ...}
  ],
  "edges": [{"src": "double_sum", "dst": "Finset.sum_range_succ", "kind": "uses"}, ...],
  "messages": [], "notes": [], "lean_version": "4.35.0"
}
```

All fields are documented in `model.py`. `class_field: true` marks a field of a class, such as
`MulOneClass.mul_one`: an axiom *of that algebraic structure*, which every instance must prove.

## Configuration

`LEMMA_GRAPH_DEPTH` (3) and `LEMMA_GRAPH_MAX_NODES` (300) are the defaults; requests are capped at
`LEMMA_GRAPH_DEPTH_LIMIT` (8) and `LEMMA_GRAPH_NODES_LIMIT` (1500). `LEMMA_GRAPH_TIMEOUT` (120 s)
bounds each Lean command. Without limits the chain grows fast: depth 5 from an ordinary Mathlib proof
already passes 300 theorems.

## Limitations

- **Theorems only.** A proof's dependence on a *definition* (and the theorems inside that
  definition's well-formedness proofs) is not shown. Axioms are exact anyway, via `collectAxioms`.
- **Statement and proof uses are not told apart.** `getUsedConstantsAsSet` covers both. Theorems rarely
  appear in statements.
- **Tactic-generated proofs** show what the tactic actually used: `simp` lists the simp lemmas it
  rewrote with; `ring`, `omega`, `norm_num`, `decide` mostly use their own internals, which are
  denylisted, so a goal closed by `ring` may show no dependencies.
- **Examples** are found by a line-based scan (top-level `example` lines). Identifiers in their text
  are resolved without the source's `open`s, so `open Finset` + `sum_range_succ` in a term-mode example
  is missed (tactic examples are fine: tactics report full names).
- **Expanding a local theorem** isn't possible through `expand` (it runs without the source). It is
  never needed: local theorems are always fully expanded.
- **Shared REPL:** graph builds use the same lean-interact REPL as the agent's Lean checks.

## Files

| File | Contents |
| --- | --- |
| `extract.py` | The metaprogram, denylists, and running it (`run_source`, `run_meta`) |
| `build.py` | Raw output → `LemmaGraph`; examples; merging; axiom edges |
| `model.py` | `LemmaGraph`, `LemmaNode`, `LemmaEdge`, `LeanMessage` |
| `__init__.py` | `build_lemma_graph`, `expand_lemma_graph` (+ `_sync` versions) |
| `__main__.py` | Terminal command |
