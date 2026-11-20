"""Tool-calling agent loop backed by OpenRouter (OpenAI-compatible API)."""

import json
from collections.abc import Callable
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

    async def run(
        self,
        user_message: str,
        history: list[dict] | None = None,
        on_tool_call: Callable[[dict], None] | None = None,
    ) -> AgentResult:
        """Run one user turn. `on_tool_call` is called after each tool executes (for live logging)."""
        messages = list(history or []) + [{"role": "user", "content": user_message}]
        trace: list[dict] = []

        for _ in range(Config.AGENT_MAX_STEPS):
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                tools=TOOL_SCHEMAS,
            )
            msg = completion.choices[0].message

            assistant: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant)

            if not msg.tool_calls:
                return AgentResult(
                    reply=msg.content or "", messages=messages, tool_calls=trace
                )

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = await run_tool(self.workspace, tc.function.name, args)
                except json.JSONDecodeError as e:
                    args, result = {}, {"error": f"Invalid JSON arguments: {e}"}
                call = {"name": tc.function.name, "arguments": args, "result": result}
                trace.append(call)
                if on_tool_call:
                    on_tool_call(call)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": serialize_result(result),
                    }
                )

        return AgentResult(
            reply="Stopped: reached the maximum number of agent steps.",
            messages=messages,
            tool_calls=trace,
            finished=False,
        )


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
        result = await agent.run(prompt, history, on_tool_call=_print_tool_call)
        print(f"\n\033[1magent>\033[0m {result.reply}\n")
        return result.messages

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
