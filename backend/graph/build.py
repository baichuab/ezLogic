"""Turn an `Extraction` into a `ProofGraph`. Pure Python; Lean is not needed here.

Nodes
  * one `declaration` node per declaration in the source;
  * one `step` node per tactic, nested under its declaration (or under the tactic that contains
    it, e.g. the branches of `induction` or the `by` block of a `have`);
  * one `external` node per library lemma the proof relies on.

Edges (dependent -> dependency)
  * `uses` between declarations, from Lean's own record of which constants each one uses;
  * `uses` from a step to the lemmas it applied (theorems only; definitions and instances that
    merely appear in the goal are noise), or to a user definition the step names explicitly;
  * `uses` from a term-mode declaration (no tactics) to the library lemmas in its proof term;
  * `uses_hyp` from a step to the earlier step that introduced a hypothesis it mentions. A step
    introduces the names that appear in the next goal state but not in its own (`have`,
    `obtain`, `intro`, ...), or, for `cases`/`induction`, in its branches' goal states.

Explanation order: declarations sorted so every declaration comes after the ones it uses (ties
broken by source position), each followed by its steps in source order.
"""

import re
from dataclasses import dataclass, field

from .extract import ConstantInfo, Declaration, Extraction, Span, Tactic
from .goals import case_tag, continues, hypothesis_names
from .model import DECLARATION, EXTERNAL, STEP, USES, USES_HYP, Edge, Node, ProofGraph

SORRY_WARNING = "declaration uses 'sorry'"

# Lemmas that tactics insert as plumbing; showing them would only add noise.
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


def is_interesting(info: ConstantInfo) -> bool:
    """Whether a library constant deserves a node: a real lemma, not tactic plumbing."""
    name = info.canonical
    return (
        info.kind == "theorem"
        and name not in PLUMBING
        and not name.startswith(IGNORED_PREFIXES)
        and not name.rsplit(".", 1)[-1].startswith("inst")
    )


class _Source:
    def __init__(self, text: str):
        self.text = text
        self.line_starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self.line_starts.append(i + 1)

    def offset(self, line: int, col: int) -> int:
        line = min(max(line, 1), len(self.line_starts))
        return min(self.line_starts[line - 1] + col, len(self.text))

    def slice(self, span: Span, holes: list[Span] = ()) -> str:
        """Text of `span`, with each span in `holes` replaced by a space."""
        start, end = self.offset(span.start_line, span.start_col), self.offset(span.end_line, span.end_col)
        out, pos = [], start
        for h in sorted(holes, key=lambda s: s.start):
            hs, he = self.offset(h.start_line, h.start_col), self.offset(h.end_line, h.end_col)
            if hs < pos:
                continue
            out.append(self.text[pos:hs])
            out.append(" ")
            pos = he
        out.append(self.text[pos:end])
        return "".join(out)


@dataclass(eq=False)
class _Step:
    tactic: Tactic
    node: Node
    decl: Declaration
    parent: "_Step | None" = None
    children: list["_Step"] = field(default_factory=list)
    intro_after: set[str] = field(default_factory=set)  # names visible to later siblings
    intro_inside: set[str] = field(default_factory=set)  # names visible inside this step's branches
    tokens: set[str] = field(default_factory=set)  # identifiers in this step's own code

    @property
    def tag(self) -> str:
        return case_tag(self.tactic.goals)

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent


def _span_fields(span: Span) -> dict:
    return dict(
        start_line=span.start_line, start_col=span.start_col, end_line=span.end_line, end_col=span.end_col
    )


def _first_line(code: str, limit: int = 80) -> str:
    line = code.strip().split("\n", 1)[0].strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"


