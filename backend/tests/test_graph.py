"""Tests for backend/graph. The fixtures are real Lean output saved with
`python -m graph tests/fixtures/<name>.lean --save-extraction tests/fixtures/<name>.extraction.json`,
so these run without Lean. The last test runs Lean itself and is skipped if it is not installed.
"""

import shutil
from pathlib import Path

import pytest

from config import Config
from graph import Extraction, build_graph, create_graph_sync
from graph.build import is_interesting
from graph.extract import ConstantInfo, source_messages
from lean_interact.interface import Message, Pos
from graph.goals import case_tag, continues, hypothesis_names

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    source = (FIXTURES / f"{name}.lean").read_text(encoding="utf-8")
    ex = Extraction.model_validate_json((FIXTURES / f"{name}.extraction.json").read_text(encoding="utf-8"))
    graph = build_graph(source, ex)
    nodes = {n.id: n for n in graph.nodes}
    edges = {(e.src, e.dst, e.kind, e.label) for e in graph.edges}
    return graph, nodes, edges


def test_goal_parsing():
    goals = "case succ\na b : Nat\nh : a ≤\n  b\ninst✝ : Foo\n⊢ a ≤ b\n\ncase zero\nc : Nat\n⊢ True"
    assert hypothesis_names(goals) == {"a", "b", "h"}
    assert case_tag(goals) == "succ"
    assert case_tag("x : Nat\n⊢ x = x") == ""
    assert hypothesis_names("") == set()
    assert continues("", "zero") and continues("succ", "succ.h")
    assert not continues("zero", "succ")


@pytest.mark.parametrize("name", ["basic", "branches", "sorry", "mutual"])
def test_graph_is_well_formed(name):
    graph, nodes, _ = load(name)
    assert len(nodes) == len(graph.nodes)  # unique ids
    for e in graph.edges:
        assert e.src in nodes and e.dst in nodes
    seen = set()
    for n in graph.nodes:  # parents come before their children
        assert n.parent_id is None or n.parent_id in seen
        seen.add(n.id)
    ordered = [n.order_index for n in graph.nodes if n.order_index is not None]
    assert ordered == list(range(len(ordered)))
    for n in graph.nodes:
        if n.kind == "external":
            assert n.order_index is None and n.decl_kind == "theorem"


def test_declarations_and_lemmas():
    graph, nodes, edges = load("basic")
    assert not graph.ok
    # Lemmas are explained before the theorems that use them.
    order = {n.id: n.order_index for n in graph.nodes}
    assert order["decl:double"] < order["decl:double_eq"] < order["decl:double_add"]
    assert ("decl:double_add", "decl:double_eq", "uses", None) in edges
    assert ("decl:double_add/1", "decl:double_eq", "uses", None) in edges  # rw [double_eq]
    assert ("decl:sum_le/1", "ext:Nat.le_trans", "uses", None) in edges
    assert ("decl:term_mode", "ext:Nat.add_le_add", "uses", None) in edges  # term-mode proof
    # `simp` used Nat.add_left_cancel_iff._simp_1, shown as the lemma itself.
    assert ("decl:add_zero'/3", "ext:Nat.add_left_cancel_iff", "uses", None) in edges
    # Code and positions point into the submitted source.
    assert nodes["decl:double_eq"].code.startswith("theorem double_eq")
    assert (nodes["decl:double_eq"].start_line, nodes["decl:double_eq"].end_line) == (3, 5)
    assert nodes["decl:double_eq/2"].goals_after == ""  # omega finished the proof


def test_mutual_recursion():
    """The REPL does not report declarations in `mutual` blocks; they are recovered from Lean's
    declaration ranges, and the cycle between them does not break the ordering."""
    graph, nodes, edges = load("mutual")
    assert nodes["decl:isEven"].decl_kind == "definition"
    assert nodes["decl:isOdd"].code.startswith("def isOdd")
    assert ("decl:isEven", "decl:isOdd", "uses", None) in edges  # the cycle
    assert ("decl:isOdd", "decl:isEven", "uses", None) in edges
    assert ("decl:isEven_zero", "decl:isEven", "uses", None) in edges
    assert ("decl:uses_both", "decl:isOdd", "uses", None) in edges
    decls = [n.id for n in graph.nodes if n.kind == "declaration"]
    assert decls == [
        "decl:helper",
        "decl:helper_pos",
        "decl:isEven",  # the mutual block stays together, in source order
        "decl:isOdd",
        "decl:isEven_zero",
        "decl:uses_both",
    ]


def test_no_spurious_recovered_declarations():
    """Recovery adds nothing when the REPL already reported every declaration."""
    _, nodes, _ = load("basic")
    assert sorted(n for n in nodes if n.startswith("decl:") and "/" not in n) == [
        "decl:add_zero'",
        "decl:double",
        "decl:double_add",
        "decl:double_eq",
        "decl:sum_le",
        "decl:term_mode",
    ]


