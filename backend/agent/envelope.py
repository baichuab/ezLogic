"""What `queries.response` stores: the Lean source plus its explanation.

New rows hold a versioned JSON envelope:

    {"v": 1, "lean": "<Lean source>", "explanation": {"intro": ..., "steps": [...]} | null}

Rows written before the explaining agent existed hold plain Lean source;
`decode` treats anything that isn't a valid v1 envelope that way, so old rows
keep working without a migration.
"""

import json
from typing import Any

VERSION = 1


def encode(lean: str, explanation: dict[str, Any] | None) -> str:
    return json.dumps(
        {"v": VERSION, "lean": lean, "explanation": explanation}, ensure_ascii=False
    )


def decode(text: str | None) -> tuple[str, dict[str, Any] | None]:
    """Return `(lean, explanation)` for a stored `response` value."""
    if not text:
        return "", None
    if not text.lstrip().startswith("{"):
        return text, None
    try:
        obj = json.loads(text)
    except ValueError:
        return text, None
    if (
        not isinstance(obj, dict)
        or obj.get("v") != VERSION
        or not isinstance(obj.get("lean"), str)
    ):
        return text, None
    explanation = obj.get("explanation")
    return obj["lean"], explanation if isinstance(explanation, dict) else None


def explanation_fence(explanation: dict[str, Any]) -> str:
    """The explanation as the ```json block the frontend's `fromReply` parses."""
    return "```json\n" + json.dumps(explanation, ensure_ascii=False) + "\n```"