class _Builder:
    def __init__(self, source: str, ex: Extraction):
        self.src = _Source(source)
        self.ex = ex
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple, Edge] = {}
        self.problems = [
            m for m in ex.messages if m.severity == "error" or SORRY_WARNING in m.text
        ]
        self.decls = sorted(ex.declarations, key=lambda d: d.span.start)
        self.decl_node: dict[int, Node] = {}  # id(Declaration) -> node
        self.by_name: dict[str, Node] = {}  # declared name -> node (examples excluded)
        self.steps: dict[int, list[_Step]] = {}  # id(Declaration) -> top-level steps

    # --- helpers -------------------------------------------------------------------------

    def _add_node(self, node: Node) -> Node:
        base, n = node.id, 2
        while node.id in self.nodes:
            node.id = f"{base}#{n}"
            n += 1
        self.nodes[node.id] = node
        return node

    def _add_edge(self, src: str, dst: str, kind: str, label: str | None = None) -> None:
        if src != dst:
            self.edges.setdefault((src, dst, kind, label), Edge(src, dst, kind, label))

    def _ok(self, span: Span) -> bool:
        return not any(span.contains_pos(m.span.start) for m in self.problems)

    def _owner(self, name: str) -> str | None:
        """The declared name that `name` is, or belongs to (`foo.match_1` -> `foo`)."""
        best = None
        for declared in self.by_name:
            if (name == declared or name.startswith(declared + ".")) and (
                best is None or len(declared) > len(best)
            ):
                best = declared
        return best

    def _resolve(self, name: str) -> tuple[str, str]:
        """Classify a constant: ("decl", declared name), ("aux", name) or ("ext", name)."""
        if name in self.by_name:
            return ("decl", name)
        local = self.ex.local_constants
        if local is not None and name not in local:
            return ("ext", name)
        owner = self._owner(name)
        if owner is not None:
            return ("decl", owner)
        return ("aux", name) if local is not None else ("ext", name)

    def _external(self, name: str) -> Node | None:
        info = self.ex.constants.get(name)
        if info is None or not is_interesting(info):
            return None
        node_id = f"ext:{info.canonical}"
        if node_id not in self.nodes:
            self._add_node(
                Node(
                    id=node_id,
                    kind=EXTERNAL,
                    label=info.canonical,
                    decl_kind=info.kind,
                    statement=info.statement,
                )
            )
        return self.nodes[node_id]

    # --- passes --------------------------------------------------------------------------

    def add_declarations(self) -> None:
        for d in self.decls:
            label = "example" if d.kind == "example" else d.name
            node = self._add_node(
                Node(
                    id=f"decl:{label}",
                    kind=DECLARATION,
                    label=label,
                    decl_kind=d.kind,
                    code=self.src.slice(d.span),
                    statement=d.statement,
                    ok=self._ok(d.span),
                    **_span_fields(d.span),
                )
            )
            self.decl_node[id(d)] = node
            if d.kind != "example":
                self.by_name[d.name] = node

    def add_steps(self) -> None:
        # Outer tactics first, so a stack gives each tactic its innermost container.
        seen = set()
        tactics = []
        for t in sorted(self.ex.tactics, key=lambda t: (t.span.start, (-t.span.end_line, -t.span.end_col))):
            key = (t.span.start, t.span.end)
            if key not in seen:
                seen.add(key)
                tactics.append(t)

        for d in self.decls:
            decl_node = self.decl_node[id(d)]
            top: list[_Step] = []
            stack: list[_Step] = []
            count = 0
            for t in tactics:
                if not d.span.contains(t.span):
                    continue
                while stack and not stack[-1].tactic.span.contains(t.span):
                    stack.pop()
                parent = stack[-1] if stack else None
                count += 1
                code = self.src.slice(t.span)
                node = self._add_node(
                    Node(
                        id=f"{decl_node.id}/{count}",
                        kind=STEP,
                        label=_first_line(code),
                        parent_id=parent.node.id if parent else decl_node.id,
                        code=code,
                        goals_before=t.goals,
                        ok=self._ok(t.span),
                        **_span_fields(t.span),
                    )
                )
                step = _Step(tactic=t, node=node, decl=d, parent=parent)
                (parent.children if parent else top).append(step)
                stack.append(step)
            self.steps[id(d)] = top

    def _walk(self, steps: list[_Step]):
        for s in steps:
            yield s
            yield from self._walk(s.children)

    def add_hypothesis_edges(self) -> None:
        for d in self.decls:
            top = self.steps[id(d)]
            self._introductions(top, decl_ok=self.decl_node[id(d)].ok)
            all_steps = list(self._walk(top))
            for s in all_steps:
                own = self.src.slice(s.tactic.span, [c.tactic.span for c in s.children])
                s.tokens = set(_IDENT.findall(own))
            for user in all_steps:
                for name in {t.split(".", 1)[0] for t in user.tokens}:
                    source = self._introducer(name, user, all_steps)
                    if source is not None:
                        self._add_edge(user.node.id, source.node.id, USES_HYP, name)

    def _introductions(self, siblings: list[_Step], decl_ok: bool) -> None:
        hyps = [hypothesis_names(s.tactic.goals) for s in siblings]
        for i, s in enumerate(siblings):
            nxt = siblings[i + 1] if i + 1 < len(siblings) else None
            if nxt is not None and continues(s.tag, nxt.tag):
                s.node.goals_after = nxt.tactic.goals
            elif decl_ok:
                s.node.goals_after = ""  # the proof (or this branch of it) is complete
        # A step's goal comes from the latest earlier sibling working on the same branch; names
        # that appear in between were introduced by that sibling.
        for j in range(1, len(siblings)):
            for i in range(j - 1, -1, -1):
                if continues(siblings[i].tag, siblings[j].tag):
                    siblings[i].intro_after |= hyps[j] - hyps[i]
                    break
        for s in siblings:
            self._introductions(s.children, decl_ok)
            before = hypothesis_names(s.tactic.goals)
            earlier: set[str] = set()
            for c in s.children:
                s.intro_inside |= hypothesis_names(c.tactic.goals) - before - earlier
                earlier |= c.intro_after

    @staticmethod
    def _introducer(name: str, user: _Step, steps: list[_Step]) -> _Step | None:
        """The latest step before `user` whose introduction of `name` is in scope at `user`."""
        best = None
        ancestors = set(user.ancestors())
        for s in steps:
            if s is user:
                continue
            in_scope = (
                name in s.intro_after
                and s.tactic.span.end <= user.tactic.span.start
                and (s.parent is None or s.parent in ancestors)
                and continues(s.tag, user.tag)
            ) or (name in s.intro_inside and s in ancestors)
            if in_scope and (best is None or s.tactic.span.start > best.tactic.span.start):
                best = s
        return best

    def add_constant_edges(self) -> None:
        local = self.ex.local_constants
        for d in self.decls:
            decl_node = self.decl_node[id(d)]
            steps = list(self._walk(self.steps[id(d)]))

            for s in steps:
                for c in s.tactic.used_constants:
                    kind, name = self._resolve(c)
                    if kind == "decl" and name != d.name:
                        target = self.by_name[name]
                        mentioned = any(name == t or name.endswith("." + t) for t in s.tokens)
                        if target.decl_kind == "theorem" or mentioned:
                            self._add_edge(s.node.id, target.id, USES)
                    elif kind == "ext" and (ext := self._external(c)) is not None:
                        self._add_edge(s.node.id, ext.id, USES)

            if local is None or d.name not in local:
                continue
            for kind, name in self._closure(d.name):
                if kind == "decl":
                    self._add_edge(decl_node.id, self.by_name[name].id, USES)
                elif not steps and (ext := self._external(name)) is not None:
                    self._add_edge(decl_node.id, ext.id, USES)

    def _closure(self, decl: str) -> set[tuple[str, str]]:
        """Declarations and library constants `decl` uses, looking through its auxiliary
        constants (match_1, proof_1, ...)."""
        local = self.ex.local_constants
        out, seen = set(), set()
        stack = list(local[decl].uses)
        while stack:
            m = stack.pop()
            if m in seen or m == decl:
                continue
            seen.add(m)
            kind, name = self._resolve(m)
            if kind == "ext":
                out.add(("ext", name))
            elif kind == "decl" and name != decl:
                out.add(("decl", name))
            elif m in local:
                stack.extend(local[m].uses)
        return out

    def assign_order(self) -> None:
        deps: dict[str, set[str]] = {self.decl_node[id(d)].id: set() for d in self.decls}
        for e in self.edges.values():
            if e.kind == USES and e.src in deps and e.dst in deps:
                deps[e.src].add(e.dst)
        position = {self.decl_node[id(d)].id: i for i, d in enumerate(self.decls)}

        ordered, done = [], set()
        while len(ordered) < len(deps):
            ready = [n for n in deps if n not in done and deps[n] <= done]
            # A dependency cycle (mutual recursion) is broken by source position.
            nxt = min(ready or (n for n in deps if n not in done), key=position.__getitem__)
            ordered.append(nxt)
            done.add(nxt)

        steps_of = {self.decl_node[id(d)].id: self.steps[id(d)] for d in self.decls}
        index = 0
        for decl_id in ordered:
            self.nodes[decl_id].order_index = index
            index += 1
            for s in self._walk(steps_of[decl_id]):
                s.node.order_index = index
                index += 1

    def build(self) -> ProofGraph:
        self.add_declarations()
        self.add_steps()
        self.add_hypothesis_edges()
        self.add_constant_edges()
        self.assign_order()
        messages = [
            {"severity": m.severity, **_span_fields(m.span), "text": m.text} for m in self.ex.messages
        ]
        nodes = sorted(
            self.nodes.values(),
            key=lambda n: (n.order_index is None, n.order_index or 0, n.label),
        )
        return ProofGraph(
            ok=not self.problems,
            lean_version=self.ex.lean_version,
            messages=messages,
            nodes=nodes,
            edges=list(self.edges.values()),
        )


def build_graph(source: str, extraction: Extraction) -> ProofGraph:
    return _Builder(source, extraction).build()
