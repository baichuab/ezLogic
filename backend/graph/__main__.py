"""Build a proof graph from the terminal (run from backend/).

    python -m graph proof.lean                            # nodes in order, with their edges
    python -m graph proof.lean --json                     # the graph as JSON
    python -m graph proof.lean --save-extraction ex.json  # also save Lean's output (test fixtures)
    python -m graph proof.lean --from-extraction ex.json  # rebuild from saved output, no Lean
"""

import argparse
import sys
from pathlib import Path

from .build import build_graph
from .extract import Extraction, ExtractionError, extract

parser = argparse.ArgumentParser(prog="python -m graph")
parser.add_argument("file", type=Path, help="Lean source file")
parser.add_argument("--json", action="store_true", help="print the graph as JSON")
parser.add_argument("--save-extraction", type=Path, metavar="PATH")
parser.add_argument("--from-extraction", type=Path, metavar="PATH")
args = parser.parse_args()

source = args.file.read_text(encoding="utf-8")
try:
    extraction = (
        Extraction.model_validate_json(args.from_extraction.read_text(encoding="utf-8"))
        if args.from_extraction
        else extract(source)
    )
except ExtractionError as e:
    sys.exit(f"Error: {e}")
if args.save_extraction:
    args.save_extraction.write_text(extraction.model_dump_json(exclude_none=True) + "\n", encoding="utf-8")

graph = build_graph(source, extraction)
if args.json:
    print(graph.model_dump_json(indent=1))
    sys.exit()

print(f"Lean {graph.lean_version} | ok: {graph.ok} | {len(graph.nodes)} nodes, {len(graph.edges)} edges")
for m in graph.messages:
    print(f"  {m.severity} at {m.start_line}:{m.start_col}: {m.text.splitlines()[0]}")
depth: dict[str, int] = {}
for n in graph.nodes:
    depth[n.id] = depth[n.parent_id] + 1 if n.parent_id else 0
    indent = "  " * depth[n.id]
    order = "  " if n.order_index is None else f"{n.order_index:>2}"
    print(f"{order} {indent}{n.kind:<11} {n.id}: {n.label}{'' if n.ok else '  [error]'}")
    for e in graph.edges:
        if e.src == n.id:
            print(f"   {indent}            {e.kind}{f'({e.label})' if e.label else ''} -> {e.dst}")
