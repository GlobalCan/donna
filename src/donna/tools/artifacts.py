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
        "Read an artifact by id. Optionally slice with offset/length. "
        "If the artifact is tainted (from fetch_url / PDF / untrusted source), "
        "reading propagates taint onto the calling job — which in turn escalates "
        "confirmation on future memory writes and code execution."
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
    is_tainted = bool(meta.get("tainted"))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "artifact_id": artifact_id, "mime": meta["mime"], "bytes": meta["bytes"],
            "binary": True, "tainted": is_tainted,
            "message": "artifact is binary; ask to parse via a specialized tool",
        }
    excerpt = text[offset: offset + length]
    return {
        "artifact_id": artifact_id,
        "excerpt": excerpt,
        "offset": offset,
        "length_returned": len(excerpt),
        "total_chars": len(text),
        # Agent loop reads `tainted` from tool result to propagate onto state
        "tainted": is_tainted,
        "warning": (
            "this artifact is tainted (untrusted source). Reading it has "
            "escalated your job's confirmation policy for writes/execution."
            if is_tainted else None
        ),
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
    # Top-level taint surfacing — parallels tools.memory.recall (Codex round-2
    # #4) and tools.knowledge.recall_knowledge. Without this, a list that
    # includes tainted artifacts (or tainted names/tags that made it through
    # a prior fetch_url → save_artifact path) flows through to the model
    # without escalating subsequent memory writes / run_python confirmations.
    # JobContext._execute_one only inspects the top-level `tainted` key.
    result: dict[str, Any] = {"count": len(items), "items": items}
    if any(i.get("tainted") for i in items):
        result["tainted"] = True
    return result
