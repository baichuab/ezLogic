"""Tests for backend/graph. The fixtures are real Lean output saved with
`python -m graph tests/fixtures/<name>.lean --save-extraction tests/fixtures/<name>.extraction.json`,
so these run without Lean. The last test runs Lean itself and is skipped if it is not installed.
"""

import importlib
import json
import shutil
from pathlib import Path

import pytest

from config import Config
from graph import Extraction, build_graph, create_graph_sync, declaration_graph, extract
from graph.build import display_name, is_interesting
from graph.extract import MARKER, ConstantInfo, source_messages
from lean_interact.interface import CommandResponse, LeanError, Message, Pos
from graph.goals import case_tag, case_tags, continues, hypothesis_names

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
    marker = Message(start_pos=Pos(line=60, column=0), severity="info", data=MARKER + "{}")
    kept = source_messages([inside, msg, info, marker], last_line=3, meta_ran=False)
    assert [(m.data, m.start_pos.line) for m in kept] == [("kept as is", 2), ("unterminated comment", 3)]
    # When the metaprogram ran, anything past the end is about the metaprogram, not the source.
    assert [m.data for m in source_messages([inside, msg, marker], last_line=3, meta_ran=True)] == ["kept as is"]


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


def test_goals_after_without_bullets():
    """`exact hp` after `constructor`, without bullets, closes `left` but leaves `right` open.
    Hand-written extraction (Lean's positions are one line down because of `import Lean`)."""
    source = "theorem t (p q : Prop) (hp : p) (hq : q) : p ∧ q := by\n  constructor\n  exact hp\n  exact hq\n"
    hyps = "p q : Prop\nhp : p\nhq : q\n"
    left, right = f"case left\n{hyps}⊢ p", f"case right\n{hyps}⊢ q"

    def pos(line, column):
        return {"line": line + 1, "column": column}

    def tactic(line, end_col, goals, text):
        return {"start_pos": pos(line, 2), "end_pos": pos(line, end_col), "goals": goals, "tactic": text,
                "proof_state": 0, "used_constants": []}

    ex = Extraction.model_validate({
        "declarations": [{"name": "t", "kind": "theorem", "range": {"synthetic": False, "start": pos(1, 0), "finish": pos(4, 10)}}],
        "tactics": [
            tactic(2, 13, f"{hyps}⊢ p ∧ q", "constructor"),
            tactic(3, 10, f"{left}\n\n{right}", "exact hp"),
            tactic(4, 10, right, "exact hq"),
        ],
        "messages": [],
        "local_constants": None,
    })
    nodes = {n.id: n for n in build_graph(source, ex).nodes}
    assert nodes["decl:t/1"].goals_after == f"{left}\n\n{right}"
    assert nodes["decl:t/2"].goals_after == right  # not "": `right` is still open
    assert nodes["decl:t/3"].goals_after == ""


def test_goals_after_with_bullets():
    """A bullet or `induction` alternative sees only its own goal, so it ends with no goals left."""
    _, nodes, _ = load("branches")
    assert nodes["decl:and_swap/4"].goals_after == ""  # · exact hq
    _, nodes, _ = load("basic")
    assert nodes["decl:add_zero'/2"].goals_after == ""  # | zero => rfl


def _pos(line, column):
    """A position in the source, in Lean's numbering (one line down because of `import Lean`)."""
    return {"line": line + 1, "column": column}


def _tactic(line, start, end, goals, text, used=()):
    return {"start_pos": _pos(line, start), "end_pos": _pos(line, end), "goals": goals, "tactic": text,
            "proof_state": 0, "used_constants": list(used)}


def _decl(name, kind, start, end):
    return {"name": name, "kind": kind, "range": {"synthetic": False, "start": _pos(*start), "finish": _pos(*end)}}


def _lemma(name, kind="theorem"):
    return {"name": name, "canonical": name, "kind": kind}


