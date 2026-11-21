"""Re-record the Lean output the lemma_graph tests run on. Needs Lean; run from backend/:

    python tests/fixtures/lemma_graph/regenerate.py

Do this after changing the metaprogram (lemma_graph/extract.py), then check the tests still pass.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from lemma_graph import build, extract  # noqa: E402

HERE = pathlib.Path(__file__).parent
DEPTH, MAX_NODES = 2, 40


def main() -> None:
    for src_path in sorted(HERE.glob("*.lean")):
        source = src_path.read_text()
        raw = extract.run_source(source, extract.Params(depth=DEPTH, max_nodes=MAX_NODES), timeout=300)
        local_ids = {build._unescape(n["id"]) for n in (raw.meta or {}).get("nodes", []) if n.get("local")}
        examples, _ = build.example_roots(source, raw.tactics, local_ids)
        example_meta = None
        if examples:
            example_meta = extract.run_meta(
                extract.Params(
                    depth=DEPTH,
                    max_nodes=MAX_NODES,
                    local_roots=False,
                    virtual_roots=[{"id": e["id"], "uses": e["uses"]} for e in examples],
                ),
                timeout=300,
            )
        data = {
            "params": {"depth": DEPTH, "max_nodes": MAX_NODES},
            "meta": raw.meta,
            "example_meta": example_meta,
            "messages": [m.model_dump(mode="json") for m in raw.messages],
            "tactics": [t.model_dump(mode="json") for t in raw.tactics],
        }
        (HERE / f"{src_path.stem}.raw.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
        print(f"{src_path.name}: {len((raw.meta or {}).get('nodes', []))} nodes, {len(examples)} examples")

    meta = extract.run_meta(
        extract.Params(depth=3, max_nodes=12, local_roots=False, roots=["Finset.sum_insert", "No.such_theorem"]),
        timeout=300,
    )
    (HERE / "expand.raw.json").write_text(json.dumps({"meta": meta}, ensure_ascii=False, indent=1))
    print(f"expand: {len(meta['nodes'])} nodes")


if __name__ == "__main__":
    main()
