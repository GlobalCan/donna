"""Attachment tools — let the agent ingest a Discord-attached file.

Codex review #14 fix: previously PDF/document ingestion lived only in
`botctl teach` (CLI). Now the agent itself can consume an attachment that
arrived in a Discord message and route it through the same ingestion
pipeline.
"""
from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

import httpx

from ..config import settings
from ..logging import get_logger
from .registry import tool

log = get_logger(__name__)

# Caps on untrusted attachment materialization. Codex adversarial scan #4:
# without these, a model-chosen attachment_url pointing at a multi-hundred-MB
# PDF would download in full, pypdf extraction would fan out across every
# page, and the worker's 512MB container memory cap would likely be hit
# before the ingest pipeline's chunker sees anything.
_ATTACH_MAX_BYTES = 10 * 1024 * 1024      # 10 MB — a large novel PDF
_ATTACH_MAX_PDF_PAGES = 500
_ATTACH_MAX_TEXT_CHARS = 1_000_000        # ~250k tokens — above that, chunk before us


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

    async with httpx.AsyncClient(  # noqa: SIM117 (client needed before stream)
        timeout=60.0, follow_redirects=True,
        headers={"User-Agent": "DonnaBot/0.1 (+personal)"},
    ) as client:
        # Stream so oversized attachments abort before we hold the whole
        # payload in memory.
        async with client.stream("GET", attachment_url) as r:
            r.raise_for_status()
            declared_len = r.headers.get("content-length")
            if declared_len and declared_len.isdigit() and int(declared_len) > _ATTACH_MAX_BYTES:
                return {
                    "error": "content_length_exceeds_cap",
                    "content_length": int(declared_len),
                    "max_bytes": _ATTACH_MAX_BYTES,
                    "url": attachment_url,
                }
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > _ATTACH_MAX_BYTES:
                    return {
                        "error": "download_exceeded_cap",
                        "max_bytes": _ATTACH_MAX_BYTES,
                        "url": attachment_url,
                    }
            data = bytes(buf)

    # Infer type from URL. Fixed-name path was a concurrency footgun
    # (cross-vendor review #15 / Codex GPT-5 RF): two simultaneous ingests
    # with the same extension would overwrite each other's bytes mid-read.
    # Solo-bot rarely hits this today, but `/teach` flows that fan out into
    # multiple attachments will. UUID suffix makes each call's tempfile
    # unique without reaching for NamedTemporaryFile (which complicates
    # the cleanup-on-error story).
    import uuid
    ext = Path(attachment_url.split("?", 1)[0]).suffix.lower()
    dest = tmp_dir / f"attach_{uuid.uuid4().hex[:12]}{ext or '.bin'}"
    dest.write_bytes(data)

    # Extract text
    pages_read = 0
    truncated_chars = False
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(dest))
            parts: list[str] = []
            for page in reader.pages[:_ATTACH_MAX_PDF_PAGES]:
                parts.append(page.extract_text() or "")
                pages_read += 1
            text = "\n\n".join(parts)
        elif ext in (".md", ".txt", ".markdown", ""):
            text = data.decode("utf-8", errors="replace")
        else:
            return {
                "error": f"unsupported file type: {ext}",
                "bytes": len(data),
                "url": attachment_url,
            }
        if len(text) > _ATTACH_MAX_TEXT_CHARS:
            text = text[:_ATTACH_MAX_TEXT_CHARS]
            truncated_chars = True
    except Exception as e:
        return {"error": f"extraction_failed: {e}", "url": attachment_url}
    finally:
        with suppress(OSError):
            dest.unlink()

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
        # Codex round-2 #4: source is from Discord, which we treat as
        # untrusted. Persist that fact so later reads re-taint.
        tainted=True,
    )
    # Propagate taint — untrusted source
    result["tainted"] = True
    result["source_url"] = attachment_url
    if ext == ".pdf":
        result["pages_read"] = pages_read
    result["truncated_chars"] = truncated_chars
    return result
