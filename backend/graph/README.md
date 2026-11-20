# Proof graphs

Turns a Lean 4 source into a graph of the pieces it is made of: its declarations, the tactic steps
inside each proof, and the library lemmas it relies on. Edges record what depends on what. Each node
also gets an `order_index`, so a proof can be walked through step by step with every lemma
explained before the theorem that uses it.

The structure comes from Lean itself, not from an LLM: Lean reports which tactics ran, what goal
each one faced, and which constants every declaration and tactic used.

## Usage

```python
from graph import create_graph

graph = await create_graph(lean_source)   # ProofGraph (pydantic); raises ExtractionError without Lean
graph.model_dump()                        # plain dict / JSON
```

- **API:** `POST /api/graph` with `{"code": "<lean source>"}` returns the graph. Nothing is stored;
  every call re-runs Lean. The response format is listed under `ProofGraph` at `/docs`.
- **Terminal** (from `backend/`): `python -m graph proof.lean` prints the nodes in order with their
  edges; add `--json` for the raw graph.
- **Tests** (from `backend/`): `pytest tests`. They use saved Lean output in `tests/fixtures/`, so
  only the last test needs Lean installed.

Lean must be installed (see the main README). The first run builds the Lean REPL, which takes a
few minutes.

## How it works

```
source ──► extract.py ──► Extraction ──► build.py ──► ProofGraph
           (runs Lean)    (Lean's raw      (pure Python)
                           output)
```

### 1. Extraction (`extract.py`)

The source is sent to the Lean REPL (via `lean-interact`) as one command:

```
import Lean        ← added so the metaprogram below can use Lean's API
<the source>
<metaprogram>      ← a short Lean program that prints dependency data as JSON
```

with two REPL options switched on:

- `all_tactics`: every tactic with its position, the goal before it, and the constants it used;
- `declarations`: every declaration with its name, kind, position and statement.

The metaprogram runs after the source, so it can see everything the source defined. It prints:

- **locals:** every constant the source created, with the constants it uses. This includes the
  helpers Lean generates behind the scenes (`foo.match_1`, `foo.proof_1`, structure projections).
- **constants:** each library constant those use, with its kind (theorem, definition, instance,
  projection, ...), its statement if it is a theorem, and its *canonical* name. The canonical name
  maps generated names back to the real lemma: `Nat.add_left_cancel_iff._simp_1` becomes
  `Nat.add_left_cancel_iff`.

A declaration that fails is stored by Lean as `sorry`, so lemmas its tactics used would be missing
from `constants`. Those are classified with a second command that only repeats the imports.

Because `import Lean` is added as the first line, every position Lean reports is one line too far
down; `Extraction.line_offset` records this and the builder subtracts it.

Messages Lean reports past the end of the source belong to the metaprogram and are dropped, unless
the metaprogram produced no output. Then the source broke it (an unclosed `/-` comment swallows
it, for example), so those errors are kept and moved to the source's last line.

### 2. Building the graph (`build.py`)

**Nodes**

| Kind | One per | Notes |
| --- | --- | --- |
| `declaration` | theorem, lemma, def, structure, instance, example | `code` is the exact source text; `statement` is its type |
| `step` | tactic | Nested under the declaration, or under the tactic containing it: the branches of `induction`/`cases`, or the `by` block inside a `have`. Nesting comes from source positions. |
| `external` | library lemma used | Only real lemmas: definitions, instances, projections, tactic internals (`Lean.*`, `Mathlib.Tactic.*`) and plumbing (`Eq.mpr`, `congrArg`, ...) are left out |

**Edges** point from the dependent node to what it depends on.

- `uses`, declaration → declaration: from Lean's record of the constants each declaration uses,
  looking through its generated helpers (so a `match` inside `foo` counts as `foo`).
- `uses`, step → lemma or declaration: the lemmas a tactic applied. Definitions appear in nearly
  every goal that mentions them, so a step only links to one if it names it (`unfold double`).
