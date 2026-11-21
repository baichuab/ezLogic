"""Opt-in local Postgres integration: RUN_GRAPH_DB_TESTS=1 python -m pytest ..."""
import asyncio
import os
from uuid import uuid4

import httpx
import pytest

import db
import main
from agent.graph import ProofGraph

pytestmark = pytest.mark.skipif(os.getenv('RUN_GRAPH_DB_TESTS') != '1', reason='Requires local PostgreSQL')


def test_atomic_graph_storage_and_guest_isolation():
    async def check():
        await db.init_db()
        await db.init_db()  # migration must be repeatable on an existing database
        query_id = None
        marker = f'graph-integration-{uuid4()}'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as owner:
            await owner.post('/api/session')
            import jwt
            from config import Config
            user = jwt.decode(owner.cookies['ezlogic_guest'], Config.GUEST_JWT_SECRET, algorithms=['HS256'])['sub']
            payload = ProofGraph.model_validate({'root_node_id': 'A', 'nodes': [
                {'node_id': 'A', 'depends_on_ids': ['B', 'C']},
                {'node_id': 'B', 'depends_on_ids': ['D']},
                {'node_id': 'C', 'depends_on_ids': []},
                {'node_id': 'D', 'depends_on_ids': None},
            ]})
            try:
                query_id = await db.insert_turn(user, str(uuid4()), 'integration-test', marker, 'snapshot', [], graph=payload)
                r = await owner.get(f'/api/queries/{query_id}/graph')
                assert r.status_code == 200
                assert r.json()['root_node_id'] == 'A'
                assert len(r.json()['nodes']) == 4
                assert r.json()['nodes'][3]['depends_on_ids'] is None
                assert r.json()['nodes'][0]['kind'] is None
                upgraded = ProofGraph.model_validate({'root_node_id': 'A', 'nodes': [
                    {**n.model_dump(), 'kind': 'theorem', 'proof_dependency_ids': n.depends_on_ids}
                    for n in payload.nodes
                ]})
                await db.save_missing_graph(user, query_id, 'different snapshot', upgraded)
                assert (await owner.get(f'/api/queries/{query_id}/graph')).json()['nodes'][0]['kind'] is None
                await db.save_missing_graph(user, query_id, 'snapshot', upgraded)
                await db.save_missing_graph(user, query_id, 'snapshot', upgraded)
                data = (await owner.get(f'/api/queries/{query_id}/graph')).json()
                assert data['nodes'][0]['kind'] == 'theorem'
                assert data['nodes'][0]['proof_dependency_ids'] == ['B', 'C']
                # Verify authorization in the actual SQL, not just in a mocked lookup.
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as stranger:
                    assert (await stranger.get(f'/api/queries/{query_id}/graph')).status_code == 404
                invalid = ProofGraph.model_construct(root_node_id='missing', nodes=payload.nodes)
                with pytest.raises(ValueError):
                    await db.insert_turn(user, str(uuid4()), 'integration-test', marker + '-invalid', '', [], graph=invalid)
                async with await db._connect() as conn:
                    result = await conn.execute('select count(*) as n from queries where query = %s', (marker + '-invalid',))
                    assert (await result.fetchone())['n'] == 0
            finally:
                if query_id:
                    async with await db._connect() as conn:
                        await conn.execute('delete from chat_turns where query_id = %s', (query_id,))
                        await conn.execute('delete from queries where query_id = %s', (query_id,))
                        result = await conn.execute('select count(*) as n from proof_nodes where query_id = %s', (query_id,))
                        assert (await result.fetchone())['n'] == 0
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(check())
