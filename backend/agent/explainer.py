"""Explaining agent: turns the writer's final Lean proof into step cards.

Runs once after `ProofAgent` finishes a turn. It makes a single tool-free LLM
call and returns the structure the frontend's `fromReply` / `normaliseStep`
(frontend/src/lib/api.ts) already render as proof-step cards:

    {"intro": str, "steps": [{"id", "kind", "title", "statementTex",
                              "summary", "explanation", "leanLines": [a, b]}]}

`leanLines` is a 1-based inclusive line range into the exact Lean source the
frontend shows (`done.response`), which `LeanCode.svelte` highlights when the
user opens a step. Each step's prose is rendered by `RichText.svelte`, which
understands `$inline$`, `$$display$$` and `` `code` `` -- nothing else.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI, BadRequestError

from config import Config

from .agent import turns_to_messages

log = logging.getLogger(__name__)

# Must match frontend/src/lib/types.ts StepKind.
STEP_KINDS = (
    "theorem",
    "definition",
    "lemma",
    "strategy",
    "base-case",
    "inductive-step",
    "step",
    "conclusion",
    "response",
)

LEAN_CHECK_TOOLS = ("check_lean_file", "check_lean_snippet")
MAX_WRITER_NOTES = 6000
MAX_DIAGNOSTICS = 20

EXPLAIN_PROMPT = f"""You are the explaining agent of ezLogic, an assistant for mathematicians. \
Another agent has already written a Lean 4 proof for the user's request. Your job is to explain \
that proof to a mathematician who may not know Lean, step by step, pointing each step at the \
exact lines of Lean code that carry it out.

You are given the user's request, the final Lean source with line numbers, the writing agent's \
own notes, and the result of the last Lean check.

Reply with ONE JSON object and nothing else (no prose before or after, no code fences):
{{
  "intro": "One or two plain sentences introducing the proof.",
  "steps": [
    {{
      "id": "s1",
      "kind": "theorem",
      "title": "Short heading",
      "statementTex": "LaTeX for the claim of this step",
      "summary": "One or two sentences shown on the step card.",
      "explanation": "A thorough explanation.\\n\\nParagraphs separated by blank lines.",
      "leanLines": [5, 7]
    }}
  ]
}}

Rules:
- One step per logical move of the proof, in order: usually the statement first, then the \
strategy, then cases / key steps, then the conclusion. Typically 3 to 8 steps.
- "kind" is exactly one of: {", ".join(STEP_KINDS)}.
- "id" values are unique: "s1", "s2", ...
- "leanLines" is [first, last]: 1-based, inclusive line numbers taken from the numbered source \
you are given. Each step gets one contiguous range covering the Lean code that does that step. \
Together the steps should cover the theorem statement and the whole proof body. Skip import \
lines unless they matter. Never invent line numbers outside the source.
- "intro" is plain text: no $, no LaTeX, no backticks.
- "statementTex" is raw LaTeX WITHOUT surrounding $ (e.g. "2\\\\sum_{{i=0}}^{{n}} i = n(n+1)"), \
or "" if the step has no single formula.
- "summary" and "explanation" may use only $inline math$, $$display math$$ and `code` for Lean \
names, tactics and lemmas. No markdown: no **bold**, no lists, no headings, no code fences.
- In "explanation", relate the informal argument to the code: say what each tactic or lemma on \
those lines does and why it is needed, and quote Lean names in `backticks`.
- Remember this is a JSON string: escape backslashes in LaTeX (write \\\\frac, not \\frac).
- Never claim the proof is verified or compiles. If the last Lean check did not pass, say in \
"intro" that the proof is unverified, and point out where Lean reported problems."""


def number_lines(source: str) -> str:
    """Prefix every line with its 1-based number, matching the frontend's `split('\\n')`."""
    lines = source.split("\n")
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}}| {line}" for i, line in enumerate(lines, 1))


def last_check(tool_calls: list[dict]) -> dict | None:
    """The result of the most recent Lean check tool call, if any."""
    for call in reversed(tool_calls):
        if call.get("name") in LEAN_CHECK_TOOLS and isinstance(call.get("result"), dict):
            return call["result"]
    return None


def describe_check(tool_calls: list[dict], finished: bool) -> str:
    """Plain-language verification status and diagnostics for the prompt."""
    result = last_check(tool_calls)
    if result is None:
        status = "No Lean check was run: the proof is UNVERIFIED."
    elif result.get("ok"):
        status = "The last Lean check passed."
    else:
        status = "The last Lean check FAILED: the proof is UNVERIFIED."
    if not finished:
        status += " The writing agent gave up before finishing."

    lines = [status]
    messages = (result or {}).get("messages") or []
    for m in messages[:MAX_DIAGNOSTICS]:
        if not isinstance(m, dict):
            continue
        lines.append(
            f"- line {m.get('line', '?')}, col {m.get('column', '?')} "
            f"[{m.get('severity', '?')}]: {str(m.get('message', '')).strip()}"
        )
    if result and result.get("error"):
        lines.append(f"- error: {result['error']}")
    return "\n".join(lines)


def strip_fences(text: str) -> str:
    """Writer notes without code blocks: the Lean is given separately, numbered."""
    return re.sub(r"```[\s\S]*?```", "", text or "").strip()


