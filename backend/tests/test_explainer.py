"""Tests for agent/explainer.py (no network: the LLM call is stubbed)."""

import asyncio
import json

import pytest

from agent import explainer as ex
from config import Config

LEAN = "import Mathlib\n\ntheorem t (n : ℕ) : n + 0 = n := by\n  simp"


def test_number_lines_matches_frontend_split():
    out = ex.number_lines("a\n\nb")
    assert out.split("\n") == ["1| a", "2| ", "3| b"]
    wide = ex.number_lines("\n".join(["x"] * 10)).split("\n")
    assert wide[0] == " 1| x" and wide[9] == "10| x"


def test_parse_json_variants():
    obj = {"steps": []}
    assert ex.parse_json(json.dumps(obj)) == obj
    assert ex.parse_json("```json\n" + json.dumps(obj) + "\n```") == obj
    assert ex.parse_json("Sure! " + json.dumps(obj) + " Done.") == obj
    assert ex.parse_json("not json") is None


def test_validate_coerces_and_clamps():
    out = ex.validate(
        {
            "intro": " Hi. ",
            "steps": [
                {"id": "s1", "kind": "theorem", "title": "A", "statementTex": "$x=1$", "summary": "s",
                 "leanLines": [3, 3]},
                {"id": "s1", "kind": "nonsense", "title": "B", "summary": "s", "leanLines": [9, 2]},
                {"kind": "step", "title": "C", "summary": "s", "leanLines": [50, 60]},
                {"kind": "step", "title": "D", "summary": "s", "leanLines": ["x", 1]},
                {"title": "", "summary": ""},
                "garbage",
            ],
        },
        n_lines=4,
    )
    assert out["intro"] == "Hi."
    steps = out["steps"]
    assert [s["title"] for s in steps] == ["A", "B", "C", "D"]
    assert len({s["id"] for s in steps}) == 4
    assert steps[0]["statementTex"] == "x=1"
    assert steps[0]["leanLines"] == [3, 3]
    assert steps[1]["kind"] == "step"
    assert steps[1]["leanLines"] == [2, 4]  # swapped, then clamped
    assert "leanLines" not in steps[2]  # entirely out of range
    assert "leanLines" not in steps[3]
    assert steps[1]["explanation"] == "s"  # falls back to summary


def test_validate_rejects_unusable():
    assert ex.validate(None, 3) is None
    assert ex.validate({"steps": []}, 3) is None
    assert ex.validate({"intro": "x"}, 3) is None


def test_describe_check_reports_diagnostics():
    calls = [
        {"name": "check_lean_file", "arguments": {}, "result": {
            "ok": False, "messages": [{"severity": "error", "line": 4, "column": 2, "message": "unsolved goals"}],
            "error": None}},
    ]
    text = ex.describe_check(calls, finished=False)
    assert "FAILED" in text and "gave up" in text and "line 4" in text
    assert "passed" in ex.describe_check([{"name": "check_lean_snippet", "result": {"ok": True}}], True)
    assert "No Lean check" in ex.describe_check([], True)


class _Stub(ex.ExplainerAgent):
    def __init__(self, replies):
        self.model = "stub"
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def _complete(self, messages):
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


GOOD = json.dumps({"intro": "Proof.", "steps": [
    {"id": "s1", "kind": "theorem", "title": "Statement", "summary": "s", "leanLines": [3, 3]},
    {"id": "s2", "kind": "conclusion", "title": "Simp", "summary": "s", "leanLines": [4, 4]},
]})


def _run(agent, **kw):
    async def go():
        return [e async for e in agent.stream("prove it", LEAN, **kw)]
    return asyncio.run(go())


def test_stream_frames_a_json_fence_and_returns_explanation():
    agent = _Stub([GOOD])
    events = _run(agent, writer_reply="Here:\n```lean\nfoo\n```", tool_calls=[])
    assert events[0] == {"type": "token", "content": "\n\n```json\n"}
    assert events[1] == {"type": "token", "content": "\n```"}
    assert events[2]["type"] == "explanation"
    assert [s["id"] for s in events[2]["explanation"]["steps"]] == ["s1", "s2"]
    prompt = agent.calls[0][-1]["content"]
    assert "3| theorem t" in prompt and "```lean" not in prompt


def test_stream_retries_once_then_gives_up():
    agent = _Stub(["nope", GOOD])
    assert _run(agent)[-1]["explanation"] is not None
    assert len(agent.calls) == 2

    agent = _Stub(["nope", "still nope"])
    assert _run(agent)[-1]["explanation"] is None


def test_stream_swallows_errors(monkeypatch):
    monkeypatch.setattr(Config, "EXPLAIN_TIMEOUT", 5)
    events = _run(_Stub([RuntimeError("boom")]))
    assert events[-1] == {"type": "explanation", "explanation": None}
    assert events[1]["content"] == "\n```"  # fence is still closed


@pytest.mark.parametrize("reply,expected_prefix", [
    ("Done.\n```json\n{\"old\": 1}\n```\nBye", "Done.\n\nBye"),
    ("", "```json"),
])
def test_compose_reply(reply, expected_prefix):
    import main
    out = main._compose_reply(reply, {"steps": [{"id": "s1"}]})
    assert out.startswith(expected_prefix)
    assert '"old"' not in out
    assert out.count("```json") == 1
    assert main._compose_reply("unchanged", None) == "unchanged"
