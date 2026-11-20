"""Tests for the pure parts of agent/agent.py."""

from agent.agent import _tool_ok


def test_ok_field_wins_even_when_falsy():
    assert _tool_ok({"ok": True, "output": ""}) is True
    assert _tool_ok({"ok": False, "output": "error: ..."}) is False


def test_ok_field_wins_over_a_present_but_null_error():
    # LeanResult.to_dict() always includes "error", null on success -- "ok" must
    # still decide the outcome, not the mere presence of the "error" key.
    assert _tool_ok({"ok": True, "error": None}) is True


def test_falls_back_to_a_truthy_error_when_there_is_no_ok_field():
    assert _tool_ok({"error": "WorkspaceError: no such file"}) is False
    assert _tool_ok({"error": None}) is True


def test_no_ok_or_error_field_has_no_pass_fail_concept():
    assert _tool_ok({"result": "wrote 12 bytes"}) is None
    assert _tool_ok({"files": ["a.lean"]}) is None
