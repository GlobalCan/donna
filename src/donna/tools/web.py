"""Web tools — search_web, fetch_url, search_news. All taint-marking."""
from __future__ import annotations

import asyncio
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
        "Search the web via Tavily. Returns titles + URLs + sanitized snippets. "
        "Snippets from untrusted sources are run through a quarantined Haiku "
        "call that strips embedded instructions before returning to the agent. "
        "Tainted — downstream memory writes require confirmation."
    ),
)
async def search_web(query: str, max_results: int = 8) -> dict[str, Any]:
    res = await _tv().search(query=query, max_results=max_results, search_depth="basic")
    hits = res.get("results", [])
    sanitized_hits = await _sanitize_hits(hits, "search_web")
    return {
        "query": query,
        "hits": sanitized_hits,
        "count": len(sanitized_hits),
        "warning": "snippets sanitized via dual-call; raw content is tainted",
    }


@tool(
    scope="read_web", cost="low", taints_job=True,
    description=(
        "Search news via Tavily (recency-weighted). Snippets sanitized like "
        "search_web. Tainted."
    ),
)
async def search_news(query: str, max_results: int = 8, days: int = 7) -> dict[str, Any]:
    res = await _tv().search(
        query=query, max_results=max_results, topic="news", days=days, search_depth="basic",
    )
    hits = res.get("results", [])
    sanitized_hits = await _sanitize_hits(hits, "search_news")
    # Preserve the published_date field in news results
    for h, raw in zip(sanitized_hits, hits, strict=False):
        if raw.get("published_date"):
            h["published"] = raw["published_date"]
    return {
        "query": query,
        "hits": sanitized_hits,
        "count": len(sanitized_hits),
        "warning": "snippets sanitized via dual-call; raw content is tainted",
    }


async def _sanitize_hits(hits: list, source_tool: str) -> list[dict[str, Any]]:
    """Codex review #4 fix — dual-call sanitize every search snippet before
    returning to the privileged model context. Fetch_url was the only sanitized
    path before; this closes the gap."""
    from ..security.sanitize import sanitize_untrusted

    out: list[dict[str, Any]] = []
    # Sanitize in parallel — these are independent Haiku calls
    tasks = []
    for h in hits:
        raw_snippet = (h.get("content", "") or "")[:2000]
        if not raw_snippet.strip():
            tasks.append(None)
        else:
            tasks.append(
                sanitize_untrusted(
                    raw_snippet,
                    artifact_id=f"search:{source_tool}:{h.get('url','')}",
                    source_url=h.get("url"),
                )
            )
    results = await asyncio.gather(
        *[t for t in tasks if t is not None],
        return_exceptions=True,
    )
    result_iter = iter(results)
    for h, task in zip(hits, tasks, strict=False):
        if task is None:
            sanitized = ""
        else:
            r = next(result_iter)
            sanitized = (
                r if isinstance(r, str) else f"[sanitize_error: {r}]"
            )
        out.append({
            "title": h.get("title"),
            "url": h.get("url"),
            "snippet": sanitized,
            "raw_snippet_length": len(h.get("content", "") or ""),
        })
    return out


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
    # Wikipedia's user-agent policy requires name/version with a real URL
    # contact marker in parens (not a free-text tag like "+personal"), and
    # browser-typical Accept headers. The prior UA `DonnaBot/0.1 (+personal)`
    # got 403s on en.wikipedia.org.
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True,
        headers={
            "User-Agent": (
                "Donna/0.2 (+https://github.com/GlobalCan/donna; "
                "solo-operator personal AI assistant) httpx"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.text

    rendered = markdownify(raw, heading_style="ATX") if format == "markdown" else raw

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
