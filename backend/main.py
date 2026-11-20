from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, Field

import db
from agent import ProofAgent, Workspace, WorkspaceError
from agent import lean
from config import Config


@asynccontextmanager
async def lifespan(_: FastAPI):
    if Config.DATABASE_URL:
        await db.open_pool()
    yield
    await db.close_pool()


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


class ChatRequest(BaseModel):
    user_id: str
    chat_id: UUID  # created once per chat by the UI
    text: str
    model: str | None = None  # defaults to OPENROUTER_MODEL
    allowBuild: bool = False  # true = always call the model, even if this text is cached


class ChatResponse(BaseModel):
    query_id: UUID | None  # None when the turn wasn't saved (no Lean code / step limit hit)
    response: str  # Lean source; the agent's text reply when no Lean code was produced
    cached: bool


class SnippetRequest(BaseModel):
    code: str


class FileRequest(BaseModel):
    path: str


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ezLogic Backend"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Run the proof agent for one user turn, reusing a cached answer when allowed."""
    model = request.model or Config.OPENROUTER_MODEL
    try:
        if not request.allowBuild:
            hit = await db.find_cached(request.user_id, request.chat_id, model, request.text)
            if hit:
                return ChatResponse(query_id=hit["query_id"], response=hit["response"], cached=True)

        history = await db.latest_messages(request.user_id, request.chat_id)
        try:
            agent = ProofAgent(workspace, model=model)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        result = await agent.run(request.text, history)

        lean_code = db.extract_lean(result, workspace)
        if not result.finished or lean_code is None:
            # Not saved, so the next turn's history won't include this one.
            return ChatResponse(query_id=None, response=result.reply, cached=False)

        query_id = await db.save_turn(
            request.user_id, request.chat_id, model, request.text, lean_code, result.messages
        )
        return ChatResponse(query_id=query_id, response=lean_code, cached=False)
    except (psycopg.Error, PoolTimeout, RuntimeError) as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")


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