def test_statements_are_full_types():
    """The REPL only reports the part after the colon; nodes show the whole type."""
    _, nodes, _ = load("basic")
    assert nodes["decl:sum_le"].statement == "∀ (a b c : Nat), a ≤ b → b ≤ c → double a ≤ 2 * c"
    assert nodes["decl:double"].statement == "Nat → Nat"
    _, nodes, _ = load("branches")
    assert nodes["decl:example"].statement  # Lean keeps no constant for examples: the REPL's text


def test_goals_after_swap():
    """After `swap` both goals are still open, in the new order."""
    source = "theorem t (p q : Prop) (hp : p) (hq : q) : p ∧ q := by\n  constructor\n  swap\n  exact hq\n  exact hp\n"
    hyps = "p q : Prop\nhp : p\nhq : q\n"
    left, right = f"case left\n{hyps}⊢ p", f"case right\n{hyps}⊢ q"
    ex = Extraction.model_validate({
        "declarations": [_decl("t", "theorem", (1, 0), (5, 10))],
        "tactics": [
            _tactic(2, 2, 13, f"{hyps}⊢ p ∧ q", "constructor"),
            _tactic(3, 2, 6, f"{left}\n\n{right}", "swap"),
            _tactic(4, 2, 10, f"{right}\n\n{left}", "exact hq"),
            _tactic(5, 2, 10, left, "exact hp"),
        ],
        "messages": [],
        "local_constants": None,
    })
    nodes = {n.id: n for n in build_graph(source, ex).nodes}
    assert case_tags(nodes["decl:t/2"].goals_after) == ["right", "left"]  # was only ["right"]
    assert nodes["decl:t/3"].goals_after == left
    assert nodes["decl:t/4"].goals_after == ""


def test_lemmas_in_the_term_part_of_a_proof():
    """A proof that is a term with a `by` block inside: the lemma named in the term part is linked
    to the declaration; one only a tactic used behind the scenes is not."""
    source = "theorem m (a b : Nat) (h : a ≤ b) : a ≤ b + 1 ∧ True :=\n  ⟨Nat.le_succ_of_le h, by trivial⟩\n"
    line = source.split("\n")[1]
    start = line.index("trivial")
    ex = Extraction.model_validate({
        "declarations": [_decl("m", "theorem", (1, 0), (2, len(line)))],
        "tactics": [_tactic(2, start, start + len("trivial"), "⊢ True", "trivial", ["True.intro"])],
        "messages": [],
        "local_constants": {"m": {"name": "m", "kind": "theorem", "uses": ["Nat.le_succ_of_le", "Nat.lt_irrefl", "True.intro"]}},
        "constants": {
            "Nat.le_succ_of_le": _lemma("Nat.le_succ_of_le"),
            "Nat.lt_irrefl": _lemma("Nat.lt_irrefl"),
            "True.intro": _lemma("True.intro", "constructor"),
        },
    })
    edges = {(e.src, e.dst) for e in build_graph(source, ex).edges}
    assert edges == {("decl:m", "ext:Nat.le_succ_of_le")}


def test_examples_link_the_declarations_they_name():
    """Lean keeps no constant for an example, so its edges come from the names in its code."""
    source = "theorem two : 1 + 1 = 2 := rfl\nexample : 1 + 1 = 2 := two\n"
    ex = Extraction.model_validate({
        "declarations": [_decl("two", "theorem", (1, 0), (1, 30)), _decl("_example", "example", (2, 0), (2, 26))],
        "tactics": [],
        "messages": [],
        "local_constants": {"two": {"name": "two", "kind": "theorem", "uses": ["rfl"]}},
    })
    edges = {(e.src, e.dst, e.kind) for e in build_graph(source, ex).edges}
    assert edges == {("decl:example", "decl:two", "uses")}


