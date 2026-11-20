"""The proof graph returned by `create_graph` and `POST /api/graph`. See README.md."""

from pydantic import BaseModel

# Node kinds
DECLARATION = "declaration"  # a theorem/def/structure/... written in the source
STEP = "step"  # a tactic; nested tactics are child steps
EXTERNAL = "external"  # a library lemma the proof relies on

# Edge kinds. Edges point from the dependent node to the node it depends on.
USES = "uses"  # src refers to the declaration or lemma dst
USES_HYP = "uses_hyp"  # src names a hypothesis that step dst introduced (label = the name)


class Node(BaseModel):
    id: str  # "decl:<name>", "<decl id>/<n>" for steps, "ext:<name>"
    kind: str
    label: str  # declaration name, first line of the tactic, or lemma name
    parent_id: str | None = None  # the declaration or step containing this step
    decl_kind: str | None = None  # theorem, definition, structure, ... (not for steps)
    code: str | None = None  # exact source text
    statement: str | None = None  # declaration type / lemma statement, as Lean prints it
    start_line: int | None = None  # 1-based lines, 0-based columns, in the submitted source
    start_col: int | None = None
    end_line: int | None = None
    end_col: int | None = None
    goals_before: str | None = None  # steps: goal state before the tactic
    goals_after: str | None = None  # steps: "" = no goals left, None = unknown
    ok: bool = True  # False if Lean reported an error or `sorry` inside this node
    order_index: int | None = None  # position in the step-by-step order; None for lemmas


class Edge(BaseModel):
    src: str
    dst: str
    kind: str
    label: str | None = None


class LeanMessage(BaseModel):
    severity: str  # error, warning, info
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    text: str


class ProofGraph(BaseModel):
    ok: bool  # Lean accepted the whole source: no errors, no `sorry`
    lean_version: str | None
    messages: list[LeanMessage]
    nodes: list[Node]  # in `order_index` order (parents before children), lemmas last
    edges: list[Edge]
