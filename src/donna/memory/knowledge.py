"""Knowledge base — sources, chunks, scoped retrieval with hybrid search."""
from __future__ import annotations

import hashlib
import sqlite3
import struct
from typing import Any

import numpy as np

from ..types import Chunk
from . import ids

# ---------- sources ---------------------------------------------------------


def insert_source(
    conn: sqlite3.Connection,
    *,
    agent_scope: str,
    source_type: str,
    title: str,
    copyright_status: str,
    work_id: str | None = None,
    publication_date: str | None = None,
    author_period: str | None = None,
    source_ref: str | None = None,
    added_by: str = "user",
    tainted: bool = False,
) -> str:
    sid = ids.source_id()
    conn.execute(
        """
        INSERT INTO knowledge_sources
            (id, agent_scope, source_type, work_id, title, publication_date,
             author_period, source_ref, copyright_status, added_by, tainted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (sid, agent_scope, source_type, work_id, title, publication_date,
         author_period, source_ref, copyright_status, added_by, 1 if tainted else 0),
    )
    return sid


def list_sources(conn: sqlite3.Connection, agent_scope: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM knowledge_sources WHERE agent_scope = ? ORDER BY added_at DESC",
        (agent_scope,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- chunks ----------------------------------------------------------


def insert_chunk(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    agent_scope: str,
    content: str,
    chunk_index: int,
    fingerprint: str,
    embedding: list[float] | None,
    work_id: str | None,
    publication_date: str | None,
    source_type: str,
    token_count: int | None = None,
    is_style_anchor: bool = False,
) -> str | None:
    """Insert if fingerprint not already present for this scope (dedupe)."""
    existing = conn.execute(
        "SELECT id FROM knowledge_chunks WHERE agent_scope = ? AND fingerprint = ?",
        (agent_scope, fingerprint),
    ).fetchone()
    if existing is not None:
        return None  # dedup

    cid = ids.chunk_id()
    emb = _pack_embedding(embedding) if embedding else None
    conn.execute(
        """
        INSERT INTO knowledge_chunks
            (id, source_id, agent_scope, work_id, publication_date, source_type,
             content, embedding, chunk_index, token_count, fingerprint, is_style_anchor)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cid, source_id, agent_scope, work_id, publication_date, source_type,
         content, emb, chunk_index, token_count, fingerprint, 1 if is_style_anchor else 0),
    )
    conn.execute(
        "UPDATE knowledge_sources SET chunk_count = chunk_count + 1 WHERE id = ?",
        (source_id,),
    )
    return cid


def semantic_search(
    conn: sqlite3.Connection,
    *,
    agent_scope: str,
    query_embedding: list[float],
    limit: int = 40,
) -> list[tuple[Chunk, float]]:
    """Semantic search using sqlite-vec's `vec_distance_cosine` scalar function
    (Codex review #3+#7 fix). The math runs in C inside SQLite — no Python
    brute-force scan, no loading every embedding into numpy. Streams results
    ordered by similarity; memory stays O(limit), not O(corpus).

    Returns chunks + their cosine similarity score (1 = identical, -1 = opposite).
    `vec_distance_cosine` returns DISTANCE (0..2), so we convert to similarity.
    """
    q_blob = _pack_embedding(query_embedding)
    try:
        rows = conn.execute(
            """
            SELECT c.id, c.source_id, c.agent_scope, c.work_id, c.publication_date,
                   c.source_type, c.content, c.chunk_index, c.is_style_anchor,
                   s.title AS source_title,
                   vec_distance_cosine(c.embedding, ?) AS dist
            FROM knowledge_chunks c
            JOIN knowledge_sources s ON s.id = c.source_id
            WHERE c.agent_scope = ? AND c.embedding IS NOT NULL
            ORDER BY dist ASC
            LIMIT ?
            """,
            (q_blob, agent_scope, limit),
        ).fetchall()
    except sqlite3.OperationalError as e:
        # Fallback if sqlite-vec isn't loaded for some reason — preserves
        # correctness at the cost of the original performance profile.
        if "vec_distance_cosine" in str(e):
            return _python_fallback_search(conn, agent_scope, query_embedding, limit)
        raise

    return [
        (_row_to_chunk(r, 1.0 - float(r["dist"])), 1.0 - float(r["dist"]))
        for r in rows
    ]


