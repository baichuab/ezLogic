"""Lemma dependency graph: which theorems a Lean proof relies on, which theorems those rely on, and
so on into Mathlib, down to the axioms. See README.md.

    graph = await build_lemma_graph(lean_source)            # LemmaGraph (pydantic)
    more = await expand_lemma_graph(["Finset.sum_insert"])  # the chain below truncated nodes
"""

import asyncio
import logging
import time

from agent.lean import LeanUnavailable
from config import Config

from . import build, extract
from .model import LeanMessage, LemmaEdge, LemmaGraph, LemmaNode

log = logging.getLogger(__name__)

__all__ = [
    "LeanMessage",
    "LeanUnavailable",
    "LemmaEdge",
    "LemmaGraph",
    "LemmaNode",
    "build_lemma_graph",
    "build_lemma_graph_sync",
    "expand_lemma_graph",
    "expand_lemma_graph_sync",
]


def _clamp(depth: int | None, max_nodes: int | None) -> tuple[int, int]:
    depth = Config.LEMMA_GRAPH_DEPTH if depth is None else depth
    max_nodes = Config.LEMMA_GRAPH_MAX_NODES if max_nodes is None else max_nodes
    return (
        max(1, min(depth, Config.LEMMA_GRAPH_DEPTH_LIMIT)),
        max(1, min(max_nodes, Config.LEMMA_GRAPH_NODES_LIMIT)),
    )


def build_lemma_graph_sync(
    source: str,
    *,
    depth: int | None = None,
    max_nodes: int | None = None,
    include_core: bool = False,
) -> LemmaGraph:
    """Elaborate `source` and build its lemma graph. Blocking; raises `LeanUnavailable`."""
    depth, max_nodes = _clamp(depth, max_nodes)
    t0 = time.monotonic()
    params = extract.Params(depth=depth, max_nodes=max_nodes, include_core=include_core)
    raw = extract.run_source(source, params, timeout=Config.LEMMA_GRAPH_TIMEOUT)
    notes: list[str] = []

    if raw.meta is None:
        notes.append(
            "Lean could not read the source's own theorems: the end of the source looks "
            "unfinished (an unclosed comment or proof). Only examples are shown."
        )
    local_ids = {build._unescape(n["id"]) for n in (raw.meta or {}).get("nodes", []) if n.get("local")}

    # Examples have no constant, so their dependencies are resolved separately, from the
    # constants their tactics used and the names in their text.
    examples, example_edges = build.example_roots(source, raw.tactics, local_ids)
    example_meta = None
    if examples:
        budget = max(1, max_nodes - len((raw.meta or {}).get("nodes", [])))
        try:
            example_meta = extract.run_meta(
                extract.Params(
                    depth=depth,
                    max_nodes=budget,
                    local_roots=False,
                    virtual_roots=[{"id": e["id"], "uses": e["uses"]} for e in examples],
                    include_core=include_core,
                ),
                timeout=Config.LEMMA_GRAPH_TIMEOUT,
            )
        except LeanUnavailable as e:
            log.warning("lemma graph: examples could not be resolved: %s", e)
            notes.append("The dependencies of the source's examples could not be resolved.")
            examples, example_edges = [], []

    graph = build.assemble(
        build.merge_meta(raw.meta, example_meta),
        messages=raw.messages,
        examples=examples,
        extra_edges=example_edges,
        notes=notes,
    )
    log.info(
        "lemma graph: %d nodes, %d edges, truncated=%s, depth=%d, elapsed=%.1fs",
        len(graph.nodes), len(graph.edges), graph.truncated, depth, time.monotonic() - t0,
    )
    return graph


def expand_lemma_graph_sync(
    names: list[str],
    *,
    depth: int | None = None,
    max_nodes: int | None = None,
    include_core: bool = False,
) -> LemmaGraph:
    """The dependency chain below existing (library) theorems, e.g. a graph's truncated nodes.
    The given theorems are the roots, at depth 0; the caller offsets depths when merging.
    Theorems of a submitted source can't be expanded this way, but they never need to be: the
    source's own theorems are always fully expanded. Blocking; raises `LeanUnavailable`."""
    depth, max_nodes = _clamp(depth, max_nodes)
    meta = extract.run_meta(
        extract.Params(
            depth=depth,
            max_nodes=max_nodes,
            local_roots=False,
            roots=names,
            include_core=include_core,
        ),
        timeout=Config.LEMMA_GRAPH_TIMEOUT,
    )
    graph = build.assemble(build.merge_meta(meta))
    found = {n.id for n in graph.nodes}
    missing = [n for n in names if n not in found]
    graph.roots = [n for n in names if n in found]
    if missing:
        graph.notes.append(f"Not found in Mathlib: {', '.join(missing)}")
    return graph


async def _in_thread(fn, *args, **kwargs) -> LemmaGraph:
    try:
        # Safety net on top of the REPL's own per-command timeout, as in agent/lean.py.
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=Config.LEAN_STARTUP_TIMEOUT + 2 * Config.LEMMA_GRAPH_TIMEOUT,
        )
    except asyncio.TimeoutError as e:
        raise LeanUnavailable("Building the lemma graph timed out") from e


async def build_lemma_graph(source: str, **kwargs) -> LemmaGraph:
    return await _in_thread(build_lemma_graph_sync, source, **kwargs)


async def expand_lemma_graph(names: list[str], **kwargs) -> LemmaGraph:
    return await _in_thread(expand_lemma_graph_sync, names, **kwargs)