def test_errors_are_attached_to_nodes():
    _, nodes, _ = load("basic")
    assert not nodes["decl:double_add"].ok
    assert not nodes["decl:double_add/2"].ok  # ring_nf (unknown without Mathlib)
    assert nodes["decl:double_add/1"].ok
    assert nodes["decl:double_eq"].ok


def test_sorry_is_not_ok():
    graph, nodes, _ = load("sorry")
    assert not graph.ok  # Lean only warns about `sorry`
    assert not nodes["decl:s"].ok
    assert not nodes["decl:s/3"].ok  # the `sorry` step itself
    assert nodes["decl:s/1"].ok and nodes["decl:s/2"].ok
    assert nodes["decl:done"].ok and nodes["decl:done/1"].ok


def test_errors_past_the_end_are_kept():
    """An unclosed comment swallows the appended metaprogram; Lean's error is reported inside it."""
    msg = Message(start_pos=Pos(line=44, column=0), severity="error", data="unterminated comment")
    info = Message(start_pos=Pos(line=50, column=0), severity="info", data="ignored")
    inside = Message(start_pos=Pos(line=2, column=0), severity="error", data="kept as is")
    kept = source_messages([inside, msg, info], last_line=3, meta_ran=False)
    assert [(m.data, m.start_pos.line) for m in kept] == [("kept as is", 2), ("unterminated comment", 3)]
    # When the metaprogram ran, anything past the end is about the metaprogram, not the source.
    assert [m.data for m in source_messages([inside, msg], last_line=3, meta_ran=True)] == ["kept as is"]


def test_nesting():
    _, nodes, _ = load("basic")
    assert nodes["decl:sum_le/4"].parent_id == "decl:sum_le/3"  # `by omega` inside obtain
    assert nodes["decl:add_zero'/2"].parent_id == "decl:add_zero'/1"  # induction branches
    assert nodes["decl:add_zero'/3"].parent_id == "decl:add_zero'/1"


def test_hypothesis_edges():
    _, _, edges = load("basic")
    assert ("decl:sum_le/5", "decl:sum_le/3", "uses_hyp", "hk") in edges  # subst hk <- obtain

    _, _, edges = load("branches")
    hyp_edges = {e for e in edges if e[2] == "uses_hyp"}
    assert hyp_edges == {
        ("decl:and_swap/2", "decl:and_swap/1", "uses_hyp", "h"),  # rcases h <- intro h
        ("decl:and_swap/4", "decl:and_swap/2", "uses_hyp", "hq"),
        ("decl:and_swap/5", "decl:and_swap/2", "uses_hyp", "hp"),
        # Branch hypotheses come from the induction / cases step, not from another branch.
        ("decl:sum_formula/3", "decl:sum_formula/1", "uses_hyp", "ih"),
        ("decl:or_comm'/2", "decl:or_comm'/1", "uses_hyp", "hp"),
        ("decl:or_comm'/3", "decl:or_comm'/1", "uses_hyp", "hq"),
        ("decl:or_comm'/4", "decl:or_comm'/3", "uses_hyp", "hq'"),
    }


def test_noise_is_filtered():
    graph, nodes, edges = load("branches")
    externals = {n.label for n in graph.nodes if n.kind == "external"}
    assert externals == {"List.range_succ", "List.sum_append", "Nat.mul_add"}  # no projections/plumbing
    assert ("decl:uses_swap", "decl:and_swap", "uses", None) in edges
    assert "decl:example" in nodes

    def lemma(name, kind="theorem"):
        return ConstantInfo(name=name, canonical=name, kind=kind)

    assert is_interesting(lemma("Nat.add_comm"))
    assert not is_interesting(lemma("Eq.mpr"))  # plumbing
    assert not is_interesting(lemma("Lean.Omega.tidy_sat"))  # tactic internals
    assert not is_interesting(lemma("Std.instReflLeOfIsPreorder"))  # instance
    assert not is_interesting(lemma("Nat.add", kind="definition"))


def test_without_metaprogram_output():
    """If the metaprogram did not run, steps and their lemmas are still there."""
    source = (FIXTURES / "basic.lean").read_text(encoding="utf-8")
    ex = Extraction.model_validate_json((FIXTURES / "basic.extraction.json").read_text(encoding="utf-8"))
    ex.local_constants = None
    graph = build_graph(source, ex)
    edges = {(e.src, e.dst, e.kind) for e in graph.edges}
    assert ("decl:sum_le/1", "ext:Nat.le_trans", "uses") in edges
    assert ("decl:double_add/1", "decl:double_eq", "uses") in edges


@pytest.mark.skipif(not shutil.which(Config.LAKE_PATH), reason="Lean (lake) is not installed")
def test_live_lean():
    graph = create_graph_sync("theorem t (p q : Prop) (hp : p) (hq : q) : p ∧ q := by\n  exact ⟨hp, hq⟩\n")
    assert graph.ok
    assert [n.id for n in graph.nodes] == ["decl:t", "decl:t/1"]
    assert graph.nodes[1].goals_after == ""

    graph = create_graph_sync("theorem t : 1 = 1 := rfl\n/- oops\n")
    assert not graph.ok
    assert [m.text for m in graph.messages] == ["unterminated comment"]
