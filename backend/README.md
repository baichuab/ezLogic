# ezLogic Backend

FastAPI backend hosting the Lean proof agent.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set OPENROUTER_API_KEY
python main.py         # http://localhost:8000, docs at /docs
```

Lean must be installed separately via [elan](https://github.com/leanprover/elan) for
verification to work; without it, Lean tools return an "not installed" error and the agent
reports proofs as unverified.

## Testing the agent from the terminal

```bash
python -m agent                                  # interactive chat (/files, /reset, /exit)
python -m agent "prove that 2 + 2 = 4"           # single prompt
python -m agent --model openai/gpt-4o "..."      # override the OpenRouter model
```

Tool calls are printed live as the agent runs them.

## API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Health check |
| POST | `/api/session` | Validate or issue the guest cookie. Returns `204 No Content` |
| POST | `/api/chat` | Run the agent for one turn. Body: `{"message": str, "history": [...], "model": str?}`. Returns `reply`, `messages` (send back as `history` next turn), `tool_calls` trace, `finished` |
| GET | `/api/files` | List workspace files |
| GET | `/api/files/{path}` | Read a workspace file |
| POST | `/api/verify/file` | Compile a workspace file with the Lean CLI. Body: `{"path": str}` |
| POST | `/api/verify/snippet` | Check a snippet with lean-interact. Body: `{"code": str}` |

`POST /api/session` checks the `ezlogic_guest` cookie and reuses the guest ID if
the JWT is valid. If the cookie is missing or invalid, FastAPI sets a new
`HttpOnly` cookie with a signed JWT that lasts 24 hours. `POST /api/chat` also
checks the guest cookie and can start a session on its own. Browser clients
calling the API from a different port on the same hostname should use
`credentials: "include"` with `fetch`.

For HTTPS deployments, set `GUEST_COOKIE_SECURE=true` and set `GUEST_JWT_SECRET`
to a persistent random secret shared by all backend workers. Without a configured
secret, local sessions expire when the backend process restarts.

## Project Structure

- `main.py` - FastAPI app and routes
- `config.py` - Configuration from environment / `.env`
- `agent/agent.py` - OpenRouter tool-calling loop and system prompt
- `agent/tools.py` - Tool schemas and dispatcher
- `agent/workspace.py` - Sandboxed file operations (paths cannot escape `WORKSPACE_DIR`)
- `agent/lean.py` - Lean CLI file checks and lean-interact snippet checks
- `workspace/` - The agent's local file system (git-ignored). Add a `lakefile` here to make it
  a Lake project (e.g. with Mathlib); files are then checked with `lake env lean`.
