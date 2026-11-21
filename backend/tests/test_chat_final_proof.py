import asyncio
import json
from uuid import uuid4

import httpx

import main
from agent import AgentResult, Workspace, lean


def check_call(code: str, ok: bool = True) -> dict:
    return {
        "name": "check_lean_snippet",
        "arguments": {"code": code},
        "result": {"ok": ok, "source_hash": lean.source_hash(code),
                   "proof_candidate": lean.is_proof_candidate(code)},
    }


def test_later_probe_does_not_replace_proof(tmp_path):
    proof = "import Mathlib\n\ntheorem ezlogic_main : True := by trivial"
    probe = "import Mathlib\n/- Example description /- nested -/\ntheorem pretend : True\n-/\n#eval Nat.factorization 6"
    calls = [check_call(proof), check_call(probe)]
    assert not calls[-1]["result"]["proof_candidate"]
    code, path = main._extract_lean(AgentResult("", [], calls), Workspace(tmp_path))
    assert (code, path) == (proof, None)
    assert main._final_source_check(calls, code, path) is calls[0]


def test_file_edit_invalidates_previous_check(tmp_path):
    workspace = Workspace(tmp_path)
    original = "theorem ezlogic_main : True := True.intro"
    updated = "theorem ezlogic_main : False := True.intro"
    workspace.write_file("Proof.lean", updated)
    call = {"name": "check_lean_file", "arguments": {"path": "Proof.lean"},
            "result": {"ok": True, "source_hash": lean.source_hash(original)}}
    code, path = main._extract_lean(AgentResult("", [], [call]), workspace)
    assert (code, path) == (updated, "Proof.lean")
    assert main._final_source_check([call], code, path) is None


def test_probe_only_turn_skips_explanation_and_cache(monkeypatch):
    probe = check_call("import Mathlib\n#eval Nat.factorization 6")

    class ProbeAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        async def stream(self, *_args):
            yield {"type": "done", "finished": True, "reply": "Done.",
                   "messages": [], "tool_calls": [probe]}

    async def empty_history(*_args):
        return []

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Diagnostic command reached the proof pipeline")

    monkeypatch.setattr(main, "ProofAgent", ProbeAgent)
    monkeypatch.setattr(main, "ExplainerAgent", unexpected)
    monkeypatch.setattr(main, "extract_graph", unexpected)
    monkeypatch.setattr(main.db, "insert_turn", unexpected)
    monkeypatch.setattr(main.db, "list_history", empty_history)

    async def run():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            result = await client.post("/api/chat", json={
                "chat_id": str(uuid4()), "text": "Prove the theorem", "allowBuild": True,
            }, headers={"Cookie": "ezlogic_guest=stale"})
            assert result.cookies.get("ezlogic_guest")
            renewed = await client.post("/api/session")
            assert renewed.status_code == 204
            assert "set-cookie" not in renewed.headers
        assert result.status_code == 200
        event = json.loads(result.text.removeprefix("data: "))
        assert event["type"] == "done"
        assert event["finished"] is False
        assert event["verified"] is False
        assert event["query_id"] is None
        assert event["response"] == ""
        assert "stopped before submitting a Lean proof" in event["reply"]

    asyncio.run(run())
