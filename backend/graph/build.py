"""Turn an `Extraction` into a `ProofGraph`. Pure Python; no Lean needed. See README.md."""

import re
from dataclasses import dataclass, field

import networkx as nx

from .extract import ConstantInfo, Extraction
from .goals import case_tag, continues, hypothesis_names
from .model import DECLARATION, EXTERNAL, STEP, USES, USES_HYP, Edge, LeanMessage, Node, ProofGraph

# Lean 4.36 writes "declaration uses `sorry`"; older versions used straight quotes.
SORRY_WARNING = re.compile(r"declaration uses [`']sorry[`']")
SORRY_TOKEN = re.compile(r"(?<![\w.'])(sorry|admit)(?![\w'])")

# Lemmas tactics insert as plumbing; showing them would only add noise.
PLUMBING = frozenset(
    """
    Eq.mpr Eq.mp Eq.trans Eq.symm Eq.refl Eq.subst Eq.substr Eq.ndrec Eq.propIntro congr congrArg
    congrFun eq_self eq_true eq_false of_eq_true of_eq_false iff_self propext id rfl trivial
    implies_congr forall_congr Decidable.byContradiction Classical.byContradiction Not.intro
    absurd False.elim Iff.rfl HEq.refl cast_eq of_decide_eq_true
    """.split()
)
IGNORED_PREFIXES = ("Lean.", "Std.Tactic.", "Mathlib.Tactic.", "Aesop.", "Batteries.Tactic.")

_IDENT = re.compile(r"[^\W\d][\w'!?]*(?:\.[^\W\d][\w'!?]*)*")

Pos = tuple[int, int]
Span = tuple[Pos, Pos]


def is_interesting(info: ConstantInfo) -> bool:
    """Whether a library constant deserves a node: a real lemma, not tactic plumbing."""
    name = info.canonical
    return (
        info.kind == "theorem"
        and name not in PLUMBING
        and not name.startswith(IGNORED_PREFIXES)
        and not name.rsplit(".", 1)[-1].startswith("inst")
    )


def _inside(outer: Span, inner: Span) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def _location(span: Span) -> dict:
    (sl, sc), (el, ec) = span
    return dict(start_line=sl, start_col=sc, end_line=el, end_col=ec)


@dataclass(eq=False)
class _Step:
    decl: str  # declared name of the containing declaration
    span: Span
    goals: str
    used: list[str]
    tag: str = ""
    hyps: set[str] = field(default_factory=set)
    intro_after: set[str] = field(default_factory=set)  # names visible to later steps on its goal
    intro_inside: set[str] = field(default_factory=set)  # names visible inside its branches
    tokens: set[str] = field(default_factory=set)  # identifiers in its own code (not children's)


