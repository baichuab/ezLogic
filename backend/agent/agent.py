"""Tool-calling agent loop backed by OpenRouter (OpenAI-compatible API)."""

import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from config import Config

from . import envelope
from .tools import TOOL_SCHEMAS, run_tool, serialize_result
from .workspace import Workspace

log = logging.getLogger(__name__)


def _last_lean_error(trace: list[dict]) -> str:
    """Report the latest check's actual diagnostics, never an older resolved error."""
    for call in reversed(trace):
        if call.get("name") not in ("check_lean_file", "check_lean_snippet"):
            continue
        result = call.get("result") or {}
        if _tool_ok(result):
            if result.get("proof_candidate") is False:
                continue
            return ""
        parts = [str(result["error"])] if result.get("error") else []
        for msg in result.get("messages", []):
            if isinstance(msg, dict) and msg.get("severity") == "error":
                location = f"Line {msg['line']}: " if msg.get("line") is not None else ""
                parts.append(location + str(msg.get("message", "")))
        return "\n".join(parts)[:4000]
    return ""


def _stopped_reply(reason: str, trace: list[dict], reply: str = "") -> str:
    error = _last_lean_error(trace)
    text = reply.strip() or f"Stopped: {reason}."
    return f"{text}\n\nLast Lean error:\n{error}" if error else text


def _tool_ok(result: dict) -> bool | None:
    """Pass/fail for a log line, matching how the frontend reads a tool result
    (api.ts's toolSucceeded): `ok` wins when present (Lean checks), else a truthy
    `error` means failure, else there's no pass/fail concept for this tool."""
    if "ok" in result:
        return bool(result["ok"])
    if "error" in result:
        return not result["error"]
    return None

SYSTEM_PROMPT = """You are ezLogic, an assistant for mathematicians that writes and verifies \
formal proofs in Lean 4.

You work inside a local workspace directory and have tools to list, read, write, edit and \
delete files, and to verify Lean code:
- check_lean_snippet: fast check of a short self-contained snippet in a Lean REPL. Mathlib is \
already imported for you in this REPL; any `import` line you include is ignored, not an error.
- check_lean_file: check a .lean file in the workspace, in the same REPL. Start the file with \
`import Mathlib`; only Mathlib, Std, Lean and Batteries imports are supported. A proof is only \
verified once check_lean_file returns ok=true on the final file.

Write Lean 4 only. This is NOT Lean 3: never write `begin ... end`, never separate tactics with \
commas, never write a tactic block as `{ ... }`. Tactics are separated by newlines (or `<;>`). \
Case split with `induction n with | zero => ... | succ k ih => ...`, not `induction n with k hk`.

Lean 4 syntax reminders:
- Tactics such as `obtain`, `rw`, `exact`, and `ring` must be inside a `by` block.
- Use newline-separated tactics, never `obtain ... := h,` or `show ..., from ...`.
- A term-mode let uses `let h := value; body` or a newline, not Lean 3's `let ... in`.
- Keep number types consistent: use integer identities for Int goals, not Nat lemmas.
- If you don't know a library name, write the goal as a Lean theorem and try `exact?`
  or `apply?` so Lean searches for a match. Use `#check` for specific names when helpful.
  Diagnostic commands such as `#check` and `#eval` do not verify the requested proof.

For example, this is valid Lean 4 tactic syntax:
theorem example_reorder {P Q : Prop} (h : P ∧ Q) : Q ∧ P := by
  obtain ⟨hp, hq⟩ := h
  exact ⟨hq, hp⟩

For prime-number questions, the predicate is Nat.Prime. In this Mathlib version,
Nat.exists_infinite_primes (n + 1) gives ∃ p, n + 1 ≤ p ∧ Nat.Prime p.
Destructure this result and prove the requested bound; do not return it unchanged
when the requested conjunction order or bound is different.

Workflow:
1. Understand the mathematical statement. Formalise it as a Lean 4 theorem named ezlogic_main.
Use other names for helper lemmas. The final theorem must be named, not an anonymous example,
so Lean can extract its declaration dependency graph. Do not invent dependency lists.
2. Write the proof to a .lean file in the workspace (unless the user only wants a snippet).
3. Verify it with Lean. If there are errors, read them carefully, fix the proof, and re-check. \
Never claim a proof is verified unless the tool returned ok=true. Never leave `sorry`.
4. If the same approach fails twice in a row, change strategy instead of making small edits: try \
a different tactic (`simp`, `norm_num`, `omega`, `ring`, `decide`), look up the right lemma \
instead of guessing its name, or restate the goal in an equivalent, simpler form.
5. When done, explain the proof to the user: walk through the key code snippets, what each \
tactic or lemma does, and how it corresponds to the informal mathematical argument.

If a Lean tool reports that Lean is not installed, tell the user, and still show your best \
attempt at the proof clearly marked as unverified."""


