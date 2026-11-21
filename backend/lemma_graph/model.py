"""The lemma dependency graph returned by `build_lemma_graph` and `POST /api/lemma-graph`."""

from typing import Literal

from pydantic import BaseModel

NodeKind = Literal["theorem", "example", "axiom"]
# local: written in the submitted source; mathlib / core (Init, Std, Lean) / batteries / other: by
# the module the constant comes from.
Origin = Literal["local", "mathlib", "core", "batteries", "other"]


class LemmaNode(BaseModel):
    id: str  # Lean's full name ("Finset.sum_range_succ", "_private.0.foo"); "example@<line>" for examples
    label: str  # the name to show: private names as written, "example (line 14)" for examples
    kind: NodeKind
    origin: Origin
    module: str | None = None  # e.g. "Mathlib.Algebra.BigOperators.Group.Finset.Basic"; None for local
    statement: str | None = None  # the theorem's type, as Lean prints it
    class_field: bool = False  # a field of a class, e.g. `MulOneClass.mul_one`: an axiom of that class
    # (not of a plain structure: `And.left` is False)
    depth: int | None = None  # links from the nearest root (the source's own theorems are 0); None for axioms
    truncated: bool = False  # its dependencies were not followed (depth or node limit): expand it to see them
    ok: bool = True  # local nodes: False if Lean reported an error in it or it relies on `sorry`
    start_line: int | None = None  # local nodes: 1-based, inclusive lines in the submitted source
    end_line: int | None = None
    axioms: list[str] | None = None  # every axiom it relies on (`#print axioms`); None if not computed


class LemmaEdge(BaseModel):
    src: str  # the dependent node
    dst: str  # what it depends on
    kind: Literal["uses", "axiom"]  # uses: theorem -> theorem; axiom: -> an axiom node


class LeanMessage(BaseModel):
    severity: str
    line: int | None
    column: int | None
    text: str


class LemmaGraph(BaseModel):
    ok: bool  # Lean accepted the source: no errors, and nothing relies on `sorry`
    truncated: bool  # some nodes were not expanded (see LemmaNode.truncated)
    roots: list[str]  # ids of the source's own theorems and examples, in source order
    nodes: list[LemmaNode]  # by depth, axioms last
    edges: list[LemmaEdge]
    messages: list[LeanMessage]  # Lean's messages about the source
    notes: list[str] = []  # anything that makes the graph incomplete, in plain words
    lean_version: str | None = None