def test_only_real_declarations_are_recovered():
    """Constants with a source range that the REPL did not report: declarations in a `mutual`
    block are recovered; a derived instance and a `notation` parser are not."""
    source = (
        "structure P where\n  x : Nat\n  deriving Repr\n\n"
        'notation "⟪" a "⟫" => P.mk a\n\n'
        "mutual\n  def ev : Nat → Bool\n    | 0 => true\n    | n + 1 => od n\n"
        "  def od : Nat → Bool\n    | 0 => false\n    | n + 1 => ev n\nend\n"
    )
    lines = source.split("\n")

    def rng(line, col, end_line):  # [line, col, end line, end col], in Lean's numbering
        return [line + 1, col, end_line + 1, len(lines[end_line - 1])]

    ex = Extraction.model_validate({
        "declarations": [_decl("P", "structure", (1, 0), (3, 15))],
        "tactics": [],
        "messages": [],
        "local_constants": {
            "P": {"name": "P", "kind": "inductive", "uses": [], "range": rng(1, 0, 3)},
            "instReprP": {"name": "instReprP", "kind": "definition", "uses": [], "range": [4, 11, 4, 15]},
            "«term⟪_⟫»": {"name": "«term⟪_⟫»", "kind": "definition", "uses": [], "range": rng(5, 0, 5)},
            "ev": {"name": "ev", "kind": "definition", "uses": ["od"], "range": rng(8, 2, 10)},
            "od": {"name": "od", "kind": "definition", "uses": ["ev"], "range": rng(11, 2, 13)},
        },
    })
    graph = build_graph(source, ex)
    assert [n.id for n in graph.nodes if n.kind == "declaration"] == ["decl:P", "decl:ev", "decl:od"]


def test_generated_declarations_are_left_out():
    """The REPL reports the parsers and macros `notation` and `macro` generate as definitions
    (seen with Lean 4.36); only declarations the source writes become nodes."""
    source = (
        'notation "⟪" a "⟫" => Prod.mk a a\n\n'
        'macro "twice" t:tactic : tactic => `(tactic| ($t; $t))\n\n'
        "set_option maxHeartbeats 400000 in\n/-- doc -/\n@[simp] private theorem a : 1 = 1 := rfl\n\n"
        "example : 2 = 2 := rfl\n"
    )
    ex = Extraction.model_validate({
        "declarations": [
            _decl("«term⟪_⟫»", "definition", (1, 0), (1, 33)),
            _decl("«_aux___macroRules_term⟪_⟫_1»", "definition", (1, 0), (1, 33)),
            _decl("_aux___unexpand_Prod_mk_1", "definition", (1, 0), (1, 33)),
            _decl("tacticTwice_", "definition", (3, 0), (3, 54)),
            _decl("a", "theorem", (5, 0), (7, 41)),
            _decl("_example", "example", (9, 0), (9, 22)),
        ],
        "tactics": [],
        "messages": [],
        "local_constants": None,
    })
    assert [n.id for n in build_graph(source, ex).nodes] == ["decl:a", "decl:example"]


def test_private_declarations():
    """Lean names `private theorem p1` `_private.0.p1` (seen with Lean 4.36); the node shows `p1`."""
    source = "private theorem p1 : 1 = 1 := rfl\ntheorem p2 : 1 = 1 := by\n  exact p1\n"
    ex = Extraction.model_validate({
        "declarations": [_decl("_private.0.p1", "theorem", (1, 0), (1, 34)), _decl("p2", "theorem", (2, 0), (3, 10))],
        "tactics": [_tactic(3, 2, 10, "⊢ 1 = 1", "exact p1", ["_private.0.p1"])],
        "messages": [],
        "local_constants": {
            "_private.0.p1": {"name": "_private.0.p1", "kind": "theorem", "uses": ["rfl"]},
            "p2": {"name": "p2", "kind": "theorem", "uses": ["_private.0.p1"]},
        },
    })
    graph = build_graph(source, ex)
    edges = {(e.src, e.dst) for e in graph.edges}
    assert ("decl:p2", "decl:p1") in edges and ("decl:p2/1", "decl:p1") in edges
    assert display_name("_private.Foo.Bar.0.Baz.qux") == "Baz.qux" and display_name("Nat.add") == "Nat.add"


