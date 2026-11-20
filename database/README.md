# Database plan

Postgres stores each chat turn and the Lean code produced for it. The cache is a lookup on those rows. There is no separate cache key.

`POST /api/chat` and `GET /api/history` live in `backend/main.py`. The SQL lives in `backend/db.py`. `ProofAgent.run` in `backend/agent/agent.py` stays unchanged.

`user_token` is the JWT the client sends. The column stores that token, and every lookup matches it exactly. The UI creates `chat_id` once per chat. It does not send `query_id`. A picked file is read in the browser and sent as `text`.

## Endpoints

### `POST /api/chat`

```json
{
  "user_token": "<jwt>",
  "chat_id": "2b6e1c3a-7f4d-4c8a-9e11-0a1b2c3d4e5f",
  "model": "anthropic/claude-sonnet-4.5",
  "text": "prove that n + 0 = n",
  "allowBuild": false
}
```

```json
{
  "query_id": "...",
  "response": "theorem n_add_zero (n : Nat) : n + 0 = n := by\n  simp",
  "cached": false
}
```

`response` is the Lean source the UI shows.

### `GET /api/history?user_token=<jwt>&chat_id=<uuid>`

Calls `list_history`. `chat()` does not. An empty chat returns `"turns": []`.

```json
{
  "turns": [
    {
      "query_id": "...",
      "model": "anthropic/claude-sonnet-4.5",
      "query": "prove that n + 0 = n",
      "response": "theorem n_add_zero (n : Nat) : n + 0 = n := by\n  simp",
      "created_at": "2026-11-21T00:00:00Z"
    }
  ]
}
```

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
  user_token text not null,
  chat_id    uuid not null,
  query_id   uuid not null references queries (query_id),
  created_at timestamptz not null default now(),
  primary key (chat_id, query_id)
);

create index chat_turns_user_idx
  on chat_turns (user_token, chat_id, created_at);
```

`chat_turns` is the ordered list for one token and one chat. Each row is one turn. `queries` is that turn's input and output.

| Column | Contents |
| --- | --- |
| `query_id` | Generated on insert. Returned to the UI. One id per build. |
| `model` | Model passed to `ProofAgent`. |
| `query` | The exact `text` from the request. |
| `response` | The Lean source, read after the run. |
| `messages` | `AgentResult.messages`. The next model call for this chat passes the latest value back as `history`. Not sent in the HTTP response. |

`allowBuild: true` inserts a new `query_id` even when the same text already exists. The older row stays. With `allowBuild` false, `find_response` returns the newest of those rows.

## `backend/db.py`

### `latest_messages(user_token, chat_id)`

Returns the newest `messages` for this chat, or `[]`. `chat()` passes that list to `agent.run` as `history`.

```sql
select q.messages
from chat_turns t
join queries q on q.query_id = t.query_id
where t.user_token = %s and t.chat_id = %s
order by t.created_at desc
limit 1
```

### `find_response(user_token, chat_id, model, query)`

Returns `query_id` and `response` for this exact text, or no row. Used only when `allowBuild` is false.

```sql
select q.query_id, q.response
from chat_turns t
join queries q on q.query_id = t.query_id
where t.user_token = %s
  and t.chat_id = %s
  and q.model = %s
  and q.query = %s
order by t.created_at desc
limit 1
```

### `insert_turn(user_token, chat_id, model, query, response, messages)`

Stores one build and returns the new `query_id`. Both statements run in one transaction.

```sql
insert into queries (model, query, response, messages)
values (%s, %s, %s, %s)
returning query_id;

insert into chat_turns (user_token, chat_id, query_id)
values (%s, %s, %s);
```

### `list_history(user_token, chat_id)`

Returns every turn for that token and chat, oldest first. `GET /api/history` calls it.

```sql
select q.query_id, q.model, q.query, q.response, t.created_at
from chat_turns t
join queries q on q.query_id = t.query_id
where t.user_token = %s and t.chat_id = %s
order by t.created_at
```

## `chat()`

Read `allowBuild` first.

**`allowBuild` is true.** Call `latest_messages`. Call the model with that history. Read the Lean code. Call `insert_turn`.

**`allowBuild` is false.** Call `find_response`. A row means return that `query_id` and `response` with `cached: true`. Do not call the model. No row means call `latest_messages`, call the model, read the Lean code, and call `insert_turn`. A new chat has no `chat_turns` rows, so both lookups miss and the call is `agent.run(text, [])`. The same text under another `chat_id` misses too.

```python
agent = ProofAgent(workspace, model=model)
result = await agent.run(text, history)
```

`result.reply` is the model's explanation. It is not stored. Walk `result.tool_calls` from last to first:

- For `check_lean_file`, `write_file`, or `edit_file` whose `path` ends in `.lean`, `response` is `workspace.read_file(path)`. Reading the file includes later `edit_file` calls.
- If the run never touched a `.lean` file and the last Lean call is `check_lean_snippet`, `response` is that call's `code` argument.

Skip `insert_turn` when `result.finished` is false, or when that walk finds no Lean code.

Every request uses the single workspace created in `main.py`. Read the `.lean` file before the request returns. A cache hit returns the stored `response` and does not rewrite the file.

## Wiring

Add `psycopg[binary]` to `backend/requirements.txt` and `DATABASE_URL` to `backend/.env`. Put the four methods in `backend/db.py`. Replace the body of `chat()` in `backend/main.py` with the checks above, and add `GET /api/history`.
