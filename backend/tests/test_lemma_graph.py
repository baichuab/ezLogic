"""Tests for lemma_graph/. Everything except the last test runs from Lean output saved in
tests/fixtures/lemma_graph/ (<name>.lean -> <name>.raw.json), so no Lean is needed. After changing
the metaprogram, refresh them with `python tests/fixtures/lemma_graph/regenerate.py` (needs Lean).
The last test runs the real thing: `RUN_LEAN_TESTS=1 pytest tests/test_lemma_graph.py`."""

import json
import os
import pathlib
import shutil

import pytest
from lean_interact.interface import Message, Tactic

from lemma_graph import build, extract
from lemma_graph.model import LemmaGraph

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "lemma_graph"


def _load(name: str) -> tuple[str, dict]:
    source_path = FIXTURES / f"{name}.lean"
    source = source_path.read_text() if source_path.exists() else ""
    return source, json.loads((FIXTURES / f"{name}.raw.json").read_text())


def graph_of(name: str) -> LemmaGraph:
    """What build_lemma_graph_sync does after Lean ran, from the saved output."""
    source, raw = _load(name)
    tactics = [Tactic.model_validate(t) for t in raw["tactics"]]
    messages = [Message.model_validate(m) for m in raw["messages"]]
    local_ids = {build._unescape(n["id"]) for n in raw["meta"]["nodes"] if n["local"]}
    examples, edges = build.example_roots(source, tactics, local_ids)
    return build.assemble(
        build.merge_meta(raw["meta"], raw["example_meta"]),
        messages=messages,
        examples=examples,
        extra_edges=edges,
    )


def node(graph: LemmaGraph, node_id: str):
    return next(n for n in graph.nodes if n.id == node_id)


def uses(graph: LemmaGraph, node_id: str, kind: str = "uses") -> set[str]:
    return {e.dst for e in graph.edges if e.src == node_id and e.kind == kind}


def reachable_axioms(graph: LemmaGraph, node_id: str) -> set[str]:
    out, seen, stack = set(), set(), [node_id]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for e in graph.edges:
            if e.src == n:
                (out.add(e.dst) if e.kind == "axiom" else stack.append(e.dst))
    return out


# --- pure helpers ------------------------------------------------------------------------------


def test_display_name_shows_private_names_as_written():
    assert build.display_name("_private.0.priv_thm") == "priv_thm"
    assert build.display_name("_private.Mathlib.Foo.Bar.0.Nat.baz") == "Nat.baz"
    assert build.display_name("Finset.sum_range_succ") == "Finset.sum_range_succ"


def test_origin_from_module():
    assert build.origin_of("Mathlib.Algebra.Ring.Defs", False) == "mathlib"
    assert build.origin_of("Init.Data.Nat.Basic", False) == "core"
    assert build.origin_of("Batteries.Data.List", False) == "batteries"
    assert build.origin_of(None, False) == "local"
    assert build.origin_of("Mathlib.X", True) == "local"


def test_find_examples_ends_at_next_command_and_skips_trailing_blanks():
    source = "theorem a : True := trivial\n\nexample : True := by\n  trivial\n\n\ntheorem b : True := trivial\nexample : 1 = 1 := rfl"
    assert build.find_examples(source) == [(3, 4), (8, 8)]


def test_metaprogram_parameters_are_one_lean_string_literal():
    params = extract.Params(roots=['weird"name', "ℕ.lemma"], virtual_roots=[{"id": "example@3", "uses": ["a\\b"]}])
    program = extract.metaprogram(params)
    literal = program.split("Json.parse ", 1)[1].split(" with", 1)[0]
    assert json.loads(json.loads(literal))["roots"] == ['weird"name', "ℕ.lemma"]
    assert "PARAMS" not in program and '"EZLOGIC_LEMMA_GRAPH "' in program


