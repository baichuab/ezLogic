"""Tests for agent/envelope.py and the stored-response helpers in main.py."""

import json

from agent import envelope
from agent.agent import turns_to_messages

LEAN = "import Mathlib\n\ntheorem t : True := trivial"
EXPL = {"intro": "Short.", "steps": [{"id": "s1", "kind": "theorem", "leanLines": [3, 3]}]}


def test_round_trip():
    assert envelope.decode(envelope.encode(LEAN, EXPL)) == (LEAN, EXPL)


def test_round_trip_without_explanation():
    assert envelope.decode(envelope.encode(LEAN, None)) == (LEAN, None)


def test_legacy_plain_lean_row():
    assert envelope.decode(LEAN) == (LEAN, None)


def test_malformed_or_foreign_json_is_treated_as_legacy():
    for text in ['{"v": 1, "lean": ', '{"v": 2, "lean": "x"}', '{"lean": 3, "v": 1}', "[1, 2]"]:
        assert envelope.decode(text) == (text, None)


def test_empty():
    assert envelope.decode("") == ("", None)
    assert envelope.decode(None) == ("", None)


def test_explanation_fence_is_parseable_json_block():
    fence = envelope.explanation_fence(EXPL)
    assert fence.startswith("```json\n") and fence.endswith("\n```")
    assert json.loads(fence[len("```json\n") : -len("\n```")]) == EXPL


def test_turns_to_messages_replays_only_the_lean():
    msgs = turns_to_messages(
        [{"query": "q1", "response": envelope.encode(LEAN, EXPL)}, {"query": "q2", "response": LEAN}]
    )
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    for m in (msgs[1], msgs[3]):
        assert LEAN in m["content"]
        assert '"steps"' not in m["content"]