def _fake_lean(monkeypatch, *responses):
    """Replace the REPL with canned responses (an Exception is raised instead); returns the list of
    commands sent."""
    ext = importlib.import_module("graph.extract")
    sent, queue = [], list(responses)

    def run_command(cmd):
        sent.append(cmd)
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        if set(r) == {"message"}:  # the REPL's own error, e.g. "Unknown environment."
            return LeanError(message=r["message"])
        return CommandResponse.model_validate(r)

    monkeypatch.setattr(ext.shutil, "which", lambda _: "lake")
    monkeypatch.setattr(ext.lean, "run_command", run_command)
    return sent


def _meta_message(meta):
    return {"pos": {"line": 1, "column": 0}, "severity": "info", "data": MARKER + json.dumps(meta)}


_SOURCE = "theorem t (a b c : Nat) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c := by\n  exact Nat.le_trans h1 h2\n"
_TACTIC = _tactic(2, 2, 26, "⊢ a ≤ c", "exact Nat.le_trans h1 h2", ["Nat.le_trans", "t"])
_META_OUT = {
    "lean_version": "4.0.0",
    "locals": [{"name": "t", "kind": "theorem", "uses": ["Nat.le_trans"]}],
    "constants": [_lemma("Nat.le_trans")],
}


def test_extract_is_one_command(monkeypatch):
    """Normally the source and the metaprogram go to Lean as one command, so a REPL restart between
    commands (lean-interact restarts it when memory is high) can't lose anything."""
    sent = _fake_lean(monkeypatch, {"env": 7, "tactics": [_TACTIC], "messages": [_meta_message(_META_OUT)]})
    ex = extract(_SOURCE)
    assert len(sent) == 1
    assert sent[0].cmd.startswith("import Lean\n" + _SOURCE + "\n\n") and MARKER in sent[0].cmd
    assert set(ex.local_constants) == {"t"} and set(ex.constants) == {"Nat.le_trans"}
    assert ex.lean_version == "4.0.0"


def test_extract_recovers_a_swallowed_metaprogram(monkeypatch):
    """When the end of the source swallows the metaprogram, it runs again on the saved state."""
    swallowed = {"pos": {"line": 40, "column": 0}, "severity": "error", "data": "unterminated comment"}
    sent = _fake_lean(
        monkeypatch,
        {"env": 7, "tactics": [_TACTIC], "messages": [swallowed]},
        {"env": 8, "messages": [_meta_message(_META_OUT)]},
    )
    ex = extract(_SOURCE + "/- oops\n")
    assert sent[1].env == 7 and MARKER in sent[1].cmd
    assert set(ex.local_constants) == {"t"}
    # Moved to the source's last line (line 4, which is 5 in Lean's numbering with `import Lean`).
    assert [(m.data, m.start_pos.line) for m in ex.messages] == [("unterminated comment", 5)]


def test_extract_survives_a_restarted_repl(monkeypatch):
    """If the saved state is gone (the REPL restarted), the graph is still built without declaration
    dependencies, and the tactics' lemmas are classified in a fresh command."""
    sent = _fake_lean(
        monkeypatch,
        {"env": 7, "tactics": [_TACTIC], "messages": []},  # metaprogram swallowed
        {"message": "Unknown environment."},
        {"env": 9, "messages": [_meta_message({"lean_version": "4.0.0", "locals": [], "constants": [_lemma("Nat.le_trans")]})]},
    )
    ex = extract(_SOURCE)
    assert sent[2].env is None and sent[2].cmd.startswith("import Lean\n")
    assert ex.local_constants is None
    assert "Nat.le_trans" in ex.constants
    assert len(ex.tactics) == 1


def test_extract_survives_a_failed_classification(monkeypatch):
    """Classifying the lemmas of failed declarations is optional; if it fails, the graph is kept."""
    meta = {**_META_OUT, "locals": [], "constants": []}  # `t` failed: its lemmas are missing
    sent = _fake_lean(
        monkeypatch,
        {"env": 7, "tactics": [_TACTIC], "messages": [_meta_message(meta)]},
        RuntimeError("timeout"),
    )
    ex = extract(_SOURCE)
    assert len(sent) == 2 and ex.lean_version == "4.0.0" and len(ex.tactics) == 1


