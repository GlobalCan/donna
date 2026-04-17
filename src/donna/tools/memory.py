"""Memory tools — remember / recall / forget over the facts table."""
from __future__ import annotations

from typing import Any

from ..memory import facts as facts_mod
from ..memory.db import connect
from .registry import tool


@tool(
    scope="write_memory", cost="low", confirmation="once_per_job",
    taints_job=False,
    description=(
        "Save a durable fact to long-term memory. If called during a tainted job "
        "(e.g. after fetching a URL), user confirmation is required via Discord "
        "reaction before the write proceeds. Include concise `tags` (comma-sep) "
        "to make future recall easier."
    ),
)
async def remember(
    fact: str,
    tags: str = "",
    agent_scope: str | None = None,
    job_id: str | None = None,
    tainted: bool = False,
) -> dict[str, Any]:
    conn = connect()
    try:
        fid = facts_mod.insert_fact(
            conn,
            fact=fact,
            tags=tags,
            agent_scope=agent_scope,
            written_by_tool="remember",
            written_by_job=job_id,
            tainted=tainted,
        )
    finally:
        conn.close()
    return {"fact_id": fid, "stored": True}


@tool(
    scope="read_memory", cost="low",
    description=(
        "Search long-term memory with a keyword query. Returns up to `limit` "
        "matches, optionally scoped to a specific agent (or NULL for shared)."
    ),
)
async def recall(
    query: str,
    limit: int = 10,
    agent_scope: str | None = None,
) -> dict[str, Any]:
    conn = connect()
    try:
        results = facts_mod.search_facts_fts(
            conn, query, agent_scope=agent_scope, limit=limit,
        )
    finally:
        conn.close()
    return {"query": query, "results": results, "count": len(results)}


@tool(
    scope="write_memory", cost="low", confirmation="always",
    description="Delete a fact by id. Always requires confirmation.",
)
async def forget(fact_id: str) -> dict[str, Any]:
    conn = connect()
    try:
        ok = facts_mod.delete_fact(conn, fact_id)
    finally:
        conn.close()
    return {"fact_id": fact_id, "deleted": ok}
