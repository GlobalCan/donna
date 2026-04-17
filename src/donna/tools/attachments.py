"""Attachment tools — let the agent ingest a Discord-attached file.

Codex review #14 fix: previously PDF/document ingestion lived only in
`botctl teach` (CLI). Now the agent itself can consume an attachment that
arrived in a Discord message and route it through the same ingestion
pipeline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import httpx

from ..config import settings
from ..logging import get_logger
from .registry import tool

log = get_logger(__name__)


@tool(
    scope="write_knowledge", cost="medium", confirmation="once_per_job",
    description=(
        "Download a Discord attachment URL, extract its text (PDF / txt / md), "
        "and ingest into the named scope's knowledge corpus. Tainted — the "
        "source is untrusted, and any downstream memory writes will require "
        "confirmation."
    ),
    taints_job=True,
)
async def ingest_discord_attachment(
    scope: str,
    attachment_url: str,
    title: str,
    source_type: Literal["book", "article", "interview", "podcast", "transcript", "other"] = "other",
    publication_date: str = "",
    copyright_status: Literal["public_domain", "personal_use", "licensed", "public_web"] = "personal_use",
    job_id: str | None = None,
) -> dict[str, Any]:
    # Fetch the attachment to a temp file
    tmp_dir = settings().data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        timeout=60.0, follow_redirects=True,
        headers={"User-Agent": "DonnaBot/0.1 (+personal)"},
    ) as client:
        r = await client.get(attachment_url)
        r.raise_for_status()
        data = r.content

    # Infer type from URL
    ext = Path(attachment_url.split("?", 1)[0]).suffix.lower()
    dest = tmp_dir / f"attach{ext or '.bin'}"
    dest.write_bytes(data)

    # Extract text
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            text = "\n\n".join(
                (p.extract_text() or "") for p in PdfReader(str(dest)).pages
            )
        elif ext in (".md", ".txt", ".markdown", ""):
            text = data.decode("utf-8", errors="replace")
        else:
            return {
                "error": f"unsupported file type: {ext}",
                "bytes": len(data),
                "url": attachment_url,
            }
    except Exception as e:
        return {"error": f"extraction_failed: {e}", "url": attachment_url}
    finally:
        try:
            dest.unlink()
        except OSError:
            pass

    if not text.strip():
        return {"error": "empty_extracted_text", "url": attachment_url}

    from ..ingest.pipeline import ingest_text
    result = await ingest_text(
        scope=scope,
        source_type=source_type,
        title=title,
        content=text,
        copyright_status=copyright_status,
        publication_date=publication_date or None,
        added_by=f"tool:ingest_discord_attachment:job:{job_id}" if job_id else "tool:ingest_discord_attachment",
    )
    # Propagate taint — untrusted source
    result["tainted"] = True
    result["source_url"] = attachment_url
    return result
