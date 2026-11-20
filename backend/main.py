import json

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import ProofAgent, Workspace, WorkspaceError
from agent import lean
from config import Config
from guest_session import ensure_guest_session

app = FastAPI(
    title=Config.API_TITLE,
    description="LLM-powered Lean proof writing and verification",
    version=Config.API_VERSION,
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
    message: str
    history: list[dict] = []  # `messages` returned by the previous /api/chat call
    model: str | None = None  # override OPENROUTER_MODEL


class SnippetRequest(BaseModel):
    code: str


class FileRequest(BaseModel):
    path: str


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
async def chat(request: ChatRequest):
    """Run the proof agent for one user turn, streaming events as SSE.

    Each event is a `data: {json}` line; see `ProofAgent.stream` for event types.
    On failure mid-stream an `{"type": "error", "detail": ...}` event is sent.
    """
    try:
        agent = ProofAgent(workspace, model=request.model)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    async def events():
        try:
            async for event in agent.stream(request.message, request.history):
                yield _sse(event)
        except Exception as e:  # status code is already sent; report in-band
            yield _sse({"type": "error", "detail": f"{type(e).__name__}: {e}"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


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