def test_include_core_turns_off_the_denylist():
    assert "congrArg" in extract.Params().to_json()["deny_names"]
    assert "Mathlib.Tactic" in extract.Params().to_json()["deny_prefixes"]
    core = extract.Params(include_core=True).to_json()
    assert core["deny_names"] == [] and core["deny_prefixes"] == []


# --- graphs from saved Lean output -------------------------------------------------------------


def test_basic_roots_in_source_order():
    g = graph_of("basic")
    assert g.roots == ["double_sum", "uses_local", "broken", "example@14", "_private.0.priv_thm"]
    assert [n.id for n in g.nodes[:5]] == g.roots
    assert node(g, "_private.0.priv_thm").label == "priv_thm"


def test_local_theorem_links_into_mathlib_and_to_other_local_theorems():
    g = graph_of("basic")
    assert {"Finset.sum_range_succ", "mul_add"} <= uses(g, "double_sum")
    assert uses(g, "uses_local") == {"double_sum"}
    n = node(g, "Finset.sum_range_succ")
    assert (n.origin, n.depth) == ("mathlib", 1)
    assert n.module.startswith("Mathlib.Algebra.BigOperators")
    assert n.statement


def test_local_nodes_carry_their_lines():
    g = graph_of("basic")
    d = node(g, "double_sum")
    assert (d.origin, d.start_line, d.end_line, d.depth) == ("local", 3, 6, 0)
    assert (node(g, "example@14").start_line, node(g, "example@14").end_line) == (14, 14)


def test_plumbing_and_tactic_internals_are_dropped():
    g = graph_of("basic")
    ids = {n.id for n in g.nodes}
    assert not ids & {"congrArg", "Eq.mpr", "of_eq_true", "eq_self", "id"}
    assert not any(i.startswith(("Mathlib.Tactic.", "Mathlib.Meta.", "Lean.")) for i in ids)


def test_instances_are_looked_through_not_shown():
    g = graph_of("basic")
    # `Distrib.leftDistribClass` is an instance (a theorem of a Prop-valued class): it is replaced
    # by the lemma it is built from.
    assert "Distrib.leftDistribClass" not in {n.id for n in g.nodes}
    assert "Distrib.left_distrib" in uses(g, "double_sum")


def test_class_fields_are_marked():
    g = graph_of("basic")
    assert node(g, "MulOneClass.mul_one").class_field
    assert not node(g, "mul_one").class_field


def test_fields_of_plain_structures_are_not_class_fields():
    g = graph_of("defs")  # `h.1` in `and_left` uses `And.left`, a field of the structure `And`
    assert "And.left" in uses(g, "and_left")
    assert not node(g, "And.left").class_field


def test_failed_proof_keeps_its_links_and_is_marked_with_sorry():
    g = graph_of("basic")
    broken = node(g, "broken")
    assert not broken.ok
    assert "Nat.add_comm" in uses(g, "broken")
    assert "sorryAx" in uses(g, "broken", "axiom")
    assert not node(g, "sorryAx").ok
    assert not g.ok
    assert [m.line for m in g.messages if m.severity == "error"] == [12]


def test_axiom_edges_reach_exactly_print_axioms():
    g = graph_of("basic")
    for n in g.nodes:
        if n.kind != "axiom" and n.axioms is not None:
            assert reachable_axioms(g, n.id) == set(n.axioms), n.id


def test_axiom_edges_are_minimal():
    g = graph_of("basic")
    # double_sum's axioms all come through its dependencies, so it has no axiom edge of its own.
    assert node(g, "double_sum").axioms == ["Classical.choice", "Quot.sound", "propext"]
    assert uses(g, "double_sum", "axiom") == set()


def test_depth_limit_marks_frontier_truncated():
    g = graph_of("basic")  # recorded with depth=2
    assert g.truncated
    for n in g.nodes:
        if n.kind == "axiom":
            continue
        assert n.depth <= 2
        if n.depth < 2:
            assert not n.truncated, n.id
    assert node(g, "Finset.sum_range_succ_comm").truncated


