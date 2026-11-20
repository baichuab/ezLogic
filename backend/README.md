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

## Database

Chat turns are cached in Postgres (see `database/README.md`). `DATABASE_URL` must point at a
reachable database before the backend will start (`init_db()` runs on startup). For local
development, run Postgres in Docker and point `DATABASE_URL` at it:

```bash
docker run --name ezlogic-db -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres
# DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
```

Also set `GUEST_JWT_SECRET` in `.env` to a persistent random value, or guest sessions
(and their chat history) are invalidated every time the backend restarts.

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
| POST | `/api/chat` | Run the agent for one turn, streamed as SSE. Body: `{"chat_id": uuid, "text": str, "model": str?, "allowBuild": bool}`. See `database/README.md` for the event stream shape |
| GET | `/api/history?chat_id=<uuid>` | Every stored turn for this guest and chat, oldest first |
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
