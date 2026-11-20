import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import AgentResult, ProofAgent, Workspace, WorkspaceError
from agent import lean
from config import Config
from guest_session import ensure_guest_session

import db


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.init_db()
    yield


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
    response: str
    created_at: str


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

    try:
        if not body.allowBuild:
            hit = await db.find_response(user, chat_id, model, body.text)
            if hit is not None:
                return _stream(
                    _single(
                        {
                            "type": "done",
                            "cached": True,
                            "query_id": hit["query_id"],
                            "response": hit["response"],
                            "reply": hit["response"],
                            "finished": True,
                            "tool_calls": [],
                        }
                    )
                )

        turns = await db.list_history(user, chat_id)
    except (RuntimeError, psycopg.Error) as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")

    try:
        agent = ProofAgent(workspace, model=model)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    async def events() -> AsyncIterator[str]:
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
                query_id: str | None = None
                if result.finished and response is not None:
                    query_id = await db.insert_turn(
                        user, chat_id, model, body.text, response, result.messages
                    )
                yield _sse(
                    {
                        "type": "done",
                        "cached": False,
                        "query_id": query_id,
                        "response": response if response is not None else result.reply,
                        "reply": result.reply,
                        "finished": result.finished,
                        "tool_calls": result.tool_calls,
                    }
                )
        except Exception as e:  # status code is already sent; report in-band
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
        raise HTTPException(status_code=503, detail=f"Database error: {e}")
    return HistoryResponse(turns=turns)


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
    """Compile a workspace file with the Lean CLI."""
    try:
        return (await lean.check_file(workspace, request.path)).to_dict()
    except WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
