"""Graph contract, verifier failures, and HTTP authorization (no LLM calls)."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

import main
from agent import graph


def example_graph():
    return graph.ProofGraph.model_validate({"root_node_id": "A", "nodes": [
        {"node_id": "A", "depends_on_ids": ["B"], "kind": "theorem", "proof_dependency_ids": ["B"]},
        {"node_id": "B", "depends_on_ids": None, "kind": "theorem"},
    ]})


def test_graph_validation_and_unknown_frontier():
    g = example_graph()
    assert g.nodes[1].depends_on_ids is None
    for bad in [
        {"root_node_id": "missing", "nodes": [n.model_dump() for n in g.nodes]},
        {"root_node_id": "A", "nodes": [g.nodes[0].model_dump()]},
        {"root_node_id": "A", "nodes": [n.model_dump() for n in g.nodes] * 2},
    ]:
        with pytest.raises(ValueError):
            graph.ProofGraph.model_validate(bad)


def response(*, error=False, sorries=None, env=1, messages=None):
    return SimpleNamespace(has_errors=lambda: error, sorries=sorries or [], env=env, messages=messages or [])


def test_extractor_uses_checked_environment_and_exact_source(monkeypatch):
    calls = []
    payload = example_graph().model_dump()
    outputs = [response(env=42), response(messages=[SimpleNamespace(data=graph.MARKER + json.dumps(payload), severity="info")])]
    def run(command, **kwargs):
        calls.append(command)
        return outputs.pop(0)
    monkeypatch.setattr(graph.lean, "_get_server", lambda: SimpleNamespace(run=run))
    monkeypatch.setattr(graph.lean, "_get_base_env", lambda _: 7)
    result = graph._extract("import Mathlib\ntheorem ezlogic_main : True := True.intro")
    assert result.root_node_id == "A"
    assert calls[0].env == 7
    assert "theorem ezlogic_main" in calls[0].cmd
    assert calls[1].env == 42
    assert "getUsedConstantsAsSet" in calls[1].cmd


@pytest.mark.parametrize("failed", [response(error=True), response(sorries=["unproved"])])
def test_rejected_proof_never_reaches_extractor(monkeypatch, failed):
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return failed
    monkeypatch.setattr(graph.lean, "_get_server", lambda: SimpleNamespace(run=run))
    monkeypatch.setattr(graph.lean, "_get_base_env", lambda _: 0)
    assert asyncio.run(graph.extract_graph("theorem bad : False := by sorry")) is None
    assert len(calls) == 1


def test_graph_endpoint_is_scoped_to_guest_and_handles_missing_data(monkeypatch):
    query_id = str(uuid4())
    owner = None
    async def lookup(user, query):
        nonlocal owner
        if owner is None:
            owner = user
        return {"query_id": query, **example_graph().model_dump()} if user == owner else None
    async def no_source(user, query):
        return None
    monkeypatch.setattr(main.db, "get_graph", lookup)
    monkeypatch.setattr(main.db, "get_graph_source", no_source)
    async def check():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as a:
            await a.post('/api/session')
            r = await a.get(f'/api/queries/{query_id}/graph')
            assert r.status_code == 200
            assert r.json()["nodes"][1]["depends_on_ids"] is None
            assert (await a.get('/api/queries/not-a-uuid/graph')).status_code == 422
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as b:
            await b.post('/api/session')
            assert (await b.get(f'/api/queries/{query_id}/graph')).status_code == 404
    asyncio.run(check())


def test_graph_database_failure_returns_safe_error(monkeypatch):
    async def fail(*_):
        raise RuntimeError('private database details')
    monkeypatch.setattr(main.db, 'get_graph', fail)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            r = await client.get(f'/api/queries/{uuid4()}/graph')
            assert r.status_code == 503
            assert 'private database details' not in r.text
    asyncio.run(check())


def test_retry_builds_graph_from_owned_snapshot(monkeypatch):
    from agent import envelope

    query_id = str(uuid4())
    source = "theorem ezlogic_main : True := True.intro"
    snapshot = envelope.encode(source, None)
    owner = None
    saved = None

    async def read_source(user, key):
        nonlocal owner
        assert key == query_id
        if owner is None:
            owner = user
        return snapshot if user == owner else None

    async def read_graph(user, key):
        return saved if user == owner else None

    async def extract(code):
        assert code == source
        return example_graph()

    async def save(user, key, response, extracted):
        nonlocal saved
        assert user == owner and key == query_id and response == snapshot
        assert saved is None
        saved = {"query_id": key, **extracted.model_dump()}

    monkeypatch.setattr(main.db, "get_graph_source", read_source)
    monkeypatch.setattr(main.db, "get_graph", read_graph)
    monkeypatch.setattr(main.db, "save_missing_graph", save)
    monkeypatch.setattr(main, "extract_graph", extract)

    async def check():
        transport = httpx.ASGITransport(app=main.app)
        path = f"/api/queries/{query_id}/graph"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as a:
            await a.post('/api/session')
            missing_graph = await a.get(path)
            assert missing_graph.status_code == 200
            assert missing_graph.json() is None
            built = await a.post(path)
            assert built.status_code == 200
            assert (await a.get(path)).json() == built.json()
            assert (await a.post(path)).json() == built.json()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as stranger:
            inaccessible = await stranger.get(path)
            assert inaccessible.status_code == 404
            assert inaccessible.json() == {"detail": main.PROOF_UNAVAILABLE}
            assert (await stranger.post(path)).status_code == 404

    asyncio.run(check())
