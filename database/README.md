# Database plan

Postgres stores each chat turn and the Lean code produced for it. The cache is a lookup on that table. There is no separate cache key.

`POST /api/chat` in `backend/main.py` is the only caller. `ProofAgent.run` in `backend/agent/agent.py` stays unchanged.

## Request

```json
{
  "user_id": "u1",
  "chat_id": "2b6e1c3a-7f4d-4c8a-9e11-0a1b2c3d4e5f",
  "model": "anthropic/claude-sonnet-4.5",
  "text": "prove that n + 0 = n",
  "allowBuild": false
}
```

The UI creates `chat_id` once per chat. It does not send `query_id`. A picked file is read in the browser and sent as `text`. `run()` accepts one string.

```json
{
  "query_id": "...",
  "response": "theorem n_add_zero (n : Nat) : n + 0 = n := by\n  simp",
  "cached": false
}
```

`response` is the Lean source the UI shows.

## Tables

```sql
create table queries (
  query_id   uuid primary key default gen_random_uuid(),
  model      text not null,
  query      text not null,
  response   text not null,
  messages   jsonb not null,
  created_at timestamptz not null default now()
);

create table chat_turns (
  user_id    text not null,
  chat_id    uuid not null,
  query_id   uuid not null references queries (query_id),
  created_at timestamptz not null default now(),
  primary key (chat_id, query_id)
);

create index chat_turns_user_idx
  on chat_turns (user_id, chat_id, created_at);
```

`chat_turns` is the ordered list for one user and one chat. Each row is one turn.

`queries` is that turn's input and output.

| Column | Contents |
| --- | --- |
| `query_id` | Generated on insert. Returned to the UI. One id per build. |
| `model` | Model passed to `ProofAgent`. |
| `query` | The exact `text` from the request. |
| `response` | The Lean source, read after the run. |
| `messages` | `AgentResult.messages`. The next call for this chat passes the latest value back as `history`. Not sent in the HTTP response. |

`allowBuild: true` inserts a new `query_id` even when the same text already exists. The older row stays. With `allowBuild` false, the lookup below returns the newest of those rows.

`user_id` is the value the client sends. The backend does not authenticate it.

## Checks

Read `allowBuild` first.

### `allowBuild` is true

Load this chat's latest `messages`. No row means `history` is `[]`.

```sql
select q.messages
from chat_turns t
join queries q on q.query_id = t.query_id
where t.user_id = %s and t.chat_id = %s
order by t.created_at desc
limit 1
```

Call the model, read the Lean code, then insert a `queries` row and a `chat_turns` row.

### `allowBuild` is false

Search this chat for the same model and the same text:

```sql
select q.query_id, q.response
from chat_turns t
join queries q on q.query_id = t.query_id
where t.user_id = %s
  and t.chat_id = %s
  and q.model = %s
  and q.query = %s
order by t.created_at desc
limit 1
```

A row means return that `query_id` and `response` with `cached: true`. Do not call the model.

No row means load the latest `messages` with the query above, call the model, read the Lean code, and insert both rows. A new chat has no `chat_turns` rows, so this misses and the call is `agent.run(text, [])`. The same text under another `chat_id` misses too.

## Model call

```python
agent = ProofAgent(workspace, model=model)
result = await agent.run(text, history)
```

`history` is the latest `messages` for this `user_id` and `chat_id`.

`result.reply` is the model's explanation. It is not stored. The Lean code is taken from the workspace after `run()` returns. Walk `result.tool_calls` from last to first:

- For `check_lean_file`, `write_file`, or `edit_file` whose `path` ends in `.lean`, `response` is `workspace.read_file(path)`. Reading the file includes later `edit_file` calls.
- If the run never touched a `.lean` file and the last Lean call is `check_lean_snippet`, `response` is that call's `code` argument.

Skip the insert when `result.finished` is false, or when that walk finds no Lean code.

Every request uses the single workspace created in `main.py`. Read the `.lean` file before the request returns. A cache hit returns the stored `response` and does not rewrite the file.

## Wiring

Add `psycopg[binary]` to `backend/requirements.txt` and `DATABASE_URL` to `backend/.env`. Put the SQL and the lookups in `backend/db.py`. Replace the body of `chat()` in `backend/main.py` with the checks above.