def test_declaration_graph():
    """Declarations only, each with the declarations it uses directly and the lemmas it uses."""
    graph, _, _ = load("mutual")
    decls = {d.name: d for d in declaration_graph(graph).declarations}
    assert {n: d.depends_on for n, d in decls.items()} == {
        "helper": [],
        "helper_pos": ["helper"],
        "isEven": ["isOdd"],  # the `mutual` cycle
        "isOdd": ["isEven"],
        "isEven_zero": ["isEven"],
        "uses_both": ["helper", "helper_pos", "isOdd"],  # in walkthrough order
    }
    graph, _, _ = load("basic")
    decls = {d.name: d for d in declaration_graph(graph).declarations}
    assert decls["sum_le"].depends_on == ["double", "double_eq"]
    assert decls["sum_le"].lemmas == ["Nat.le_trans"]  # used by a step, counted for the declaration
    assert decls["sum_le"].statement.startswith("∀ (a b c : Nat)")
    assert decls["double"].kind == "definition" and decls["double_eq"].kind == "theorem"


@pytest.mark.parametrize("name", ["basic", "branches", "sorry", "mutual"])
def test_declaration_graph_is_well_formed(name):
    graph, _, _ = load(name)
    decls = declaration_graph(graph).declarations
    assert [d.order_index for d in decls] == sorted(d.order_index for d in decls)
    by_name = {d.name: d for d in decls}
    for d in decls:
        assert set(d.depends_on) <= set(by_name) and d.name not in d.depends_on
        for dep in d.depends_on:  # dependencies come first, except inside a `mutual` cycle
            assert by_name[dep].order_index < d.order_index or d.name in by_name[dep].depends_on


def test_declaration_graph_counts_steps():
    """Dependencies found only by tactic steps still count, e.g. when the metaprogram did not run or
    a failed declaration lost its proof to `sorry`."""
    source = (FIXTURES / "basic.lean").read_text(encoding="utf-8")
    ex = Extraction.model_validate_json((FIXTURES / "basic.extraction.json").read_text(encoding="utf-8"))
    ex.local_constants = None
    decls = {d.name: d for d in declaration_graph(build_graph(source, ex)).declarations}
    assert decls["double_add"].depends_on == ["double_eq"]  # from `rw [double_eq, ...]`


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

    # An unfinished proof at the end: the graph is still built, with the error on the source.
    graph = create_graph_sync("theorem a : 1 = 1 := rfl\ntheorem b : 1 = 1 := by\n")
    assert not graph.ok and "decl:a" in {n.id for n in graph.nodes}
    assert all(m.start_line <= 3 for m in graph.messages)

    # Derived instances, notation and macros are not declaration nodes; an instance is.
    graph = create_graph_sync(
        'structure P where\n  x : Nat\n  deriving Repr\n\nnotation "⟪" a "⟫" => P.mk a\n\n'
        'macro "twice" t:tactic : tactic => `(tactic| ($t; $t))\n\n'
        "instance : Inhabited P := ⟨⟨0⟩⟩\n\ntheorem uses_it : (⟪1⟫ : P).x = 1 := by\n  twice rfl\n"
    )
    assert [n.id for n in graph.nodes if n.kind == "declaration"] == ["decl:P", "decl:instInhabitedP", "decl:uses_it"]


@pytest.mark.skipif(not shutil.which(Config.LAKE_PATH), reason="Lean (lake) is not installed")
def test_live_private_declaration():
    graph = create_graph_sync("private theorem p1 : 1 = 1 := rfl\ntheorem p2 : 1 = 1 := p1\n")
    edges = {(e.src, e.dst) for e in graph.edges}
    assert ("decl:p2", "decl:p1") in edges