class _Builder:
    def __init__(self, source: str, ex: Extraction):
        self.source, self.ex = source, ex
        self.line_starts = [0] + [i + 1 for i, ch in enumerate(source) if ch == "\n"]
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple, Edge] = {}
        self.tree = nx.DiGraph()  # declaration -> step -> nested step, children in source order
        self.steps: dict[str, _Step] = {}
        self.decls: list[tuple[str, str, Span]] = []  # (node id, declared name, span), source order
        self.by_name: dict[str, str] = {}  # declared name -> node id (examples have no name)
        self.problems = [
            self._pos(m.start_pos)
            for m in ex.messages
            if m.severity == "error" or SORRY_WARNING.search(m.data)
        ]

    # --- helpers -------------------------------------------------------------------------

    def _pos(self, p) -> Pos:
        return (max(p.line - self.ex.line_offset, 1), p.column)

    def _span(self, start, end) -> Span:
        return (self._pos(start), self._pos(end if end is not None else start))

    def _offset(self, pos: Pos) -> int:
        line = min(pos[0], len(self.line_starts))
        return min(self.line_starts[line - 1] + pos[1], len(self.source))

    def _text(self, span: Span, holes: list[Span] = ()) -> str:
        """Source text of `span`, with each span in `holes` blanked out."""
        out, at = [], self._offset(span[0])
        for hole in sorted(holes):
            out += [self.source[at : self._offset(hole[0])], " "]
            at = self._offset(hole[1])
        return "".join(out) + self.source[at : self._offset(span[1])]

    def _ok(self, span: Span) -> bool:
        return not any(span[0] <= p < span[1] or p == span[0] for p in self.problems)

    def _add_node(self, node: Node) -> str:
        base, n = node.id, 2
        while node.id in self.nodes:
            node.id, n = f"{base}#{n}", n + 1
        self.nodes[node.id] = node
        self.tree.add_node(node.id)
        return node.id

    def _add_edge(self, src: str, dst: str, kind: str, label: str | None = None) -> None:
        if src != dst:
            self.edges.setdefault((src, dst, kind, label), Edge(src=src, dst=dst, kind=kind, label=label))

    def _owner(self, name: str) -> str | None:
        """The declared name that `name` is or belongs to (`foo.match_1` -> `foo`)."""
        owners = [d for d in self.by_name if name == d or name.startswith(d + ".")]
        return max(owners, key=len, default=None)

    def _resolve(self, name: str) -> tuple[str, str]:
        """("decl", declared name), ("aux", name) for Lean-generated helpers, or ("ext", name)."""
        local = self.ex.local_constants
        if name not in self.by_name and local is not None and name not in local:
            return ("ext", name)
        if (owner := self._owner(name)) is not None:
            return ("decl", owner)
        return ("aux", name) if local is not None else ("ext", name)

    def _external(self, name: str) -> str | None:
        info = self.ex.constants.get(name)
        if info is None or not is_interesting(info):
            return None
        node_id = f"ext:{info.canonical}"
        if node_id not in self.nodes:
            self._add_node(
                Node(id=node_id, kind=EXTERNAL, label=info.canonical, decl_kind=info.kind, statement=info.statement)
            )
        return node_id

    # --- passes --------------------------------------------------------------------------

    def add_declarations(self) -> None:
        for d in sorted(self.ex.declarations, key=lambda d: (d.range.start.line, d.range.start.column)):
            span = self._span(d.range.start, d.range.finish)
            label = "example" if d.kind == "example" else d.name
            node_id = self._add_node(
                Node(
                    id=f"decl:{label}",
                    kind=DECLARATION,
                    label=label,
                    decl_kind=d.kind,
                    code=self._text(span),
                    statement=d.statement,
                    ok=self._ok(span),
                    **_location(span),
                )
            )
            self.decls.append((node_id, d.name, span))
            if d.kind != "example":
                self.by_name[d.name] = node_id

    def add_steps(self) -> None:
        tactics = {}  # outer tactics first, duplicates dropped
        for t in self.ex.tactics:
            tactics.setdefault(self._span(t.start_pos, t.end_pos), t)
        ordered = sorted(tactics.items(), key=lambda kv: (kv[0][0], (-kv[0][1][0], -kv[0][1][1])))

        for decl_id, decl_name, decl_span in self.decls:
            stack: list[str] = []  # enclosing steps
            count = 0
            for span, t in ordered:
                if not _inside(decl_span, span):
                    continue
                while stack and not _inside(self.steps[stack[-1]].span, span):
                    stack.pop()
                count += 1
                code = self._text(span)
                first_line = code.strip().split("\n", 1)[0].strip()
                step_id = self._add_node(
                    Node(
                        id=f"{decl_id}/{count}",
                        kind=STEP,
                        label=first_line if len(first_line) <= 80 else first_line[:79] + "…",
                        parent_id=stack[-1] if stack else decl_id,
                        code=code,
                        goals_before=t.goals,
                        # Lean reports `sorry` at the declaration name, so check the step's code.
                        ok=self._ok(span) and not SORRY_TOKEN.search(code),
                        **_location(span),
                    )
                )
                self.tree.add_edge(stack[-1] if stack else decl_id, step_id)
                self.steps[step_id] = _Step(
                    decl=decl_name,
                    span=span,
                    goals=t.goals,
                    used=t.used_constants,
                    tag=case_tag(t.goals),
                    hyps=hypothesis_names(t.goals),
                )
                stack.append(step_id)

    def add_hypothesis_edges(self) -> None:
        for decl_id, _, _ in self.decls:
            self._introductions(decl_id, self.nodes[decl_id].ok)
        for step_id, s in self.steps.items():
            children = [self.steps[c].span for c in self.tree.successors(step_id)]
            s.tokens = set(_IDENT.findall(self._text(s.span, children)))
        for step_id, s in self.steps.items():
            ancestors = nx.ancestors(self.tree, step_id)
            for name in {t.split(".", 1)[0] for t in s.tokens}:
                if (source := self._introducer(name, step_id, ancestors)) is not None:
                    self._add_edge(step_id, source, USES_HYP, name)

    def _introductions(self, parent: str, decl_ok: bool) -> None:
        """Record which names each child of `parent` introduces, and its goals after."""
        ids = list(self.tree.successors(parent))
        sibs = [self.steps[i] for i in ids]
        for i, s in enumerate(sibs):
            if i + 1 < len(sibs) and continues(s.tag, sibs[i + 1].tag):
                self.nodes[ids[i]].goals_after = sibs[i + 1].goals
            elif decl_ok:
                self.nodes[ids[i]].goals_after = ""  # the proof, or this branch of it, is done
        # A step's goal comes from the latest earlier sibling on the same branch: names that are
        # new in it were introduced by that sibling (have, obtain, intro, ...).
        for j, later in enumerate(sibs):
            for earlier in reversed(sibs[:j]):
                if continues(earlier.tag, later.tag):
                    earlier.intro_after |= later.hyps - earlier.hyps
                    break
        # Names new in a step's branches were introduced by the step itself (cases, induction).
        for step_id, s in zip(ids, sibs):
            self._introductions(step_id, decl_ok)
            seen: set[str] = set()
            for child in self.tree.successors(step_id):
                c = self.steps[child]
                s.intro_inside |= c.hyps - s.hyps - seen
                seen |= c.intro_after

    def _introducer(self, name: str, user_id: str, ancestors: set[str]) -> str | None:
        """The latest step whose introduction of `name` is in scope at step `user_id`."""
        user, best = self.steps[user_id], None
        for step_id, s in self.steps.items():
            visible = (
                name in s.intro_after
                and s.span[1] <= user.span[0]
                and next(self.tree.predecessors(step_id)) in ancestors
                and continues(s.tag, user.tag)
            ) or (name in s.intro_inside and step_id in ancestors)
            if visible and (best is None or s.span[0] > self.steps[best].span[0]):
                best = step_id
        return best

    def add_constant_edges(self) -> None:
        for step_id, s in self.steps.items():
            for c in s.used:
                kind, name = self._resolve(c)
                if kind == "decl" and name != s.decl:
                    target = self.nodes[self.by_name[name]]
                    # Definitions show up in every goal that mentions them; only link if named.
                    if target.decl_kind == "theorem" or any(name == t or name.endswith("." + t) for t in s.tokens):
                        self._add_edge(step_id, target.id, USES)
                elif kind == "ext" and (ext := self._external(c)):
                    self._add_edge(step_id, ext, USES)

        if self.ex.local_constants is None:
            return
        for decl_id, decl_name, _ in self.decls:
            if decl_name not in self.ex.local_constants:
                continue
            term_mode = self.tree.out_degree(decl_id) == 0
            for kind, name in self._closure(decl_name):
                if kind == "decl":
                    self._add_edge(decl_id, self.by_name[name], USES)
                elif term_mode and (ext := self._external(name)):
                    self._add_edge(decl_id, ext, USES)

    def _closure(self, decl: str) -> set[tuple[str, str]]:
        """Declarations and library constants `decl` uses, looking through its Lean-generated
        helpers (match_1, proof_1, ...)."""
        local = self.ex.local_constants
        out, seen, stack = set(), set(), list(local[decl].uses)
        while stack:
            m = stack.pop()
            if m in seen or m == decl:
                continue
            seen.add(m)
            kind, name = self._resolve(m)
            if kind == "ext" or (kind == "decl" and name != decl):
                out.add((kind, name))
            elif m in local:
                stack.extend(local[m].uses)
        return out

    def assign_order(self) -> None:
        position = {decl_id: i for i, (decl_id, _, _) in enumerate(self.decls)}
        deps = nx.DiGraph()
        deps.add_nodes_from(position)
        deps.add_edges_from(
            (e.dst, e.src) for e in self.edges.values() if e.kind == USES and e.src in position and e.dst in position
        )
        try:
            order = list(nx.lexicographical_topological_sort(deps, key=position.get))
        except nx.NetworkXUnfeasible:  # mutually dependent declarations: keep source order
            order = list(position)
        for index, node_id in enumerate(n for d in order for n in nx.dfs_preorder_nodes(self.tree, d)):
            self.nodes[node_id].order_index = index

    def build(self) -> ProofGraph:
        self.add_declarations()
        self.add_steps()
        self.add_hypothesis_edges()
        self.add_constant_edges()
        self.assign_order()
        return ProofGraph(
            ok=not self.problems,
            lean_version=self.ex.lean_version,
            messages=[
                LeanMessage(severity=m.severity, text=m.data, **_location(self._span(m.start_pos, m.end_pos)))
                for m in self.ex.messages
            ],
            nodes=sorted(self.nodes.values(), key=lambda n: (n.order_index is None, n.order_index or 0, n.label)),
            edges=list(self.edges.values()),
        )


def build_graph(source: str, extraction: Extraction) -> ProofGraph:
    return _Builder(source, extraction).build()
