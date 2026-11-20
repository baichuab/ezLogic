"""Tool definitions (OpenAI function-calling format) and their implementations."""

import json
from typing import Any

from . import lean
from .workspace import Workspace, WorkspaceError

MAX_TOOL_OUTPUT = 20_000


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_PATH = {"type": "string", "description": "Path relative to the workspace root"}

TOOL_SCHEMAS = [
    _fn(
        "list_files",
        "List all files in the workspace (recursively), or under a subdirectory.",
        {"path": {**_PATH, "description": "Directory to list (default: workspace root)"}},
        [],
    ),
    _fn("read_file", "Read the full contents of a file.", {"path": _PATH}, ["path"]),
    _fn(
        "write_file",
        "Create or overwrite a file with the given content. Parent directories are created.",
        {"path": _PATH, "content": {"type": "string"}},
        ["path", "content"],
    ),
    _fn(
        "edit_file",
        "Replace one exact, unique occurrence of old_string with new_string in a file.",
        {
            "path": _PATH,
            "old_string": {"type": "string", "description": "Exact text to replace"},
            "new_string": {"type": "string", "description": "Replacement text"},
        },
        ["path", "old_string", "new_string"],
    ),
    _fn("delete_file", "Delete a file.", {"path": _PATH}, ["path"]),
    _fn(
        "check_lean_file",
        "Check a .lean file in the workspace in the Lean REPL (Mathlib preloaded) and return Lean's messages. "
        "Only Mathlib/Std/Lean/Batteries imports are supported. "
        "Use this to verify complete proofs. A proof is only verified if ok=true.",
        {"path": _PATH},
        ["path"],
    ),
    _fn(
        "check_lean_snippet",
        "Quickly check a short, self-contained Lean 4 snippet in a Lean REPL (no file needed). "
        "Good for testing a lemma, tactic, or #check/#eval before writing it to a file. Mathlib "
        "is already imported in this REPL; any `import` line in the snippet is simply ignored.",
        {"code": {"type": "string", "description": "Lean 4 source code"}},
        ["code"],
    ),
]


async def run_tool(workspace: Workspace, name: str, args: dict[str, Any]) -> dict:
    """Execute a tool call. Always returns a JSON-serialisable dict."""
    try:
        match name:
            case "list_files":
                return {"files": workspace.list_files(args.get("path", "."))}
            case "read_file":
                return {"content": workspace.read_file(args["path"])}
            case "write_file":
                return {"result": workspace.write_file(args["path"], args["content"])}
            case "edit_file":
                return {
                    "result": workspace.edit_file(
                        args["path"], args["old_string"], args["new_string"]
                    )
                }
            case "delete_file":
                return {"result": workspace.delete_file(args["path"])}
            case "check_lean_file":
                return (await lean.check_file(workspace, args["path"])).to_dict()
            case "check_lean_snippet":
                return (await lean.check_snippet(args["code"])).to_dict()
            case _:
                return {"error": f"Unknown tool: {name}"}
    except (WorkspaceError, KeyError) as e:
        return {"error": f"{type(e).__name__}: {e}"}


def serialize_result(result: dict) -> str:
    text = json.dumps(result, ensure_ascii=False)
    if len(text) > MAX_TOOL_OUTPUT:
        text = text[:MAX_TOOL_OUTPUT] + "... [truncated]"
    return text
