import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import AgentResult, ExplainerAgent, ProofAgent, Workspace, WorkspaceError
from agent import envelope, lean
from config import Config
from guest_session import ensure_guest_session

import db

# Only the root logger needs a handler; every module below logs through
# logging.getLogger(__name__), e.g. "main", "agent.agent", "agent.lean". Everything
# ends up in this process's terminal -- there is no log file (see backend/README.md).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # the OpenAI client's HTTP logs are noisy at INFO

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.init_db()
    # Best-effort and non-blocking: starts the Lean REPL and preloads Mathlib (if
    # applicable) in the background, so the first chat request isn't the one that
    # pays for it. See agent/lean.py's warm_up().
    asyncio.create_task(_warm_up_lean())
    yield


async def _warm_up_lean() -> None:
    try:
        t0 = time.monotonic()
        await lean.warm_up()
        log.info("Lean REPL warm-up finished in %.1fs", time.monotonic() - t0)
    except Exception:
        log.exception("Lean REPL warm-up failed; will retry lazily on first use")


app = FastAPI(
    title=Config.API_TITLE,
    description="LLM-powered Lean proof writing and verification",
    version=Config.API_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[Config.FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

workspace = Workspace(Config.WORKSPACE_DIR)

LEAN_FILE_TOOLS = {"check_lean_file", "write_file", "edit_file"}


class ChatRequest(BaseModel):
    chat_id: UUID
    text: str
    model: str | None = None  # override OPENROUTER_MODEL
    allowBuild: bool = False


class HistoryTurn(BaseModel):
    query_id: str
    model: str
    query: str
    response: str  # the Lean source (decoded from the stored envelope)
    created_at: str
    # The explanation as a ```json {intro, steps} block for the frontend's
    # fromReply, or None if this turn has no stored explanation.
    reply: str | None = None


class HistoryResponse(BaseModel):
    turns: list[HistoryTurn]


class SnippetRequest(BaseModel):
    code: str


class FileRequest(BaseModel):
    path: str


def _user_id(request: Request) -> str:
    """Guest id (JWT `sub`) set by ensure_guest_session."""
    return request.state.guest_id


def _extract_lean(result: AgentResult) -> str | None:
    """Lean source produced by this run, per database/README.md."""
    snippet: str | None = None
    for call in reversed(result.tool_calls):
        name = call.get("name")
        args = call.get("arguments") or {}
        path = args.get("path")
        if name in LEAN_FILE_TOOLS and isinstance(path, str) and path.endswith(".lean"):
            try:
                return workspace.read_file(path)
            except WorkspaceError:
                continue
        if name == "check_lean_snippet" and snippet is None:
            code = args.get("code")
            if isinstance(code, str) and code.strip():
                snippet = code
    return snippet


JSON_FENCE = re.compile(r"```json\s*[\s\S]*?```")


def _compose_reply(writer_reply: str, explanation: dict | None) -> str:
    """The `reply` sent to the frontend.

    With an explanation, the writer's own ```json blocks are dropped (the
    frontend's fromReply uses the *first* one) and the explanation is appended
    as the json block it renders as step cards. Without one, the writer's
    reply is sent unchanged.
    """
    if explanation is None:
        return writer_reply
    prose = JSON_FENCE.sub("", writer_reply).strip()
    fence = envelope.explanation_fence(explanation)
    return f"{prose}\n\n{fence}" if prose else fence


def _stored_turn(response: str) -> tuple[str, str]:
    """`(lean, reply)` for a stored `queries.response`: reply is the explanation's
    json block, or the Lean itself when there is none (what a cache hit always
    sent before explanations existed, which the frontend treats as "no reply")."""
    lean_src, explanation = envelope.decode(response)
    reply = envelope.explanation_fence(explanation) if explanation else lean_src
    return lean_src, reply


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ezLogic Backend"}


@app.post(
    "/api/session",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(ensure_guest_session)],
)
async def start_guest_session() -> None:
    """Validate or issue the guest session cookie."""


@app.post(
    "/api/chat",
    response_class=StreamingResponse,
    dependencies=[Depends(ensure_guest_session)],
)
async def chat(body: ChatRequest, request: Request):
    """Run the proof agent for one user turn, streaming events as SSE.

    Each event is a `data: {json}` line. Agent events (`token`,
    `tool_call_start`, `tool_result`) are forwarded as-is; see
    `ProofAgent.stream`. The last event is always either

      {"type": "done", "cached": bool, "query_id": str | None, "response": str,
       "reply": str, "finished": bool, "tool_calls": list}

    or, on failure mid-stream, `{"type": "error", "detail": str}`.
    A cache hit (allowBuild false) sends only the `done` event.
    """
    user = _user_id(request)
    chat_id = str(body.chat_id)
    model = body.model or Config.OPENROUTER_MODEL
    log.info(
        "chat request chat_id=%s user=%s model=%s allowBuild=%s len(text)=%d",
        chat_id, user, model, body.allowBuild, len(body.text),
    )

    try:
        if not body.allowBuild:
            hit = await db.find_response(user, chat_id, model, body.text)
            if hit is not None:
                log.info("chat cache hit chat_id=%s query_id=%s", chat_id, hit["query_id"])
                lean_src, reply = _stored_turn(hit["response"])
                return _stream(
                    _single(
                        {
                            "type": "done",
                            "cached": True,
                            "query_id": hit["query_id"],
                            "response": lean_src,
                            "reply": reply,
                            "finished": True,
                            "tool_calls": [],
                        }
                    )
                )

        turns = await db.list_history(user, chat_id)
    except (RuntimeError, psycopg.Error) as e:
        log.error("chat db error chat_id=%s: %s", chat_id, e)
        raise HTTPException(status_code=503, detail=f"Database error: {e}")

    try:
        agent = ProofAgent(workspace, model=model)
    except RuntimeError as e:
        log.error("chat agent init failed chat_id=%s: %s", chat_id, e)
        raise HTTPException(status_code=503, detail=str(e))

    async def events() -> AsyncIterator[str]:
        t0 = time.monotonic()
        try:
            async for event in agent.stream(body.text, turns):
                if event["type"] != "done":
                    yield _sse(event)
                    continue

                result = AgentResult(
                    reply=event["reply"],
                    messages=event["messages"],
                    tool_calls=event["tool_calls"],
                    finished=event["finished"],
                )
                response = _extract_lean(result)

                # Explaining agent: break the final Lean into step cards that
                # point at line ranges. Runs for unfinished (unverified) runs
                # too; any failure just leaves the writer's reply as it was.
                explanation: dict | None = None
                if response is not None and response.strip():
                    t1 = time.monotonic()
                    try:
                        explainer = ExplainerAgent(Config.OPENROUTER_EXPLAIN_MODEL or model)
                        async for ev in explainer.stream(
                            body.text,
                            response,
                            writer_reply=result.reply,
                            tool_calls=result.tool_calls,
                            finished=result.finished,
                            history=turns,
                        ):
                            if ev["type"] == "explanation":
                                explanation = ev["explanation"]
                            else:
                                yield _sse(ev)
                    except Exception:
                        log.exception("chat explainer failed chat_id=%s", chat_id)
                    log.info(
                        "chat explained chat_id=%s ok=%s elapsed=%.1fs",
                        chat_id, explanation is not None, time.monotonic() - t1,
                    )

                query_id: str | None = None
                if result.finished and response is not None:
                    query_id = await db.insert_turn(
                        user, chat_id, model, body.text,
                        envelope.encode(response, explanation), result.messages,
                    )
                log.info(
                    "chat done chat_id=%s finished=%s saved=%s tool_calls=%d elapsed=%.1fs",
                    chat_id, result.finished, query_id is not None, len(result.tool_calls),
                    time.monotonic() - t0,
                )
                yield _sse(
                    {
                        "type": "done",
                        "cached": False,
                        "query_id": query_id,
                        "response": response if response is not None else result.reply,
                        "reply": _compose_reply(result.reply, explanation),
                        "finished": result.finished,
                        "tool_calls": result.tool_calls,
                    }
                )
        except Exception as e:  # status code is already sent; report in-band
            log.exception("chat stream failed chat_id=%s after %.1fs", chat_id, time.monotonic() - t0)
            yield _sse({"type": "error", "detail": f"{type(e).__name__}: {e}"})

    return _stream(events())


@app.get(
    "/api/history",
    response_model=HistoryResponse,
    dependencies=[Depends(ensure_guest_session)],
)
async def history(chat_id: UUID, request: Request):
    """Every stored turn for this guest and chat, oldest first."""
    try:
        turns = await db.list_history(_user_id(request), str(chat_id))
    except (RuntimeError, psycopg.Error) as e:
        log.error("history db error chat_id=%s: %s", chat_id, e)
        raise HTTPException(status_code=503, detail=f"Database error: {e}")
    out: list[HistoryTurn] = []
    for turn in turns:
        lean_src, explanation = envelope.decode(turn["response"])
        out.append(
            HistoryTurn(
                **{**turn, "response": lean_src},
                reply=envelope.explanation_fence(explanation) if explanation else None,
            )
        )
    return HistoryResponse(turns=out)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def _single(event: dict) -> AsyncIterator[str]:
    yield _sse(event)


def _stream(body: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/files")
async def list_files():
    return {"files": workspace.list_files()}


@app.get("/api/files/{path:path}")
async def read_file(path: str):
    try:
        return {"path": path, "content": workspace.read_file(path)}
    except WorkspaceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/verify/snippet")
async def verify_snippet(request: SnippetRequest):
    """Check a short Lean snippet with the lean-interact REPL."""
    return (await lean.check_snippet(request.code)).to_dict()


@app.post("/api/verify/file")
async def verify_file(request: FileRequest):
    """Check a workspace file with the lean-interact REPL."""
    try:
        return (await lean.check_file(workspace, request.path)).to_dict()
    except WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
