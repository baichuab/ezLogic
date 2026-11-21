"""Turn the metaprogram's raw output into a `LemmaGraph`. Pure Python: no Lean needed, so all of
this is tested from saved output (tests/fixtures/lemma_graph/)."""

import re
from .model import LeanMessage, LemmaEdge, LemmaGraph, LemmaNode

MAX_STATEMENT = 1500
SORRY = "sorryAx"

# A top-level command at the start of a line: ends the example before it.
_COMMAND = re.compile(
    r"(?:@\[|/--|#|(?:private|protected|noncomputable|unsafe|partial|nonrec|public)\s"
    r"|(?:theorem|lemma|def|example|instance|abbrev|structure|class|inductive|axiom|opaque"
    r"|namespace|section|end|open|variable|universe|set_option|attribute|mutual|macro"
    r"|syntax|notation|infix|infixl|infixr|prefix|postfix|elab|deriving|irreducible_def)\b)"
)
_EXAMPLE = re.compile(r"(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable)\s+)*example\b")
# Identifiers, possibly dotted: `Nat.add_comm`, `mul_le_mul'`, `h₁`.
_IDENT = re.compile(r"(?<![\w.'])[^\W\d][\w'!?₀-₉]*(?:\.[^\W\d][\w'!?₀-₉]*)*")


def display_name(name: str) -> str:
    """Lean stores `private theorem p` as `_private.0.p` (`_private.<Module>.0.p` in a module):
    show what follows the number."""
    parts = name.split(".")
    if parts[0] != "_private":
        return name
    for i, part in enumerate(parts):
        if part.isdigit():
            return ".".join(parts[i + 1 :]) or name
    return name


def _unescape(name: str) -> str:
    """`«example@14»` -> `example@14` (Lean escapes names that aren't plain identifiers)."""
    return name[1:-1] if name.startswith("«") and name.endswith("»") else name


def origin_of(module: str | None, is_local: bool) -> str:
    if is_local or module is None:
        return "local"
    root = module.split(".")[0]
    if root == "Mathlib":
        return "mathlib"
    if root in ("Init", "Std", "Lean"):
        return "core"
    if root == "Batteries":
        return "batteries"
    return "other"


def find_examples(source: str) -> list[tuple[int, int]]:
    """`(start, end)` lines (1-based, inclusive) of each top-level `example`. An example runs until
    the next top-level command or the end of the source; trailing blank lines are left out."""
    lines = source.split("\n")
    starts = [i for i, line in enumerate(lines) if _EXAMPLE.match(line)]
    out = []
    for i in starts:
        end = len(lines) - 1
        for j in range(i + 1, len(lines)):
            if _COMMAND.match(lines[j]):
                end = j - 1
                break
        while end > i and not lines[end].strip():
            end -= 1
        out.append((i + 1, end + 1))
    return out


