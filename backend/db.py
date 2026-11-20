"""Postgres access for chat turns and stored Lean code."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _database_url() -> str:
    # Every lookup uses the same connection string. Fail before opening a socket
    # when it was never configured.
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect():
    # dict_row makes fetchone() return {"column": value} instead of a tuple.
    return psycopg.AsyncConnection.connect(_database_url(), row_factory=dict_row)


def _str(value: UUID | datetime | str) -> str:
    # Callers return JSON. Postgres gives back uuid and timestamptz objects.
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def init_db() -> None:
    """Create the tables in schema.sql. Safe to run more than once."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    # psycopg runs one statement per execute. schema.sql is three statements.
    statements = [part.strip() for part in sql.split(";") if part.strip()]
    async with await _connect() as conn:
        async with conn.cursor() as cur:
            for statement in statements:
                await cur.execute(statement)


async def latest_messages(user_token: str, chat_id: str) -> list:
    """Newest agent messages for this chat, or []."""
    # chat() passes this list to agent.run as history. A new chat has no row.
    async with await _connect() as conn:
        cur = await conn.execute(
            """
            select q.messages
            from chat_turns t
            join queries q on q.query_id = t.query_id
            where t.user_token = %s and t.chat_id = %s
            order by t.created_at desc
            limit 1
            """,
            (user_token, chat_id),
        )
        row = await cur.fetchone()
    if row is None:
        return []
    # messages is jsonb: the full agent transcript for that one turn.
    return row["messages"]


async def find_response(
    user_token: str, chat_id: str, model: str, query: str
) -> dict[str, str] | None:
    """Newest stored Lean source for this exact text, or None."""
    # Cache lookup for allowBuild false. Same text with a new build stays a
    # second row, so the newest created_at wins.
    async with await _connect() as conn:
        cur = await conn.execute(
            """
            select q.query_id, q.response
            from chat_turns t
            join queries q on q.query_id = t.query_id
            where t.user_token = %s
              and t.chat_id = %s
              and q.model = %s
              and q.query = %s
            order by t.created_at desc
            limit 1
            """,
            (user_token, chat_id, model, query),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return {"query_id": _str(row["query_id"]), "response": row["response"]}


async def insert_turn(
    user_token: str,
    chat_id: str,
    model: str,
    query: str,
    response: str,
    messages: list[dict[str, Any]],
) -> str:
    """Store one build and return its query_id. Both inserts commit together."""
    async with await _connect() as conn:
        # One transaction: a queries row is not kept without its chat_turns row.
        async with conn.transaction():
            cur = await conn.execute(
                """
                insert into queries (model, query, response, messages)
                values (%s, %s, %s, %s)
                returning query_id
                """,
                (model, query, response, Jsonb(messages)),
            )
            row = await cur.fetchone()
            query_id = row["query_id"]
            # chat_turns is the list for this token and chat. query_id points
            # at the Lean source just inserted.
            await conn.execute(
                """
                insert into chat_turns (user_token, chat_id, query_id)
                values (%s, %s, %s)
                """,
                (user_token, chat_id, query_id),
            )
    return _str(query_id)


async def list_history(user_token: str, chat_id: str) -> list[dict[str, str]]:
    """Every turn for this token and chat, oldest first."""
    # GET /api/history uses this. Order is oldest first so the UI can render
    # the chat from the first build to the last.
    async with await _connect() as conn:
        cur = await conn.execute(
            """
            select q.query_id, q.model, q.query, q.response, t.created_at
            from chat_turns t
            join queries q on q.query_id = t.query_id
            where t.user_token = %s and t.chat_id = %s
            order by t.created_at
            """,
            (user_token, chat_id),
        )
        rows = await cur.fetchall()
    return [
        {
            "query_id": _str(row["query_id"]),
            "model": row["model"],
            "query": row["query"],
            "response": row["response"],
            "created_at": _str(row["created_at"]),
        }
        for row in rows
    ]
