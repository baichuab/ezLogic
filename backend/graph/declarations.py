"""The declaration-level view of a proof graph: one entry per theorem/lemma/definition in the source,
with the declarations it depends on directly. See README.md ("Declaration graph").

    decls = declaration_graph(await create_graph(source))
    decls.declarations[i].depends_on   # e.g. ["double", "double_eq"]
"""

from pydantic import BaseModel

from .model import DECLARATION, EXTERNAL, STEP, USES, ProofGraph


class DeclarationEntry(BaseModel):
    name: str  # "sum_le"; examples are "example", "example#2", ... by position
    kind: str  # theorem, definition, structure, example, ...
    statement: str | None  # full type, as Lean prints it
    code: str  # exact source text
    start_line: int  # 1-based lines in the submitted source
    end_line: int
    order_index: int  # walkthrough order: after everything it depends on (except in `mutual` cycles)
    ok: bool  # False if Lean reported an error or `sorry` inside it
    depends_on: list[str]  # names of declarations in the source it uses directly, in walkthrough order
    lemmas: list[str]  # library lemmas it (or one of its tactic steps) uses, sorted


class DeclarationGraph(BaseModel):
    ok: bool  # Lean accepted the whole source
    lean_version: str | None
    declarations: list[DeclarationEntry]  # in walkthrough order


def _name(node_id: str) -> str:
    return node_id.removeprefix("decl:")


def declaration_graph(graph: ProofGraph) -> DeclarationGraph:
    """Collapse a `ProofGraph` to its declarations. A declaration depends on another if Lean's record
    of the declaration uses it, or if one of its tactic steps does. Counting the steps keeps the
    links of a declaration that failed, whose proof Lean replaced with `sorry`."""
    nodes = {n.id: n for n in graph.nodes}

    def owner(node_id: str) -> str:  # the declaration a step belongs to
        while nodes[node_id].kind == STEP:
            node_id = nodes[node_id].parent_id
        return node_id

    depends: dict[str, set[str]] = {}
    lemmas: dict[str, set[str]] = {}
    for e in graph.edges:
        if e.kind != USES or nodes[e.src].kind not in (DECLARATION, STEP):
            continue
        src, dst = owner(e.src), nodes[e.dst]
        if dst.kind == DECLARATION and dst.id != src:
            depends.setdefault(src, set()).add(dst.id)
        elif dst.kind == EXTERNAL:
            lemmas.setdefault(src, set()).add(dst.label)

    decls = sorted((n for n in graph.nodes if n.kind == DECLARATION), key=lambda n: n.order_index)
    return DeclarationGraph(
        ok=graph.ok,
        lean_version=graph.lean_version,
        declarations=[
            DeclarationEntry(
                name=_name(n.id),
                kind=n.decl_kind or "",
                statement=n.statement,
                code=n.code or "",
                start_line=n.start_line,
                end_line=n.end_line,
                order_index=n.order_index,
                ok=n.ok,
                depends_on=[_name(d) for d in sorted(depends.get(n.id, ()), key=lambda d: nodes[d].order_index)],
                lemmas=sorted(lemmas.get(n.id, ())),
            )
            for n in decls
        ],
    )
