# ezLogic Backend

FastAPI backend hosting the Lean proof agent.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set OPENROUTER_API_KEY and DATABASE_URL
python main.py         # http://localhost:8000, docs at /docs
```

`DATABASE_URL` is a Postgres URI. For Supabase use the **Session pooler** string
(`postgres.<project-ref>@aws-...pooler.supabase.com:5432`); the direct `db.<ref>.supabase.co`
host is IPv6-only. The tables from `database/README.md` must exist. Without a database,
`/api/chat` returns 503 and the other endpoints still work.

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
| POST | `/api/chat` | Run the agent for one turn. Body: `{"user_id": str, "chat_id": uuid, "text": str, "model": str?, "allowBuild": bool}`. Returns `{"query_id", "response", "cached"}`. History and caching are handled server-side (see `database/README.md`) |
| GET | `/api/files` | List workspace files |
| GET | `/api/files/{path}` | Read a workspace file |
| POST | `/api/verify/file` | Compile a workspace file with the Lean CLI. Body: `{"path": str}` |
| POST | `/api/verify/snippet` | Check a snippet with lean-interact. Body: `{"code": str}` |

## Project Structure

- `main.py` - FastAPI app and routes
- `config.py` - Configuration from environment / `.env`
- `db.py` - Postgres pool, cache/history lookups, saving turns, extracting Lean code from a run
- `agent/agent.py` - OpenRouter tool-calling loop and system prompt
- `agent/tools.py` - Tool schemas and dispatcher
- `agent/workspace.py` - Sandboxed file operations (paths cannot escape `WORKSPACE_DIR`)
- `agent/lean.py` - Lean CLI file checks and lean-interact snippet checks
- `workspace/` - The agent's local file system (git-ignored). Add a `lakefile` here to make it
  a Lake project (e.g. with Mathlib); files are then checked with `lake env lean`.
