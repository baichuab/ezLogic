from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import ProofAgent, Workspace, WorkspaceError
from agent import lean
from config import Config

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


class ChatResponse(BaseModel):
    reply: str
    messages: list[dict]
    tool_calls: list[dict]
    finished: bool


class SnippetRequest(BaseModel):
    code: str


class FileRequest(BaseModel):
    path: str


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ezLogic Backend"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Run the proof agent for one user turn."""
    try:
        agent = ProofAgent(workspace, model=request.model)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    result = await agent.run(request.message, request.history)
    return ChatResponse(**result.__dict__)


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