def build_user_prompt(
    request: str, lean: str, writer_reply: str, check: str
) -> str:
    notes = strip_fences(writer_reply)[:MAX_WRITER_NOTES] or "(none)"
    return (
        f"## User's request\n{request}\n\n"
        f"## Final Lean source (line numbers added; they are not part of the code)\n"
        f"{number_lines(lean)}\n\n"
        f"## Last Lean check\n{check}\n\n"
        f"## Writing agent's notes\n{notes}\n\n"
        "Return the JSON object now."
    )


def parse_json(text: str) -> Any:
    """Parse the model's reply: a bare object, a fenced one, or the outermost {...}."""
    text = (text or "").strip()
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        candidates.append(fence.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _range(value: Any, n_lines: int) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        a, b = (int(v) for v in value)
    except (TypeError, ValueError):
        return None
    if a > b:
        a, b = b, a
    a, b = max(a, 1), min(b, n_lines)
    return [a, b] if a <= b else None


def validate(obj: Any, n_lines: int) -> dict | None:
    """Coerce the model's JSON into what `normaliseStep` renders, or None if unusable."""
    if isinstance(obj, list):
        obj = {"steps": obj}
    if not isinstance(obj, dict) or not isinstance(obj.get("steps"), list):
        return None

    steps: list[dict] = []
    seen: set[str] = set()
    for raw in obj["steps"]:
        if not isinstance(raw, dict):
            continue
        title, summary = _str(raw.get("title")), _str(raw.get("summary"))
        explanation = _str(raw.get("explanation")) or summary
        if not (title or summary or explanation):
            continue
        step_id = _str(raw.get("id"))
        if not step_id or step_id in seen:
            step_id = f"s{len(steps) + 1}"
            while step_id in seen:
                step_id += "'"
        seen.add(step_id)
        kind = _str(raw.get("kind"))
        step = {
            "id": step_id,
            "kind": kind if kind in STEP_KINDS else "step",
            "title": title,
            "statementTex": _str(raw.get("statementTex")).strip("$").strip(),
            "summary": summary,
            "explanation": explanation,
        }
        lean_lines = _range(raw.get("leanLines"), n_lines)
        if lean_lines:
            step["leanLines"] = lean_lines
        steps.append(step)

    if not steps:
        return None
    out: dict[str, Any] = {"steps": steps}
    intro = _str(obj.get("intro"))
    if intro:
        out["intro"] = intro
    return out


class ExplainerAgent:
    def __init__(self, model: str | None = None):
        if not Config.OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set (see backend/.env.example)"
            )
        self.model = model or Config.OPENROUTER_EXPLAIN_MODEL or Config.OPENROUTER_MODEL
        self.client = AsyncOpenAI(
            base_url=Config.OPENROUTER_BASE_URL,
            api_key=Config.OPENROUTER_API_KEY,
            default_headers={"HTTP-Referer": Config.FRONTEND_URL, "X-Title": "ezLogic"},
            timeout=Config.EXPLAIN_TIMEOUT,
            max_retries=1,
        )

    async def _complete(self, messages: list[dict]) -> str:
        """One completion, asking for JSON mode where the provider supports it."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except BadRequestError:
            log.info("explainer: model %s rejected JSON mode, retrying without", self.model)
            response = await self.client.chat.completions.create(
                model=self.model, messages=messages
            )
        if not response.choices:
            return ""
        return response.choices[0].message.content or ""

    async def explain(
        self,
        request: str,
        lean: str,
        *,
        writer_reply: str = "",
        tool_calls: list[dict] | None = None,
        finished: bool = True,
        history: list[dict] | None = None,
    ) -> dict | None:
        """Explain `lean`; returns `{intro?, steps}` or None if the model's output is unusable."""
        n_lines = len(lean.split("\n"))
        messages = [
            {"role": "system", "content": EXPLAIN_PROMPT},
            *turns_to_messages(history or []),
            {
                "role": "user",
                "content": build_user_prompt(
                    request, lean, writer_reply, describe_check(tool_calls or [], finished)
                ),
            },
        ]

        async def attempt() -> dict | None:
            for i in range(2):
                content = await self._complete(messages)
                result = validate(parse_json(content), n_lines)
                if result is not None:
                    log.info("explainer: %d steps (attempt %d)", len(result["steps"]), i + 1)
                    return result
                log.warning("explainer: unusable output (attempt %d): %.200r", i + 1, content)
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": "That was not a valid JSON object with a non-empty "
                        '"steps" array. Reply again with only the JSON object.',
                    }
                )
            return None

        return await asyncio.wait_for(attempt(), timeout=Config.EXPLAIN_TIMEOUT * 2)

    async def stream(self, request: str, lean: str, **kwargs: Any) -> AsyncIterator[dict]:
        """`explain`, framed for the chat SSE stream.

        Yields a `token` opening a ```json fence (the frontend's live view shows
        an open json fence as "Preparing proof steps…" and hides its contents),
        then a `token` closing it, then `{"type": "explanation", "explanation":
        dict | None}`. Any error is logged and reported as `explanation: None`:
        a failed explanation never fails the turn.
        """
        yield {"type": "token", "content": "\n\n```json\n"}
        explanation: dict | None = None
        try:
            explanation = await self.explain(request, lean, **kwargs)
        except Exception:
            log.exception("explainer failed")
        yield {"type": "token", "content": "\n```"}
        yield {"type": "explanation", "explanation": explanation}