@dataclass
class AgentResult:
    reply: str
    messages: list[dict]  # this turn's transcript only (user message onwards)
    tool_calls: list[dict] = field(
        default_factory=list
    )  # trace of tool calls this turn
    finished: bool = True  # False if max steps reached


def turns_to_messages(turns: list[dict]) -> list[dict]:
    """Convert stored turns (rows from db.list_history) into chat messages.

    Each turn needs `query` and `response`; `response` is the stored value for
    that turn (an `envelope` or, for older rows, plain Lean source). Only the
    Lean is replayed. Other keys (query_id, model, created_at) are ignored.
    """
    messages: list[dict] = []
    for turn in turns:
        lean, _ = envelope.decode(turn["response"])
        messages.append({"role": "user", "content": turn["query"]})
        messages.append(
            {
                "role": "assistant",
                "content": f"Lean code for this request:\n```lean\n{lean}\n```",
            }
        )
    return messages


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
            timeout=Config.LLM_TIMEOUT,
            max_retries=1,
        )

    async def stream(
        self, user_message: str, history: list[dict] | None = None
    ) -> AsyncIterator[dict]:
        """Run one user turn, yielding events as they happen.

        `history` is the list of prior turns as returned by `db.list_history`
        (oldest first, each with `query` and `response`). The `messages` in the
        `done` event cover this turn only (user message onwards).

        Event types:
          {"type": "token", "content": str}
          {"type": "tool_call_start", "id": str, "name": str}
          {"type": "tool_result", "id": str, "name": str, "arguments": dict, "result": Any}
          {"type": "done", "reply": str, "messages": list, "tool_calls": list, "finished": bool}
        """
        prior = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *turns_to_messages(history or []),
        ]
        messages: list[dict] = [{"role": "user", "content": user_message}]
        trace: list[dict] = []
        turn_start = time.monotonic()
        deadline = turn_start + Config.AGENT_TIMEOUT
        consecutive_failed_checks = 0
        consecutive_probes = 0
        prompted_for_proof = False
        LEAN_CHECK_TOOLS = ("check_lean_file", "check_lean_snippet")

        for step in range(1, Config.AGENT_MAX_STEPS + 1):
            # Give up early instead of grinding through every one of
            # AGENT_MAX_STEPS: ask for one final, tool-free reply showing the
            # best attempt so far, rather than ending on the generic "Stopped:
            # reached the maximum number of agent steps." below.
            give_up_reason = (
                f"the time limit ({Config.AGENT_TIMEOUT:.0f}s)"
                if time.monotonic() > deadline
                else f"{consecutive_failed_checks} failed Lean checks in a row"
                if consecutive_failed_checks >= Config.AGENT_MAX_FAILED_CHECKS
                else None
            )
            if give_up_reason:
                log.warning("step=%d giving up: %s", step, give_up_reason)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Stop here: you've hit {give_up_reason}. Do not call any more "
                            "tools. Show your best Lean attempt so far, clearly marked "
                            "UNVERIFIED, and briefly explain what Lean kept rejecting."
                        ),
                    }
                )
            elif consecutive_probes >= 3 and not prompted_for_proof:
                prompted_for_proof = True
                messages.append({
                    "role": "user",
                    "content": (
                        "Use your next tool call to submit a Lean theorem for the original request. "
                        "Put the statement in a named theorem and try `exact?` or `apply?` inside "
                        "its proof if you need to find a library lemma. Stop issuing standalone "
                        "#check and #eval probes."
                    ),
                })

            t0 = time.monotonic()
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[*prior, *messages],
                tools=TOOL_SCHEMAS,
                tool_choice="none" if give_up_reason else "auto",
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
            log.info(
                "step=%d/%d model=%s llm_call=%.1fs tool_calls=%d",
                step, Config.AGENT_MAX_STEPS, self.model, time.monotonic() - t0, len(tool_calls),
            )

            if not tool_calls:
                # A normal finish (the model is done) and a forced give-up both land
                # here, since tool_choice="none" guarantees no tool_calls; `finished`
                # tells them apart (main.py only saves/caches a run that finished).
                log.info(
                    "%s step=%d elapsed=%.1fs",
                    "gave up" if give_up_reason else "finished", step, time.monotonic() - turn_start,
                )
                yield {
                    "type": "done",
                    "reply": _stopped_reply(give_up_reason, trace, content) if give_up_reason else content,
                    "messages": messages,
                    "tool_calls": trace,
                    "finished": not give_up_reason,
                }
                return

            if give_up_reason:
                # tool_choice="none" should make this unreachable, but don't loop
                # forever on a model that calls a tool anyway: fall through to the
                # step-limit ending below instead.
                break

            for tc in tool_calls:
                t1 = time.monotonic()
                try:
                    args = json.loads(tc["arguments"] or "{}")
                    result = await run_tool(self.workspace, tc["name"], args)
                except json.JSONDecodeError as e:
                    args, result = {}, {"error": f"Invalid JSON arguments: {e}"}
                call = {"name": tc["name"], "arguments": args, "result": result}
                trace.append(call)
                if tc["name"] in LEAN_CHECK_TOOLS:
                    probe = result.get("proof_candidate") is False
                    consecutive_probes = consecutive_probes + 1 if probe else 0
                    if not _tool_ok(result):
                        consecutive_failed_checks += 1
                    elif not probe:
                        consecutive_failed_checks = 0
                    if not _tool_ok(result):
                        log.warning("Lean check failed: %s", _last_lean_error(trace))
                log.info(
                    "step=%d tool=%s target=%s ok=%s elapsed=%.1fs",
                    step, tc["name"], args.get("path") or (args.get("code", "") or "")[:30] or None,
                    _tool_ok(result), time.monotonic() - t1,
                )
                yield {"type": "tool_result", "id": tc["id"], **call}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": serialize_result(result),
                    }
                )

        log.warning(
            "max steps (%d) reached without finishing, elapsed=%.1fs",
            Config.AGENT_MAX_STEPS, time.monotonic() - turn_start,
        )
        yield {
            "type": "done",
            "reply": _stopped_reply("reached the maximum number of agent steps", trace),
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

        `history` is the list of prior turns as returned by `db.list_history`
        (oldest first, each with `query` and `response`). `on_tool_call` is
        called after each tool executes and `on_token` for each text delta
        (for live logging).
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

    # A no-op if something else (e.g. importing main.py first) already configured
    # logging. Shows the same step/tool timing lines main.py's server logs do,
    # interleaved with this CLI's own colored prints -- useful for reproducing a
    # slow or looping run locally without a browser (see backend/README.md).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

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
        # history uses the same turn shape as db.list_history.
        print("\033[1magent>\033[0m ", end="", flush=True)
        reply = ""
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
                reply = event["reply"]
        print("\n")
        return [*history, {"query": prompt, "response": reply}]

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
