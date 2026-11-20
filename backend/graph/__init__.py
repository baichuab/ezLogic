"""Proof graphs: split a Lean source into declarations, tactic steps and library lemmas, linked by
their dependencies. See README.md.

    graph = await create_graph(source)
"""

import asyncio

from .build import build_graph
from .extract import Extraction, ExtractionError, extract
from .model import Edge, LeanMessage, Node, ProofGraph

# Bump when the output changes, so anything caching graphs (e.g. by source hash) rebuilds them.
GRAPH_VERSION = 5


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
    "LeanMessage",
    "Node",
    "ProofGraph",
    "build_graph",
    "create_graph",
    "create_graph_sync",
    "extract",
]
