"""End-to-end ingestion: text → chunks → fingerprint → dedupe → embed → store."""
from __future__ import annotations

from typing import Any

from ..logging import get_logger
from ..memory import artifacts as artifacts_mod
from ..memory import knowledge as kn
from ..memory.db import connect, transaction
from .chunk import chunk_text
from .embed import embed_documents

log = get_logger(__name__)


async def ingest_text(
    *,
    scope: str,
    source_type: str,
    title: str,
    content: str,
    copyright_status: str,
    publication_date: str | None = None,
    work_id: str | None = None,
    author_period: str | None = None,
    added_by: str = "user",
    tainted: bool = False,
) -> dict[str, Any]:
    """Ingest raw text under a scope. Returns ingestion stats.

    ``tainted=True`` flows through to the persisted source artifact AND the
    knowledge_sources row, so future jobs that read this material via
    recall_knowledge re-taint themselves (Codex round-2 #4). Without the
    flag, untrusted content (Discord attachments, web pulls) ingested in
    one job appears clean to any later job.
    """
    if not content.strip():
        return {"error": "empty content"}

    # Preserve the source as an artifact for provenance — mirrors the
    # tainted flag so read_artifact on the source also propagates taint.
    conn = connect()
    try:
        art = artifacts_mod.save_artifact(
            conn, content=content, name=f"source:{title}",
            mime="text/plain", tags="knowledge,source", tainted=tainted,
        )
        src_id = kn.insert_source(
            conn,
            agent_scope=scope,
            source_type=source_type,
            work_id=work_id or art["artifact_id"],
            title=title,
            publication_date=publication_date,
            author_period=author_period,
            source_ref=str(art["artifact_id"]),
            copyright_status=copyright_status,
            added_by=added_by,
            tainted=tainted,
        )
    finally:
        conn.close()

    # Chunk
    chunks = chunk_text(content)
    if not chunks:
        return {"source_id": src_id, "chunks_added": 0, "chunks_deduped": 0}

    # Fingerprint + dedupe-against-scope AND within-batch
    # (Codex audit: prior version embedded within-batch duplicates and then
    # dropped them at insert time, wasting embedding tokens + overstating
    # chunks_added counts.)
    to_embed: list[tuple[int, str, str, str]] = []  # (index, content, fingerprint, token_count-ish)
    seen_fp_this_batch: set[str] = set()
    skipped_dup = 0
    conn = connect()
    try:
        for ch in chunks:
            fp = kn.fingerprint_text(ch.content)
            if fp in seen_fp_this_batch:
                skipped_dup += 1
                continue
            existing = conn.execute(
                "SELECT 1 FROM knowledge_chunks WHERE agent_scope = ? AND fingerprint = ? LIMIT 1",
                (scope, fp),
            ).fetchone()
            if existing:
                skipped_dup += 1
                continue
            seen_fp_this_batch.add(fp)
            to_embed.append((ch.index, ch.content, fp, ch.token_count))
    finally:
        conn.close()

    if not to_embed:
        return {
            "source_id": src_id, "chunks_added": 0,
            "chunks_deduped": skipped_dup, "total_chunks": len(chunks),
        }

    # Embed in one batched call
    embeddings = await embed_documents([c[1] for c in to_embed])

    conn = connect()
    try:
        with transaction(conn):
            for (idx, content_txt, fp, tokens), emb in zip(to_embed, embeddings, strict=True):
                kn.insert_chunk(
                    conn,
                    source_id=src_id,
                    agent_scope=scope,
                    content=content_txt,
                    chunk_index=idx,
                    fingerprint=fp,
                    embedding=emb,
                    work_id=work_id,
                    publication_date=publication_date,
                    source_type=source_type,
                    token_count=tokens,
                )
    finally:
        conn.close()

    log.info(
        "ingest.done",
        scope=scope, source_id=src_id,
        chunks_added=len(to_embed), chunks_deduped=skipped_dup,
    )
    return {
        "source_id": src_id,
        "chunks_added": len(to_embed),
        "chunks_deduped": skipped_dup,
        "total_chunks": len(chunks),
        "artifact_id": art["artifact_id"],
    }
