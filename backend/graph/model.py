"""The proof graph: nodes for pieces of Lean code, edges for dependencies between them."""

from dataclasses import asdict, dataclass, field

# Node kinds
DECLARATION = "declaration"  # a theorem/lemma/def/structure/... written in the source
STEP = "step"  # a tactic inside a declaration's proof; nested tactics are child steps
EXTERNAL = "external"  # a lemma from a library (Init, Std, Mathlib, ...) the proof relies on

# Edge kinds. Edges point from the dependent node to the node it depends on.
USES = "uses"  # src refers to the constant dst (a declaration or an external lemma)
USES_HYP = "uses_hyp"  # src mentions a hypothesis that step dst introduced (label = its name)


@dataclass
class Node:
    id: str  # unique within a graph: "decl:<name>", "<decl id>/<n>", "ext:<name>"
    kind: str
    label: str  # declaration name, first line of the tactic, or lemma name
    parent_id: str | None = None  # declaration or step that contains this step
    decl_kind: str | None = None  # theorem, definition, structure, ... (not for steps)
    code: str | None = None  # exact source text (declarations and steps)
    statement: str | None = None  # what the declaration / external lemma states
    start_line: int | None = None  # 1-based lines, 0-based columns, in the submitted source
    start_col: int | None = None
    end_line: int | None = None
    end_col: int | None = None
    goals_before: str | None = None  # steps: goal state before the tactic
    goals_after: str | None = None  # steps: state after; "" = no goals left, None = unknown
    ok: bool = True  # False if Lean reported an error (or sorry) inside this node
    order_index: int | None = None  # position in the step-by-step explanation; None for externals


@dataclass
class Edge:
    src: str
    dst: str
    kind: str
    label: str | None = None


@dataclass
class ProofGraph:
    ok: bool  # Lean accepted the whole source with no errors and no sorry
    lean_version: str | None
    messages: list[dict]  # Lean messages: severity, start/end line/col, text
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ProofGraph":
        return cls(
            ok=d["ok"],
            lean_version=d.get("lean_version"),
            messages=d.get("messages", []),
            nodes=[Node(**n) for n in d.get("nodes", [])],
            edges=[Edge(**e) for e in d.get("edges", [])],
        )
