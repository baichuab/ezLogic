"""Recheck an immutable source snapshot and extract declaration edges inside Lean."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from config import Config
from . import lean

log = logging.getLogger(__name__)
EXTRACTOR = Path(__file__).with_name("graph_extract.lean").read_text(encoding="utf-8")
MARKER = "EZLOGIC_GRAPH_JSON:"


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1)
    depends_on_ids: list[str] | None
    lean_name: str = ""
    statement: str = ""
    kind: Literal["theorem", "technical"] | None = None
    proof_dependency_ids: list[str] | None = None


class ProofGraph(BaseModel):
    root_node_id: str
    nodes: list[GraphNode] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def valid_references(self):
        by_id = {n.node_id: n for n in self.nodes}
        if len(by_id) != len(self.nodes) or self.root_node_id not in by_id:
            raise ValueError("Duplicate graph node or missing root")
        for n in self.nodes:
            if n.depends_on_ids is not None:
                n.depends_on_ids = list(dict.fromkeys(n.depends_on_ids))
                if not set(n.depends_on_ids) <= by_id.keys():
                    raise ValueError("Graph contains missing dependency nodes")
            if n.proof_dependency_ids is not None:
                n.proof_dependency_ids = list(dict.fromkeys(n.proof_dependency_ids))
                if (n.kind != "theorem"
                    or not set(n.proof_dependency_ids) <= set(n.depends_on_ids or [])
                    or any(by_id[dep].kind != "theorem" for dep in n.proof_dependency_ids)):
                    raise ValueError("Proof edges must be direct references between named theorems or lemmas")
        return self


class GraphResponse(ProofGraph):
    query_id: str

    @property
    def has_proof_view(self) -> bool:
        return any(n.kind == "theorem" and n.node_id == self.root_node_id for n in self.nodes)


def _extract(code: str) -> ProofGraph:
    from lean_interact import Command
    from lean_interact.interface import LeanError

    if lean._unsupported_imports(code):
        raise ValueError("Unsupported proof imports")
    # Serialize the check + extraction so the returned environment cannot be
    # interleaved with another verifier operation. Source is a string snapshot.
    with lean._operation_lock:
        server = lean._get_server()
        base = lean._get_base_env(server)
        if base is None:
            loaded = server.run(Command(cmd="import Lean"), timeout=Config.LEAN_STARTUP_TIMEOUT)
            if isinstance(loaded, LeanError) or loaded.has_errors():
                raise ValueError("Unable to load Lean graph support")
            base = loaded.env
        checked = server.run(Command(cmd=lean._without_imports(code), env=base), timeout=Config.LEAN_TIMEOUT)
        if isinstance(checked, LeanError) or checked.has_errors() or checked.sorries or checked.env is None:
            raise ValueError("Final proof source did not pass Lean verification")
        result = server.run(Command(cmd=EXTRACTOR, env=checked.env), timeout=Config.LEAN_TIMEOUT)
        if isinstance(result, LeanError):
            raise ValueError(result.message)
        if result.has_errors():
            raise ValueError("; ".join(m.data for m in result.messages if m.severity == "error"))
        payloads = [m.data[len(MARKER):] for m in result.messages if m.data.startswith(MARKER)]
        if len(payloads) != 1:
            raise ValueError("Lean did not return one graph payload")
        return ProofGraph.model_validate(json.loads(payloads[0]))


async def extract_graph(code: str) -> ProofGraph | None:
    """Graph failure never replaces the proof reply or changes its verified badge."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_extract, code), Config.LEAN_STARTUP_TIMEOUT)
    except Exception as exc:
        log.warning("Dependency graph unavailable: %s: %s", type(exc).__name__, exc)
        return None
