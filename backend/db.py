"""Postgres storage for chat turns and the Lean code they produced (see database/README.md)."""

from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from agent import AgentResult, Workspace, WorkspaceError
from config import Config

LEAN_FILE_TOOLS = {"check_lean_file", "write_file", "edit_file"}

_pool: AsyncConnectionPool | None = None


async def open_pool() -> None:
    """Create the connection pool. Does not wait for the DB, so the app still starts if it's down."""
    global _pool
    if not Config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set (see backend/.env)")
    _pool = AsyncConnectionPool(
        Config.DATABASE_URL,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row},
        timeout=10,  # seconds to wait for a connection before raising PoolTimeout
        open=False,
    )
    await _pool.open(wait=False)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("Database pool is not open")
    return _pool


async def find_cached(user_id: str, chat_id: UUID, model: str, text: str) -> dict | None:
    """Newest turn in this chat with the same model and text, or None."""
    async with pool().connection() as conn:
        cur = await conn.execute(
            """
            select q.query_id, q.response
            from chat_turns t
            join queries q on q.query_id = t.query_id
            where t.user_id = %s
              and t.chat_id = %s
              and q.model = %s
              and q.query = %s
            order by t.created_at desc
            limit 1
            """,
            (user_id, chat_id, model, text),
        )
        return await cur.fetchone()


async def latest_messages(user_id: str, chat_id: UUID) -> list[dict]:
    """The chat's latest `messages` (agent history), or [] for a new chat."""
    async with pool().connection() as conn:
        cur = await conn.execute(
            """
            select q.messages
            from chat_turns t
            join queries q on q.query_id = t.query_id
            where t.user_id = %s and t.chat_id = %s
            order by t.created_at desc
            limit 1
            """,
            (user_id, chat_id),
        )
        row = await cur.fetchone()
        return row["messages"] if row else []


async def save_turn(
    user_id: str, chat_id: UUID, model: str, text: str, response: str, messages: list[dict]
) -> UUID:
    """Insert the `queries` row and its `chat_turns` row in one transaction. Returns query_id."""
    async with pool().connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                insert into queries (model, query, response, messages)
                values (%s, %s, %s, %s)
                returning query_id
                """,
                (model, text, response, Jsonb(messages)),
            )
            query_id = (await cur.fetchone())["query_id"]
            await conn.execute(
                "insert into chat_turns (user_id, chat_id, query_id) values (%s, %s, %s)",
                (user_id, chat_id, query_id),
            )
    return query_id


def extract_lean(result: AgentResult, workspace: Workspace) -> str | None:
    """Lean source produced by a run, read from the workspace.

    Walks tool calls from last to first: the newest .lean file touched by
    check_lean_file / write_file / edit_file wins (read now, so later edits are included).
    If no .lean file was touched, falls back to the last check_lean_snippet code.
    """
    for call in reversed(result.tool_calls):
        path = call["arguments"].get("path", "")
        if call["name"] in LEAN_FILE_TOOLS and path.endswith(".lean"):
            try:
                return workspace.read_file(path)
            except WorkspaceError:  # file was deleted or path is invalid; keep looking
                continue

    for call in reversed(result.tool_calls):
        if call["name"] == "check_lean_snippet":
            return call["arguments"].get("code") or None
    return None
