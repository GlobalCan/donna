"""Context compaction — triggered every N tool calls.

Replaces the tail of the message list with a Haiku-generated summary +
references to artifacts where full output is preserved.

v1.1 (Hermes-inspired session lineage): before compacting, the pre-compaction
message tail is written to a `compaction:<sha>` artifact. The artifact_id
is appended to state.artifact_refs and recorded in the compaction_log, so
compacted jobs remain auditable — you can `read_artifact(<id>)` to see
what was replaced.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..logging import get_logger
from ..memory import artifacts as artifacts_mod
from ..memory.db import connect, transaction
from ..observability import otel
from ..types import ModelTier
from .model_adapter import model

log = get_logger(__name__)


COMPACT_SYSTEM = (
    "You are compacting the tool-call history of an AI assistant's ongoing job. "
    "Produce a single concise summary (≤ 500 tokens) that preserves:\n"
    " - Facts learned (what questions were answered)\n"
    " - URLs visited (with their topic)\n"
    " - Artifacts created (with their IDs and purpose)\n"
    " - Decisions made\n"
    " - Outstanding open questions\n"
    "Drop: raw tool outputs, exploratory dead ends, repetitive content.\n"
    "Output only the summary, no preamble."
)


async def compact_messages(
    messages: list[dict[str, Any]],
    artifact_refs: list[str],
    *,
    job_id: str | None = None,
) -> list[dict[str, Any]]:
    """Summarize all messages after the first (initial user task) and replace
    them with a single compacted `user` message.

    v1.1 audit trail: before replacing, the raw tail is written to an
    artifact (`compaction:<job>:<n>`) and its id is appended to artifact_refs
    + recorded in the job's compaction_log. Recoverable via read_artifact.
    """
    if len(messages) <= 3:
        return messages

    initial = messages[0]  # first user task
    to_compact = messages[1:]

    # Codex Pass-2 #15 + Hermes lineage steal: preserve the raw tail as an
    # artifact BEFORE we summarize and drop it.
    raw_tail = json.dumps(to_compact, indent=2, default=str)
    saved_artifact_id: str | None = None
    try:
        conn = connect()
        try:
            with transaction(conn):
                saved = artifacts_mod.save_artifact(
                    conn,
                    content=raw_tail,
                    name=f"compaction:{job_id or 'unknown'}:{len(to_compact)}turns",
                    mime="application/json",
                    tags="compaction,audit",
                    tainted=False,
                    created_by_job=job_id,
                )
                saved_artifact_id = str(saved.get("artifact_id"))
                # Also append to the job's compaction_log for a queryable lineage
                if job_id:
                    row = conn.execute(
                        "SELECT compaction_log FROM jobs WHERE id = ?", (job_id,),
                    ).fetchone()
                    existing = []
                    if row and row["compaction_log"]:
                        try:
                            existing = json.loads(row["compaction_log"])
                        except json.JSONDecodeError:
                            existing = []
                    existing.append({
                        "artifact_id": saved_artifact_id,
                        "replaced_count": len(to_compact),
                        "at": datetime.now(timezone.utc).isoformat(),
                    })
                    conn.execute(
                        "UPDATE jobs SET compaction_log = ? WHERE id = ?",
                        (json.dumps(existing), job_id),
                    )
        finally:
            conn.close()
    except Exception as e:
        log.warning("agent.compact.audit_save_failed", error=str(e))

    tail_text = raw_tail[:40_000]
    with otel.span(
        "agent.compact",
        **{
            "compact.input_chars": len(tail_text),
            "compact.audit_artifact": saved_artifact_id,
            "agent.job.id": job_id,
        },
    ):
        result = await model().generate(
            system=COMPACT_SYSTEM,
            messages=[{"role": "user", "content": tail_text}],
            tier=ModelTier.FAST,
            max_tokens=1200,
            job_id=job_id,
        )
    summary = result.text

    all_refs = list(artifact_refs)
    if saved_artifact_id:
        all_refs.append(saved_artifact_id)

    art_ref_line = ""
    if all_refs:
        art_ref_line = (
            f"\n\nArtifacts available (use read_artifact): "
            f"{', '.join(all_refs[-20:])}"
        )

    audit_line = (
        f"\n\nFull pre-compaction history archived at artifact `{saved_artifact_id}`."
        if saved_artifact_id else ""
    )

    compacted = {
        "role": "user",
        "content": (
            f"[CONTEXT COMPACTED — {len(to_compact)} prior messages replaced]\n"
            f"{summary}{art_ref_line}{audit_line}"
        ),
    }
    log.info(
        "agent.compact.done",
        job_id=job_id, replaced=len(to_compact),
        summary_len=len(summary), audit_artifact=saved_artifact_id,
    )
    return [initial, compacted]
