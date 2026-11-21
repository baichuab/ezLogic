"""Print the lemma dependency graph of a Lean file (from backend/):

    python -m lemma_graph proof.lean [--depth 3] [--max-nodes 300] [--include-core] [--json]
    python -m lemma_graph --expand Finset.sum_insert [--depth 2]
"""

import argparse
import logging
import sys

from . import LeanUnavailable, build_lemma_graph_sync, expand_lemma_graph_sync
from .model import LemmaGraph


def _print(graph: LemmaGraph) -> None:
    uses: dict[str, list[str]] = {}
    for e in graph.edges:
        uses.setdefault(e.src, []).append(e.dst)
    for m in graph.messages:
        print(f"[{m.severity}] line {m.line}: {m.text.splitlines()[0] if m.text else ''}")
    for note in graph.notes:
        print(f"note: {note}")
    print(f"ok={graph.ok} truncated={graph.truncated} roots={graph.roots}")
    print(f"{len(graph.nodes)} nodes, {len(graph.edges)} edges\n")
    for n in graph.nodes:
        flags = "".join(
            [
                "+" if n.truncated else " ",
                "!" if not n.ok else " ",
            ]
        )
        depth = "  " if n.depth is None else f"d{n.depth}"
        where = f"lines {n.start_line}-{n.end_line}" if n.start_line else (n.module or "")
        print(f"{depth} {flags} {n.kind:<7} {n.label}  [{n.origin}] {where}")
        for dst in uses.get(n.id, []):
            print(f"          -> {dst}")
    print("\n+ = dependencies not followed (depth/node limit)   ! = error or sorry")


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m lemma_graph", description=__doc__.splitlines()[0])
    parser.add_argument("file", nargs="?", help="Lean source file")
    parser.add_argument("--expand", nargs="+", metavar="NAME", help="library theorems to start from instead")
    parser.add_argument("--depth", type=int)
    parser.add_argument("--max-nodes", type=int)
    parser.add_argument("--include-core", action="store_true", help="keep plumbing/tactic-internal lemmas")
    parser.add_argument("--json", action="store_true", help="print the raw graph as JSON")
    args = parser.parse_args()
    if not args.file and not args.expand:
        parser.error("give a Lean file or --expand NAME")
    logging.basicConfig(level=logging.WARNING)

    opts = dict(depth=args.depth, max_nodes=args.max_nodes, include_core=args.include_core)
    try:
        if args.expand:
            graph = expand_lemma_graph_sync(args.expand, **opts)
        else:
            with open(args.file, encoding="utf-8") as f:
                graph = build_lemma_graph_sync(f.read(), **opts)
    except LeanUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(graph.model_dump_json(indent=2))
    else:
        _print(graph)
    return 0


if __name__ == "__main__":
    sys.exit(main())
