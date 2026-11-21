"""Tests for the pure parts of agent/agent.py."""

from agent.agent import _tool_ok, _last_lean_error, _stopped_reply


def test_stop_message_includes_actual_latest_diagnostics():
    trace = [{"name": "check_lean_file", "result": {"ok": False, "messages": [
        {"severity": "error", "line": 5, "message": "Unknown identifier `obtain`"}
    ]}}]
    assert "Line 5: Unknown identifier `obtain`" in _stopped_reply("step limit", trace)
    assert "UNVERIFIED" in _stopped_reply("failure limit", trace, "UNVERIFIED attempt")


def test_successful_recheck_does_not_report_previous_error():
    trace = [{"name": "check_lean_file", "result": {"ok": False, "error": "old error"}},
             {"name": "check_lean_file", "result": {"ok": True}}]
    assert _last_lean_error(trace) == ""
    assert _stopped_reply("step limit", trace) == "Stopped: step limit."


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
