"""Facts table — long-term memory, scoped + FTS + optional embeddings."""
from __future__ import annotations

import sqlite3
import struct
from datetime import UTC, datetime
from typing import Any

from . import ids
from .fts import fts_sanitize


def insert_fact(
    conn: sqlite3.Connection,
    *,
    fact: str,
    agent_scope: str | None = None,
    tags: str | None = None,
    embedding: list[float] | None = None,
    written_by_tool: str | None = None,
    written_by_job: str | None = None,
    tainted: bool = False,
) -> str:
    fid = ids.fact_id()
    emb_blob = _pack_embedding(embedding) if embedding else None
    conn.execute(
        """
        INSERT INTO facts
            (id, agent_scope, fact, tags, embedding, written_by_tool, written_by_job, tainted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (fid, agent_scope, fact, tags, emb_blob, written_by_tool, written_by_job,
         1 if tainted else 0),
    )
    return fid


def delete_fact(conn: sqlite3.Connection, fact_id: str) -> bool:
    cur = conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
    return cur.rowcount > 0


def search_facts_fts(
    conn: sqlite3.Connection,
    query: str,
    *,
    agent_scope: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """FTS5 keyword search scoped by agent (and shared / NULL).

    Codex review fix: `last_used_at` used to be mutated synchronously on the
    read path, which made every recall() also a write and contributed to
    SQLite contention. It's now updated via a fire-and-forget asyncio task
    on a fresh connection — doesn't block the read, doesn't share the caller's
    connection.
    """
    match_expr = fts_sanitize(query)
    if not match_expr:
        return []
    if agent_scope:
        rows = conn.execute(
            """
            SELECT f.id, f.fact, f.tags, f.agent_scope, f.tainted,
                   rank AS score
            FROM facts_fts
            JOIN facts f ON f.rowid = facts_fts.rowid
            WHERE facts_fts MATCH ?
              AND (f.agent_scope = ? OR f.agent_scope IS NULL)
            ORDER BY rank
            LIMIT ?
            """,
            (match_expr, agent_scope, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT f.id, f.fact, f.tags, f.agent_scope, f.tainted,
                   rank AS score
            FROM facts_fts
            JOIN facts f ON f.rowid = facts_fts.rowid
            WHERE facts_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match_expr, limit),
        ).fetchall()

    if rows:
        _touch_last_used_async([r["id"] for r in rows])
    return [dict(r) for r in rows]


def _touch_last_used_async(fact_ids: list[str]) -> None:
    """Fire-and-forget `last_used_at` update. No-op if no running loop."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # synchronous context — skip silently
    loop.create_task(_do_touch_last_used(fact_ids))


async def _do_touch_last_used(fact_ids: list[str]) -> None:
    from .db import connect, transaction
    try:
        conn = connect()
        try:
            with transaction(conn):
                now = datetime.now(UTC).isoformat()
                placeholders = ",".join("?" * len(fact_ids))
                conn.execute(
                    f"UPDATE facts SET last_used_at = ? WHERE id IN ({placeholders})",
                    (now, *fact_ids),
                )
        finally:
            conn.close()
    except Exception:
        # Silently swallow — this is best-effort usage tracking
        pass


def _pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_embedding(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob)//4}f", blob))
