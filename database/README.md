# Database plan

Postgres stores each chat turn and the Lean code produced for it. The cache is a lookup on those rows. There is no separate cache key.

`POST /api/chat` and `GET /api/history` live in `backend/main.py`. The SQL lives in `backend/db.py`. `ProofAgent.run` in `backend/agent/agent.py` takes the `list_history` rows as `history`.

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

The response is `text/event-stream`: a series of `data: {json}\n\n` lines forwarding
`ProofAgent.stream` events (`token`, `tool_call_start`, `tool_result`), ending in one `done`
event (or `error` on failure):

```json
{
  "type": "done",
  "cached": false,
  "query_id": "...",
  "response": "theorem n_add_zero (n : Nat) : n + 0 = n := by\n  simp",
  "reply": "This proves n + 0 = n by simp, which unfolds the definition of addition...",
  "finished": true,
  "tool_calls": [ ... ]
}
```

`response` is the Lean source the UI shows. `reply` is the agent's prose explanation for this
turn; it is not stored, so it is not available on a cache hit or in `GET /api/history`
(`"reply": "response"` on a cache hit, the Lean source again).

### `GET /api/history?chat_id=<uuid>`

Calls `list_history`. `chat()` calls it too, for the agent's history. The user comes from the guest JWT cookie (`sub`). An empty chat returns `"turns": []`.

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
| `messages` | `AgentResult.messages`: this turn's transcript only (user message, tool calls, replies). Kept for debugging. Not sent in the HTTP response and not used as history. |

`allowBuild: true` inserts a new `query_id` even when the same text already exists. The older row stays. With `allowBuild` false, `find_response` returns the newest of those rows.

## `backend/db.py`

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

Returns every turn for that token and chat, oldest first. `GET /api/history` and `chat()` call it. `agent.run` turns each row into a user message (`query`) and an assistant message (`response`).

```sql
select q.query_id, q.model, q.query, q.response, t.created_at
from chat_turns t
join queries q on q.query_id = t.query_id
where t.user_token = %s and t.chat_id = %s
order by t.created_at
```

## `chat()`

Read `allowBuild` first.

**`allowBuild` is true.** Call `list_history`. Call the model with that history. Read the Lean code. Call `insert_turn`.

**`allowBuild` is false.** Call `find_response`. A row means return that `query_id` and `response` with `cached: true`. Do not call the model. No row means call `list_history`, call the model, read the Lean code, and call `insert_turn`. A new chat has no `chat_turns` rows, so both lookups miss and the call is `agent.run(text, [])`. The same text under another `chat_id` misses too.

```python
agent = ProofAgent(workspace, model=model)
turns = await list_history(user_token, chat_id)
result = await agent.run(text, turns)
```

`result.reply` is the model's explanation. It is not stored. Walk `result.tool_calls` from last to first:

- For `check_lean_file`, `write_file`, or `edit_file` on a `.lean` file, use the latest file that contains a theorem, lemma, or example. Reading the file includes later edits.
- If no proof file is available, use the latest checked snippet that contains a proof declaration. Standalone `#check` and `#eval` commands remain in the tool trace.

Call `insert_turn` only when the writer finishes and Lean accepted the exact source selected for the response. Unverified proof attempts can be shown in the current chat without being cached.

Every request uses the single workspace created in `main.py`. Read the `.lean` file before the request returns. A cache hit returns the stored `response` and does not rewrite the file.

## Wiring

Add `psycopg[binary]` to `backend/requirements.txt` and `DATABASE_URL` to `backend/.env`. Put the three methods in `backend/db.py`. Replace the body of `chat()` in `backend/main.py` with the checks above, and add `GET /api/history`.