def test_example_with_tactics_links_to_its_lemmas():
    g = graph_of("basic")
    ex = node(g, "example@14")
    assert (ex.kind, ex.label, ex.origin) == ("example", "example (line 14)", "local")
    assert uses(g, "example@14") == {"Nat.add_comm"}


def test_term_mode_example_links_to_a_local_theorem():
    g = graph_of("defs")
    assert uses(g, "example@13") == {"double_eq"}
    assert uses(g, "example@15") == {"double_eq", "Nat.le_add_right"}


def test_equation_lemmas_of_definitions_are_not_theorems_of_the_graph():
    g = graph_of("defs")
    ids = {n.id for n in g.nodes}
    assert not any(i.startswith("double.") for i in ids)  # double.eq_1, double.eq_def
    assert uses(g, "double_mono") == {"double_eq", "Nat.add_le_add"}


def test_mutual_theorems_form_a_cycle():
    g = graph_of("mutual")
    assert "even_or_odd_odd" in uses(g, "even_or_odd_even")
    assert "even_or_odd_even" in uses(g, "even_or_odd_odd")
    assert g.ok


def test_unfinished_source_still_yields_its_theorems_and_error():
    g = graph_of("unfinished")
    assert {"fine", "example@3"} <= set(g.roots)
    assert uses(g, "example@3") == {"Nat.add_zero"}
    # The error Lean reported past the end (the comment swallowed the metaprogram) is moved
    # to the source's last line.
    assert [(m.line, m.text) for m in g.messages] == [(7, "unterminated comment")]


def test_expand_respects_node_cap_and_marks_truncated():
    _, raw = _load("expand")  # recorded with depth=3, max_nodes=12, an unknown name among roots
    g = build.assemble(build.merge_meta(raw["meta"]))
    theorems = [n for n in g.nodes if n.kind != "axiom"]
    assert len(theorems) <= 12
    assert node(g, "Finset.sum_insert").depth == 0
    assert any(n.truncated for n in theorems)
    assert "No.such_theorem" not in {n.id for n in g.nodes}


def test_merge_prefers_the_expanded_copy_of_a_node():
    a = {"nodes": [{"id": "x", "kind": "theorem", "local": False, "depth": 2, "truncated": True,
                    "uses": ["y"], "direct_axioms": [], "axioms": [], "range": None}], "axioms": []}
    b = {"nodes": [{"id": "x", "kind": "theorem", "local": False, "depth": 1, "truncated": False,
                    "uses": ["y", "z"], "direct_axioms": [], "axioms": [], "range": None}], "axioms": []}
    (m,) = build.merge_meta(a, b)["nodes"]
    assert (m["depth"], m["truncated"], m["uses"]) == (1, False, ["y", "z"])


def test_long_statements_are_shortened():
    meta = {"nodes": [{"id": "t", "kind": "theorem", "local": False, "depth": 0, "truncated": False,
                       "uses": [], "direct_axioms": [], "axioms": [], "statement": "x" * 5000,
                       "module": "Mathlib.X", "range": None}], "axioms": []}
    assert len(build.assemble(meta).nodes[0].statement) < 1600


# --- against real Lean (skipped when it isn't installed) ---------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_LEAN_TESTS") != "1" or shutil.which("lake") is None,
    reason="needs Lean and loads Mathlib (~1 min): run with RUN_LEAN_TESTS=1",
)
def test_real_lean_graph_reaches_mathlib_and_axioms():
    from agent import lean
    from lemma_graph import build_lemma_graph_sync

    source = (FIXTURES / "basic.lean").read_text()
    try:
        g = build_lemma_graph_sync(source, depth=2, max_nodes=60)
    except lean.LeanUnavailable as e:
        pytest.skip(f"Lean REPL unavailable: {e}")
    assert "Finset.sum_range_succ" in uses(g, "double_sum")
    assert set(node(g, "double_sum").axioms) == {"propext", "Classical.choice", "Quot.sound"}
    assert reachable_axioms(g, "double_sum") == set(node(g, "double_sum").axioms)
