"""Knowledge tools — teach, recall_knowledge, recall_examples, recall_heuristics,
propose_heuristic, list_knowledge, update_prompt."""
from __future__ import annotations

from typing import Any, Literal

from ..memory import knowledge as kn
from ..memory import prompts as prompts_mod
from ..memory.db import connect
from .registry import tool


@tool(
    scope="write_knowledge", cost="medium", confirmation="once_per_job",
    description=(
        "Ingest content into a scope's knowledge corpus. Source is chunked, "
        "deduplicated by fingerprint, embedded via Voyage, and stored. "
        "Call once per source; use `/teach` slash command for bulk."
    ),
)
async def teach(
    scope: str,
    source_type: Literal["book", "article", "interview", "podcast", "tweet", "transcript", "other"],
    title: str,
    content: str,
    copyright_status: Literal["public_domain", "personal_use", "licensed", "public_web"],
    publication_date: str = "",
    work_id: str = "",
    job_id: str | None = None,
) -> dict[str, Any]:
    # Defer to ingest pipeline — avoids circular import.
    from ..ingest.pipeline import ingest_text

    return await ingest_text(
        scope=scope,
        source_type=source_type,
        title=title,
        content=content,
        copyright_status=copyright_status,
        publication_date=publication_date or None,
        work_id=work_id or None,
        added_by=f"tool:teach:job:{job_id}" if job_id else "tool:teach",
    )


@tool(
    scope="read_knowledge", cost="low",
    description=(
        "Retrieve the top-K most relevant knowledge chunks from a scope's corpus "
        "for a given query. Uses hybrid semantic + keyword retrieval with "
        "diversity constraints (max 2/work, max 3/source_type)."
    ),
)
async def recall_knowledge(
    scope: str,
    query: str,
    top_k: int = 8,
    style_anchors_only: bool = False,
) -> dict[str, Any]:
    from ..modes.retrieval import retrieve_knowledge

    out = await retrieve_knowledge(
        scope=scope, query=query, top_k=top_k, style_anchors_only=style_anchors_only
    )
    # Codex round-2 #4: surface top-level `tainted=True` when any returned
    # chunk's source was ingested from an untrusted origin. Mirrors the
    # same mechanism `tools.memory.recall` uses for facts. Without this,
    # taint doesn't flow through the recall_knowledge boundary into
    # JobContext._execute_one's taint-propagation check, and future
    # memory writes / code exec skip escalated confirmation.
    chunks = out.get("chunks") or []
    if chunks:
        source_ids = list({c.source_id for c in chunks if getattr(c, "source_id", None)})
        if source_ids:
            conn = connect()
            try:
                placeholders = ",".join("?" * len(source_ids))
                rows = conn.execute(
                    f"SELECT 1 FROM knowledge_sources "
                    f"WHERE id IN ({placeholders}) AND tainted = 1 LIMIT 1",
                    source_ids,
                ).fetchone()
            finally:
                conn.close()
            if rows is not None:
                out = {**out, "tainted": True}
    return out


@tool(
    scope="read_knowledge", cost="low",
    description="List all knowledge sources for a scope.",
)
async def list_knowledge(scope: str) -> dict[str, Any]:
    conn = connect()
    try:
        items = kn.list_sources(conn, agent_scope=scope)
    finally:
        conn.close()
    # Top-level taint surfacing — same rationale as recall_knowledge and
    # list_artifacts. A tainted knowledge_sources row (from a tainted
    # ingest_discord_attachment path) flows its title/source_ref text into
    # the model context; propagate taint so subsequent writes escalate.
    result: dict[str, Any] = {"scope": scope, "sources": items, "count": len(items)}
    if any(i.get("tainted") for i in items):
        result["tainted"] = True
    return result


@tool(
    scope="read_knowledge", cost="low",
    description="Load the scope's currently active heuristics (reasoning rules).",
)
async def recall_heuristics(scope: str) -> dict[str, Any]:
    conn = connect()
    try:
        items = prompts_mod.active_heuristics(conn, scope)
    finally:
        conn.close()
    return {"scope": scope, "heuristics": items}


@tool(
    scope="write_knowledge", cost="low",
    description=(
        "Propose a new heuristic for a scope. Status begins as 'proposed'. "
        "User must approve via Discord for it to become active. Never auto-applies. "
        "The `reasoning` is persisted alongside the heuristic for audit."
    ),
)
async def propose_heuristic(
    scope: str,
    heuristic: str,
    reasoning: str = "",
    job_id: str | None = None,
) -> dict[str, Any]:
    conn = connect()
    try:
        hid = prompts_mod.insert_heuristic(
            conn, agent_scope=scope, heuristic=heuristic,
            provenance=f"reflection:job:{job_id}" if job_id else "user",
            status="proposed",
            reasoning=reasoning or None,
        )
    finally:
        conn.close()
    return {"heuristic_id": hid, "status": "proposed", "reasoning": reasoning}
