"""Opt-in real REPL tests; no model call and no Mathlib-sized memory footprint.

RUN_LEAN_GRAPH_TESTS=1, LEAN_GRAPH_REPL_DIR=<built REPL project>.
Uses the installed Lake executable configured in .env.
"""
import os

import pytest

from agent import graph
from config import Config

pytestmark = pytest.mark.skipif(os.getenv('RUN_LEAN_GRAPH_TESTS') != '1', reason='Requires built Lean REPL')


@pytest.fixture(scope='module')
def server():
    from lean_interact import LeanServer, LeanREPLConfig, Command
    config = LeanREPLConfig(local_repl_path=os.environ['LEAN_GRAPH_REPL_DIR'],
                            build_repl=False, lake_path=Config.LAKE_PATH)
    instance = LeanServer(config)
    try:
        loaded = instance.run(Command(cmd='import Lean'), timeout=90)
        assert not loaded.has_errors()
        yield instance, loaded.env
    finally:
        instance.kill()


def use_server(monkeypatch, server):
    instance, base = server
    monkeypatch.setattr(graph.lean, '_get_server', lambda: instance)
    monkeypatch.setattr(graph.lean, '_get_base_env', lambda _: base)


def test_real_declaration_edges_are_extracted_by_lean(monkeypatch, server):
    use_server(monkeypatch, server)
    result = graph._extract('''
private theorem leaf : True := True.intro
theorem helper : True := leaf
theorem ezlogic_main (_h : helper = helper) : True := leaf
''')
    nodes = {n.node_id: n for n in result.nodes}
    assert result.root_node_id == 'ezlogic_main'
    assert 'helper' in nodes['ezlogic_main'].depends_on_ids
    leaf = next(n for n in result.nodes if n.lean_name == 'leaf')
    assert nodes['ezlogic_main'].proof_dependency_ids == [leaf.node_id]
    assert nodes['helper'].proof_dependency_ids == [leaf.node_id]
    assert leaf.kind == 'theorem'
    assert leaf.proof_dependency_ids == []
    assert nodes['True.intro'].kind == 'technical'


@pytest.mark.parametrize('source', [
    'theorem ezlogic_main : False := by rfl',
    'theorem ezlogic_main : False := by sorry',
    'axiom fake : False\ntheorem ezlogic_main : False := fake',
    'example : True := True.intro',
    'theorem a : True := True.intro\ntheorem b : True := True.intro',
])
def test_real_invalid_or_ambiguous_proof_has_no_graph(monkeypatch, server, source):
    use_server(monkeypatch, server)
    with pytest.raises(ValueError):
        graph._extract(source)


def test_namespaced_main_and_snapshot_isolation(monkeypatch, server):
    use_server(monkeypatch, server)
    result = graph._extract('namespace Demo\ntheorem ezlogic_main : True := True.intro\nend Demo')
    assert result.root_node_id == 'Demo.ezlogic_main'
    assert not any(n.node_id == 'helper' for n in result.nodes)
