"""Web tools — search_web, fetch_url, search_news. All taint-marking."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

import httpx
from markdownify import markdownify
from tavily import AsyncTavilyClient

from ..config import settings
from ..logging import get_logger
from ..memory import artifacts as artifacts_mod
from ..memory.db import connect
from .registry import tool

log = get_logger(__name__)

_tavily: AsyncTavilyClient | None = None


def _tv() -> AsyncTavilyClient:
    global _tavily
    if _tavily is None:
        _tavily = AsyncTavilyClient(api_key=settings().tavily_api_key)
    return _tavily


@tool(
    scope="read_web", cost="low", taints_job=True,
    description=(
        "Search the web via Tavily. Returns up to `max_results` hits with title, "
        "URL, snippet. Tainted — downstream memory writes require confirmation."
    ),
)
async def search_web(query: str, max_results: int = 8) -> dict[str, Any]:
    res = await _tv().search(query=query, max_results=max_results, search_depth="basic")
    hits = res.get("results", [])
    return {
        "query": query,
        "hits": [
            {"title": h.get("title"), "url": h.get("url"), "snippet": h.get("content", "")[:500]}
            for h in hits
        ],
        "count": len(hits),
    }


@tool(
    scope="read_web", cost="low", taints_job=True,
    description=(
        "Search news via Tavily (recency-weighted). Same shape as search_web. "
        "Tainted."
    ),
)
async def search_news(query: str, max_results: int = 8, days: int = 7) -> dict[str, Any]:
    res = await _tv().search(
        query=query, max_results=max_results, topic="news", days=days, search_depth="basic",
    )
    hits = res.get("results", [])
    return {
        "query": query,
        "hits": [
            {
                "title": h.get("title"),
                "url": h.get("url"),
                "snippet": h.get("content", "")[:500],
                "published": h.get("published_date"),
            }
            for h in hits
        ],
        "count": len(hits),
    }


@tool(
    scope="read_web", cost="low", taints_job=True,
    description=(
        "Fetch a URL. Content is sanitized via a quarantined Haiku call before "
        "being returned to the agent. Raw content is saved as a tainted artifact "
        "addressable via read_artifact. The returned `sanitized_summary` has been "
        "stripped of any embedded prompt-injection instructions."
    ),
)
async def fetch_url(
    url: str,
    format: Literal["text", "markdown"] = "markdown",
    job_id: str | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True,
        headers={"User-Agent": "DonnaBot/0.1 (+personal)"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.text

    if format == "markdown":
        rendered = markdownify(raw, heading_style="ATX")
    else:
        rendered = raw

    # Save raw as tainted artifact
    conn = connect()
    try:
        art = artifacts_mod.save_artifact(
            conn,
            content=rendered,
            name=f"fetch:{url}",
            mime="text/markdown" if format == "markdown" else "text/html",
            tags="fetch,tainted",
            tainted=True,
            created_by_job=job_id,
        )
    finally:
        conn.close()

    # Dual-call sanitization (deferred to security.sanitize to avoid circular import)
    from ..security.sanitize import sanitize_untrusted
    summary = await sanitize_untrusted(rendered, artifact_id=art["artifact_id"], source_url=url)

    return {
        "url": url,
        "sanitized_summary": summary,
        "bytes": art["bytes"],
        "sha256": art["sha256"],
        "artifact_id": art["artifact_id"],
        "warning": "tainted — any memory write / code exec from this job will require confirmation",
    }