def _python_fallback_search(
    conn: sqlite3.Connection, agent_scope: str, query_embedding: list[float], limit: int,
) -> list[tuple[Chunk, float]]:
    """Slow fallback if sqlite-vec isn't loaded. Kept for robustness."""
    rows = conn.execute(
        """
        SELECT c.id, c.source_id, c.agent_scope, c.work_id, c.publication_date,
               c.source_type, c.content, c.embedding, c.chunk_index, c.is_style_anchor,
               s.title AS source_title
        FROM knowledge_chunks c
        JOIN knowledge_sources s ON s.id = c.source_id
        WHERE c.agent_scope = ? AND c.embedding IS NOT NULL
        """,
        (agent_scope,),
    ).fetchall()
    if not rows:
        return []
    q = np.asarray(query_embedding, dtype=np.float32)
    q_norm = q / (np.linalg.norm(q) + 1e-9)
    scored: list[tuple[Chunk, float]] = []
    for r in rows:
        v = _unpack_embedding(r["embedding"])
        vv = np.asarray(v, dtype=np.float32)
        vv_norm = vv / (np.linalg.norm(vv) + 1e-9)
        score = float(np.dot(q_norm, vv_norm))
        scored.append((_row_to_chunk(r, score), score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def keyword_search(
    conn: sqlite3.Connection,
    *,
    agent_scope: str,
    query: str,
    limit: int = 40,
) -> list[tuple[Chunk, float]]:
    """FTS5 keyword over chunks, scoped to agent."""
    rows = conn.execute(
        """
        SELECT c.id, c.source_id, c.agent_scope, c.work_id, c.publication_date,
               c.source_type, c.content, c.chunk_index, c.is_style_anchor,
               s.title AS source_title,
               rank AS score
        FROM chunks_fts
        JOIN knowledge_chunks c ON c.rowid = chunks_fts.rowid
        JOIN knowledge_sources s ON s.id = c.source_id
        WHERE chunks_fts MATCH ?
          AND c.agent_scope = ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, agent_scope, limit),
    ).fetchall()
    # rank is FTS5 bm25-like; more negative = better
    return [(_row_to_chunk(r, -float(r["score"])), -float(r["score"])) for r in rows]


def get_chunks_by_id(
    conn: sqlite3.Connection, *, ids_: list[str]
) -> list[Chunk]:
    if not ids_:
        return []
    placeholders = ",".join("?" * len(ids_))
    rows = conn.execute(
        f"""
        SELECT c.id, c.source_id, c.agent_scope, c.work_id, c.publication_date,
               c.source_type, c.content, c.chunk_index, c.is_style_anchor,
               s.title AS source_title
        FROM knowledge_chunks c
        JOIN knowledge_sources s ON s.id = c.source_id
        WHERE c.id IN ({placeholders})
        """,
        ids_,
    ).fetchall()
    return [_row_to_chunk(r, 1.0) for r in rows]


# ---------- helpers ---------------------------------------------------------


def fingerprint_text(content: str) -> str:
    """SHA256 over a normalized version of the chunk content."""
    normalized = " ".join(content.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_embedding(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob)//4}f", blob))


def _row_to_chunk(row: Any, score: float) -> Chunk:
    return Chunk(
        id=row["id"],
        source_id=row["source_id"],
        agent_scope=row["agent_scope"],
        work_id=row["work_id"],
        publication_date=row["publication_date"],
        source_type=row["source_type"],
        content=row["content"],
        score=score,
        chunk_index=row["chunk_index"],
        is_style_anchor=bool(row["is_style_anchor"]),
        # row is sqlite3.Row — `in row` tests values, not column names, so we need .keys()
        source_title=row["source_title"] if "source_title" in row.keys() else None,  # noqa: SIM118
    )
