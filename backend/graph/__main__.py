"""Build a proof graph from the terminal.

    python -m graph proof.lean                  # print nodes in explanation order, with edges
    python -m graph proof.lean --json           # print the graph as JSON
    python -m graph proof.lean --save-extraction ex.json   # also save Lean's raw output (test fixtures)
    python -m graph proof.lean --from-extraction ex.json   # rebuild from saved output, without Lean
"""

import argparse
import json
import sys
from pathlib import Path

from .build import build_graph
from .extract import Extraction, ExtractionError, extract


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m graph", description=__doc__.split("\n\n")[0])
    parser.add_argument("file", type=Path, help="Lean source file")
    parser.add_argument("--json", action="store_true", help="print the graph as JSON")
    parser.add_argument("--save-extraction", type=Path, metavar="PATH")
    parser.add_argument("--from-extraction", type=Path, metavar="PATH")
    args = parser.parse_args()

    source = args.file.read_text(encoding="utf-8")
    if args.from_extraction:
        extraction = Extraction.from_dict(json.loads(args.from_extraction.read_text(encoding="utf-8")))
    else:
        try:
            extraction = extract(source)
        except ExtractionError as e:
            sys.exit(f"Error: {e}")
    if args.save_extraction:
        args.save_extraction.write_text(
            json.dumps(extraction.to_dict(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    graph = build_graph(source, extraction)
    if args.json:
        print(json.dumps(graph.to_dict(), indent=1, ensure_ascii=False))
        return

    print(f"Lean {graph.lean_version} | ok: {graph.ok} | {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    for m in graph.messages:
        print(f"  {m['severity']} at {m['start_line']}:{m['start_col']}: {m['text'].splitlines()[0]}")
    out: dict[str, list[str]] = {}
    for e in graph.edges:
        out.setdefault(e.src, []).append(f"{e.kind}{f'({e.label})' if e.label else ''} -> {e.dst}")
    depth = {}
    for n in graph.nodes:
        depth[n.id] = depth.get(n.parent_id, -1) + 1 if n.parent_id else 0
        order = "  " if n.order_index is None else f"{n.order_index:>2}"
        flag = "" if n.ok else "  [error]"
        print(f"{order} {'  ' * depth[n.id]}{n.kind:<11} {n.id}: {n.label}{flag}")
        for line in out.get(n.id, []):
            print(f"   {'  ' * depth[n.id]}            {line}")


if __name__ == "__main__":
    main()
