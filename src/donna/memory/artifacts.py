"""Artifact storage — SQLite metadata + blob on /data/artifacts/<sha>.blob."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from ..config import settings
from . import ids


def save_artifact(
    conn: sqlite3.Connection,
    *,
    content: bytes | str,
    name: str | None = None,
    mime: str = "text/plain",
    tags: str | None = None,
    tainted: bool = False,
    created_by_job: str | None = None,
) -> dict[str, str | int]:
    data = content.encode("utf-8") if isinstance(content, str) else content
    sha = hashlib.sha256(data).hexdigest()
    blob_path = settings().artifacts_dir / f"{sha}.blob"
    if not blob_path.exists():
        blob_path.write_bytes(data)

    # Dedupe: if an artifact with this sha already exists, reuse its id
    row = conn.execute(
        "SELECT id FROM artifacts WHERE sha256 = ?", (sha,)
    ).fetchone()
    if row is not None:
        return {"artifact_id": row["id"], "sha256": sha, "bytes": len(data)}

    art_id = ids.artifact_id()
    conn.execute(
        """
        INSERT INTO artifacts (id, sha256, name, mime, bytes, tags, tainted, created_by_job)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (art_id, sha, name, mime, len(data), tags, 1 if tainted else 0, created_by_job),
    )
    return {"artifact_id": art_id, "sha256": sha, "bytes": len(data)}


def load_artifact_bytes(conn: sqlite3.Connection, artifact_id: str) -> tuple[bytes, dict] | None:
    row = conn.execute(
        "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if row is None:
        return None
    blob_path = Path(settings().artifacts_dir) / f"{row['sha256']}.blob"
    if not blob_path.exists():
        return None
    return blob_path.read_bytes(), dict(row)


def list_artifacts(
    conn: sqlite3.Connection, *, tag: str | None = None, limit: int = 50
) -> list[dict]:
    if tag:
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE tags LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{tag}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM artifacts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
