"""Tool-calling agent loop backed by OpenRouter (OpenAI-compatible API)."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from config import Config

from .tools import TOOL_SCHEMAS, run_tool, serialize_result
from .workspace import Workspace

SYSTEM_PROMPT = """You are ezLogic, an assistant for mathematicians that writes and verifies \
formal proofs in Lean 4.

You work inside a local workspace directory and have tools to list, read, write, edit and \
delete files, and to verify Lean code:
- check_lean_snippet: fast check of a short self-contained snippet in a Lean REPL.
- check_lean_file: compile a .lean file in the workspace with the Lean CLI.

Workflow:
1. Understand the mathematical statement. Formalise it as a Lean 4 theorem.
2. Write the proof to a .lean file in the workspace (unless the user only wants a snippet).
3. Verify it with Lean. If there are errors, read them carefully, fix the proof, and re-check. \
Never claim a proof is verified unless the tool returned ok=true. Never leave `sorry`.
4. When done, explain the proof to the user: walk through the key code snippets, what each \
tactic or lemma does, and how it corresponds to the informal mathematical argument.

If a Lean tool reports that Lean is not installed, tell the user, and still show your best \
attempt at the proof clearly marked as unverified."""


@dataclass
class AgentResult:
    reply: str
    messages: list[
        dict
    ]  # full conversation (without system prompt), to send back next turn
    tool_calls: list[dict] = field(
        default_factory=list
    )  # trace of tool calls this turn
    finished: bool = True  # False if max steps reached


class ProofAgent:
    def __init__(self, workspace: Workspace, model: str | None = None):
        if not Config.OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set (see backend/.env.example)"
            )
        self.workspace = workspace
        self.model = model or Config.OPENROUTER_MODEL
        self.client = AsyncOpenAI(
            base_url=Config.OPENROUTER_BASE_URL,
            api_key=Config.OPENROUTER_API_KEY,
            default_headers={"HTTP-Referer": Config.FRONTEND_URL, "X-Title": "ezLogic"},
        )

    async def stream(
        self, user_message: str, history: list[dict] | None = None
    ) -> AsyncIterator[dict]:
        """Run one user turn, yielding events as they happen.

        Event types:
          {"type": "token", "content": str}
          {"type": "tool_call_start", "id": str, "name": str}
          {"type": "tool_result", "id": str, "name": str, "arguments": dict, "result": Any}
          {"type": "done", "reply": str, "messages": list, "tool_calls": list, "finished": bool}
        """
        messages = list(history or []) + [{"role": "user", "content": user_message}]
        trace: list[dict] = []

        for _ in range(Config.AGENT_MAX_STEPS):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                tools=TOOL_SCHEMAS,
                stream=True,
            )

            content_parts: list[str] = []
            # tool call fragments keyed by index: {"id", "name", "arguments"}
            pending: dict[int, dict] = {}

            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                if delta.content:
                    content_parts.append(delta.content)
                    yield {"type": "token", "content": delta.content}

                for tc in delta.tool_calls or []:
                    entry = pending.setdefault(
                        tc.index,
                        {"id": "", "name": "", "arguments": "", "announced": False},
                    )
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            entry["name"] += tc.function.name
                        if tc.function.arguments:
                            entry["arguments"] += tc.function.arguments
                    if not entry["announced"] and entry["name"]:
                        entry["announced"] = True
                        yield {
                            "type": "tool_call_start",
                            "id": entry["id"],
                            "name": entry["name"],
                        }

            content = "".join(content_parts)
            tool_calls = [pending[i] for i in sorted(pending)]

            assistant: dict = {"role": "assistant", "content": content}
            if tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant)

            if not tool_calls:
                yield {
                    "type": "done",
                    "reply": content,
                    "messages": messages,
                    "tool_calls": trace,
                    "finished": True,
                }
                return

            for tc in tool_calls:
                try:
                    args = json.loads(tc["arguments"] or "{}")
                    result = await run_tool(self.workspace, tc["name"], args)
                except json.JSONDecodeError as e:
                    args, result = {}, {"error": f"Invalid JSON arguments: {e}"}
                call = {"name": tc["name"], "arguments": args, "result": result}
                trace.append(call)
                yield {"type": "tool_result", "id": tc["id"], **call}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": serialize_result(result),
                    }
                )

        yield {
            "type": "done",
            "reply": "Stopped: reached the maximum number of agent steps.",
            "messages": messages,
            "tool_calls": trace,
            "finished": False,
        }

    async def run(
        self,
        user_message: str,
        history: list[dict] | None = None,
        on_tool_call: Callable[[dict], None] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> AgentResult:
        """Run one user turn to completion (non-streaming wrapper around `stream`).

        `on_tool_call` is called after each tool executes and `on_token` for each
        text delta (for live logging).
        """
        async for event in self.stream(user_message, history):
            kind = event["type"]
            if kind == "token" and on_token:
                on_token(event["content"])
            elif kind == "tool_result" and on_tool_call:
                on_tool_call(
                    {k: event[k] for k in ("name", "arguments", "result")}
                )
            elif kind == "done":
                return AgentResult(
                    reply=event["reply"],
                    messages=event["messages"],
                    tool_calls=event["tool_calls"],
                    finished=event["finished"],
                )
        raise RuntimeError("Agent stream ended without a 'done' event")


# --- CLI for manual testing ---------------------------------------------------------
# Run from backend/:
#   python -m agent                          # interactive chat
#   python -m agent "prove that 2 + 2 = 4"   # single prompt
#   python -m agent --model openai/gpt-4o "..."


def _print_tool_call(call: dict, max_len: int = 400) -> None:
    args = json.dumps(call["arguments"], ensure_ascii=False)
    result = json.dumps(call["result"], ensure_ascii=False)
    if len(args) > max_len:
        args = args[:max_len] + "..."
    if len(result) > max_len:
        result = result[:max_len] + "..."
    print(f"\033[36m  -> {call['name']}({args})\033[0m")
    print(f"\033[90m     {result}\033[0m")


async def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Chat with the ezLogic proof agent.")
    parser.add_argument(
        "prompt", nargs="*", help="Single prompt to run (omit for interactive mode)"
    )
    parser.add_argument(
        "--model", help=f"OpenRouter model (default: {Config.OPENROUTER_MODEL})"
    )
    args = parser.parse_args(argv)

    workspace = Workspace(Config.WORKSPACE_DIR)
    try:
        agent = ProofAgent(workspace, model=args.model)
    except RuntimeError as e:
        raise SystemExit(f"Error: {e}")

    print(f"ezLogic agent | model: {agent.model} | workspace: {workspace.root}")

    async def turn(prompt: str, history: list[dict]) -> list[dict]:
        print("\033[1magent>\033[0m ", end="", flush=True)
        messages = history
        async for event in agent.stream(prompt, history):
            kind = event["type"]
            if kind == "token":
                print(event["content"], end="", flush=True)
            elif kind == "tool_result":
                print()
                _print_tool_call(event)
            elif kind == "done":
                if not event["finished"]:
                    print(event["reply"], end="")
                messages = event["messages"]
        print("\n")
        return messages

    if args.prompt:
        await turn(" ".join(args.prompt), [])
        return

    print("Commands: /files, /reset, /exit\n")
    history: list[dict] = []
    while True:
        try:
            prompt = input("\033[1myou>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            continue
        if prompt in ("/exit", "/quit"):
            break
        if prompt == "/reset":
            history = []
            print("(conversation cleared)")
            continue
        if prompt == "/files":
            print("\n".join(workspace.list_files()) or "(workspace is empty)")
            continue
        try:
            history = await turn(prompt, history)
        except Exception as e:  # API errors etc. -- keep the session alive
            print(f"\033[31merror: {type(e).__name__}: {e}\033[0m")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
