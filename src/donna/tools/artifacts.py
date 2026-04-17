"""Artifact tools — save, read, list."""
from __future__ import annotations

from typing import Any

from ..memory import artifacts as artifacts_mod
from ..memory.db import connect
from .registry import tool


@tool(
    scope="write_data", cost="low", confirmation="once_per_job",
    description=(
        "Persist a named artifact (a report, summary, transcript, data blob). "
        "Returns artifact_id for later reference."
    ),
)
async def save_artifact(
    name: str,
    content: str,
    mime: str = "text/plain",
    tags: str = "",
    job_id: str | None = None,
) -> dict[str, Any]:
    conn = connect()
    try:
        return artifacts_mod.save_artifact(
            conn, name=name, content=content, mime=mime,
            tags=tags, tainted=False, created_by_job=job_id,
        )
    finally:
        conn.close()


@tool(
    scope="read_data", cost="low",
    description=(
        "Read an artifact by id. Optionally slice with offset/length. If the "
        "artifact is tainted, the read propagates taint onto the calling job."
    ),
)
async def read_artifact(
    artifact_id: str,
    offset: int = 0,
    length: int = 4000,
) -> dict[str, Any]:
    conn = connect()
    try:
        loaded = artifacts_mod.load_artifact_bytes(conn, artifact_id)
    finally:
        conn.close()
    if loaded is None:
        return {"error": "artifact_not_found", "artifact_id": artifact_id}
    data, meta = loaded
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "artifact_id": artifact_id, "mime": meta["mime"], "bytes": meta["bytes"],
            "binary": True, "message": "artifact is binary; ask to parse via a specialized tool",
        }
    excerpt = text[offset: offset + length]
    return {
        "artifact_id": artifact_id,
        "excerpt": excerpt,
        "offset": offset,
        "length_returned": len(excerpt),
        "total_chars": len(text),
        "tainted": bool(meta.get("tainted")),
    }


@tool(
    scope="read_data", cost="low",
    description="List recently saved artifacts, optionally filtered by tag.",
)
async def list_artifacts(tag: str = "", limit: int = 25) -> dict[str, Any]:
    conn = connect()
    try:
        items = artifacts_mod.list_artifacts(conn, tag=tag or None, limit=limit)
    finally:
        conn.close()
    return {"count": len(items), "items": items}
