"""Facts table — long-term memory, scoped + FTS + optional embeddings."""
from __future__ import annotations

import sqlite3
import struct
from datetime import datetime, timezone
from typing import Any

from . import ids


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
    """FTS5 keyword search scoped by agent (and shared / NULL)."""
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
            (query, agent_scope, limit),
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
            (query, limit),
        ).fetchall()
    # touch last_used_at
    if rows:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            f"UPDATE facts SET last_used_at = ? WHERE id IN ({','.join('?'*len(rows))})",
            (now, *[r["id"] for r in rows]),
        )
    return [dict(r) for r in rows]


def _pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_embedding(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob)//4}f", blob))
