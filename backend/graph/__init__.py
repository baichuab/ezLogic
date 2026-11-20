"""Proof graphs: split a Lean source into nodes (declarations, tactic steps, library lemmas) and
dependency edges, so a proof can be explained one piece at a time.

    graph = await create_graph(source)
"""

import asyncio

from .build import build_graph
from .extract import Extraction, ExtractionError, extract
from .model import Edge, Node, ProofGraph

# Bump when extraction or building changes the output, so anything that caches graphs (e.g. keyed
# by a hash of the source) knows to rebuild them.
GRAPH_VERSION = 1


def create_graph_sync(source: str) -> ProofGraph:
    return build_graph(source, extract(source))


async def create_graph(source: str) -> ProofGraph:
    """Elaborate `source` with Lean and build its graph. Raises `ExtractionError` if Lean can't run."""
    return await asyncio.to_thread(create_graph_sync, source)


__all__ = [
    "GRAPH_VERSION",
    "Edge",
    "Extraction",
    "ExtractionError",
    "Node",
    "ProofGraph",
    "build_graph",
    "create_graph",
    "create_graph_sync",
    "extract",
]