def example_roots(source: str, tactics: list, local_ids: set[str]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Virtual roots for the source's examples (Lean keeps no constant for an example), and their
    direct edges to the source's own theorems.

    An example's raw uses are the constants its tactics used (REPL `all_tactics`) plus the
    identifiers in its text, which covers term-mode examples. Names that aren't constants are
    ignored by the metaprogram. Local theorems don't exist in the plain Mathlib environment the
    virtual roots are resolved in, so links to them are returned as edges here instead."""
    lines = source.split("\n")
    roots, local_edges = [], []
    for start, end in find_examples(source):
        node_id = f"example@{start}"
        uses = {c for t in tactics if start <= t.start_pos.line <= end for c in t.used_constants}
        uses |= set(_IDENT.findall("\n".join(lines[start - 1 : end])))
        uses.discard("example")
        for name in sorted(uses & local_ids):
            local_edges.append((node_id, name))
        roots.append({"id": node_id, "uses": sorted(uses - local_ids), "range": [start, end]})
    return roots, local_edges


def _messages(messages: list) -> list[LeanMessage]:
    return [
        LeanMessage(
            severity=m.severity,
            line=m.start_pos.line if m.start_pos else None,
            column=m.start_pos.column if m.start_pos else None,
            text=m.data,
        )
        for m in messages
    ]


def merge_meta(*metas: dict | None) -> dict:
    """Union of several metaprogram outputs, by node id. A node keeps its smallest depth, and is
    truncated only if it was truncated everywhere it appeared."""
    nodes: dict[str, dict] = {}
    axioms: dict[str, dict] = {}
    version = None
    for meta in metas:
        if not meta:
            continue
        version = version or meta.get("lean_version")
        for raw in meta.get("nodes", []):
            n = {**raw, "id": _unescape(raw["id"])}
            old = nodes.get(n["id"])
            if old is None:
                nodes[n["id"]] = n
                continue
            if not n["truncated"] and old["truncated"]:
                merged = {**n, "local": old["local"] or n["local"], "range": old["range"] or n["range"]}
            else:
                merged = {**old, "uses": sorted(set(old["uses"]) | set(n["uses"]))}
            merged["depth"] = min(old["depth"], n["depth"])
            merged["truncated"] = old["truncated"] and n["truncated"]
            nodes[n["id"]] = merged
        for a in meta.get("axioms", []):
            axioms.setdefault(a["id"], a)
    return {"lean_version": version, "nodes": list(nodes.values()), "axioms": list(axioms.values())}


def assemble(
    meta: dict,
    *,
    messages: list | None = None,
    examples: list[dict] | None = None,
    extra_edges: list[tuple[str, str]] | None = None,
    notes: list[str] | None = None,
) -> LemmaGraph:
    """Build the graph from (merged) metaprogram output.

    `examples` are the virtual roots passed to the metaprogram (for their line ranges);
    `extra_edges` are example -> local theorem links found in Python."""
    lean_messages = _messages(messages or [])
    example_range = {e["id"]: e["range"] for e in examples or []}
    raw_nodes = [n for n in meta.get("nodes", [])]
    ids = {n["id"] for n in raw_nodes}

    uses: dict[str, list[str]] = {}
    for n in raw_nodes:
        uses[n["id"]] = [u for u in (_unescape(x) for x in n["uses"]) if u in ids and u != n["id"]]
    for src, dst in extra_edges or []:
        if src in ids and dst in ids and dst not in uses[src]:
            uses[src].append(dst)

    def axioms_of(n: dict) -> set[str]:
        return set(n["axioms"] if n.get("axioms") is not None else n.get("direct_axioms", []))

    by_id = {n["id"]: n for n in raw_nodes}
    errors = [m for m in lean_messages if m.severity == "error"]

    nodes: list[LemmaNode] = []
    edges: list[LemmaEdge] = []
    used_axioms: set[str] = set()
    for n in raw_nodes:
        node_id = n["id"]
        is_example = n["kind"] == "virtual"
        is_local = bool(n.get("local")) or is_example
        lines = example_range.get(node_id) if is_example else n.get("range")
        start, end = (lines or (None, None))[:2]
        node_axioms = axioms_of(n)
        ok = True
        if is_local:
            in_range = start is not None and any(
                m.line is not None and start <= m.line <= end for m in errors
            )
            ok = not in_range and SORRY not in node_axioms
        statement = n.get("statement")
        if statement and len(statement) > MAX_STATEMENT:
            statement = statement[:MAX_STATEMENT] + " …"
        nodes.append(
            LemmaNode(
                id=node_id,
                label=f"example (line {start})" if is_example else display_name(node_id),
                kind="example" if is_example else "theorem",
                origin=origin_of(n.get("module"), is_local),
                module=None if is_local else n.get("module"),
                statement=statement,
                class_field=bool(n.get("class_field")),
                depth=n.get("depth"),
                truncated=bool(n.get("truncated")),
                ok=ok,
                start_line=start,
                end_line=end,
                axioms=sorted(n["axioms"]) if n.get("axioms") is not None else None,
            )
        )
        for dst in uses[node_id]:
            edges.append(LemmaEdge(src=node_id, dst=dst, kind="uses"))
        # Axiom edges: only the axioms none of its shown dependencies already account for, so that
        # following edges from a node reaches exactly the axioms `#print axioms` lists for it.
        covered = set().union(*(axioms_of(by_id[c]) for c in uses[node_id])) if uses[node_id] else set()
        for a in sorted(node_axioms - covered):
            edges.append(LemmaEdge(src=node_id, dst=a, kind="axiom"))
            used_axioms.add(a)

    axiom_info = {a["id"]: a for a in meta.get("axioms", [])}
    for a in sorted(used_axioms):
        info = axiom_info.get(a, {})
        nodes.append(
            LemmaNode(
                id=a,
                label=a,
                kind="axiom",
                origin=origin_of(info.get("module"), False) if info.get("module") else "core",
                module=info.get("module"),
                statement=info.get("statement"),
                ok=a != SORRY,
            )
        )

    order = {n["id"]: i for i, n in enumerate(raw_nodes)}
    nodes.sort(
        key=lambda x: (x.kind == "axiom", x.depth or 0, x.start_line or 0, order.get(x.id, 0))
    )
    roots = sorted(
        (x for x in nodes if x.origin == "local" and x.kind != "axiom"),
        key=lambda x: (x.start_line or 0, x.id),
    )
    any_sorry = any(x.origin == "local" and x.axioms and SORRY in x.axioms for x in nodes)
    return LemmaGraph(
        ok=not errors and not any_sorry,
        truncated=any(x.truncated for x in nodes),
        roots=[x.id for x in roots],
        nodes=nodes,
        edges=edges,
        messages=lean_messages,
        notes=notes or [],
        lean_version=meta.get("lean_version"),
    )


def empty_graph(messages: list | None = None, notes: list[str] | None = None) -> LemmaGraph:
    return assemble({"nodes": [], "axioms": []}, messages=messages, notes=notes)