- `uses`, declaration → lemma: only for term-mode proofs, which have no steps to carry these.
- `uses_hyp`, step → step: the step names a hypothesis that an earlier step introduced. The
  `label` is the hypothesis name.

**Which step introduced a hypothesis** is read off the goal states. A name that is in a step's goal
but not in the previous step's goal was introduced by the previous step (`have`, `obtain`,
`intro`, ...). Names that first appear inside a step's branches were introduced by that step
(`cases`, `induction`). Lean tags goals with their case (`case succ`), which keeps steps in
different branches from being treated as one sequence: `ih` in the `succ` branch belongs to the
`induction` step, not to whatever ran last in the `zero` branch.

**Goals after a step** are the next step's goals on the same branch. They are `""` when nothing
is left to prove, and `null` when unknown (for example after an error).

**Errors:** a node has `ok: false` if Lean reported an error inside it, or if it contains
`sorry`/`admit`. Lean only warns about `sorry`, and at the declaration's name, so steps are checked
for the word in their own code. Lean's messages are also returned in `messages`. The graph is still
built for proofs with errors, which is when an explanation is most useful.

**Order:** declarations are sorted so each comes after the declarations it uses, with ties broken
by source position (networkx `lexicographical_topological_sort`). Each declaration is followed by
its steps in source order. `nodes` is returned in this order; `external` nodes come last and have
no `order_index`.

## Output

```json
{
  "ok": true,
  "lean_version": "4.36.0-rc1",
  "messages": [],
  "nodes": [
    {"id": "decl:t", "kind": "declaration", "label": "t", "decl_kind": "theorem",
     "code": "theorem t (a b : Nat) : a + b = b + a := by\n  exact Nat.add_comm a b",
     "statement": "a + b = b + a", "start_line": 1, "start_col": 0, "end_line": 2, "end_col": 24,
     "ok": true, "order_index": 0, ...},
    {"id": "decl:t/1", "kind": "step", "label": "exact Nat.add_comm a b", "parent_id": "decl:t",
     "goals_before": "a b : Nat\n⊢ a + b = b + a", "goals_after": "", "order_index": 1, ...},
    {"id": "ext:Nat.add_comm", "kind": "external", "label": "Nat.add_comm", "decl_kind": "theorem",
     "statement": "∀ (n m : Nat), n + m = m + n", "order_index": null, ...}
  ],
  "edges": [{"src": "decl:t/1", "dst": "ext:Nat.add_comm", "kind": "uses", "label": null}]
}
```

All fields are documented in `model.py`. Node ids are stable for the same source: `decl:<name>`,
`<declaration id>/<n>` for the n-th tactic in it, and `ext:<lemma>`.

**For storage:** this package stores nothing. To cache graphs, key them by a hash of the source
together with `graph.GRAPH_VERSION`, which is bumped whenever the output format changes.

## Limitations

- **Mathlib:** the shared REPL in `agent/lean.py` is not set up as a Lake project with Mathlib, so
  sources that `import Mathlib` fail (this also affects snippet checks).
- **Hypothesis use is found by name.** Tactics that use hypotheses without naming them (`omega`,
  `simp_all`, `assumption`, `simp [*]`) get no `uses_hyp` edge.
- **Reused hypothesis names give wrong `uses_hyp` edges.** Introductions are found by comparing
  names between goal states, so re-introducing a name that already exists is not seen. In
  `intro h; have h : q := hq; exact h`, `exact h` points to the `intro` step instead of the `have`,
  and the `have` itself gets an edge to the `intro` because its code mentions `h`.
- **Every tactic is a step.** Short runs of tactics are not grouped yet.
- **`import Lean`** is added to every source. This adds a moment to each run and could in rare
  cases clash with a user declaration of the same name.

## Files

| File | Contents |
| --- | --- |
| `extract.py` | Runs Lean; the metaprogram; `Extraction` |
| `build.py` | `Extraction` → `ProofGraph` |
| `goals.py` | Reads hypothesis names and case tags from goal states |
| `model.py` | `ProofGraph`, `Node`, `Edge`, `LeanMessage` |
| `__main__.py` | Terminal command |
