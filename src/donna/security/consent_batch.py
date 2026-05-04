"""Consent batching — one prompt for N consent-required tools in one turn.

Codex 2026-05-01 review item #11 ("operator fatigue"): when the agent
emits multiple consent-gated tool_uses in a single model turn, pre-fix
each one fired its own ✅/❌ button and the operator had to tap the
buttons N times in sequence. Tedious, slow, and a meaningful UX cliff
on multi-step tasks (e.g. two `save_artifact` calls in one turn).

This module collapses the N prompts into one merged batch prompt with
"Approve all" / "Decline all" actions, plus a "Show details" overflow
that expands the batch into per-tool decisions if the operator wants
finer control.

Design constraints satisfied:

1. **Backwards-compatible.** Single-tool consent (the common case)
   uses the existing `consent.check` path unchanged — no batch row
   created. Only when 2+ fresh tool_uses in one tool_step batch
   require consent does the batch path engage.

2. **Trust boundary preserved.** Batch.tainted = OR of all member
   tools' batch-time taint. The Slack prompt uses the more
   conservative icon. Per-tool taint propagation in tool_calls
   stays unchanged — the batch is purely a UX consolidation.

3. **Per-tool override.** Operator hits "Show details" overflow ->
   batch.approved flips to 2 (BATCH_APPROVED_INDIVIDUAL sentinel) and
   each linked pending_consents row reverts to standalone routing,
   as if it had never had a batch_id. The drainer detects this and
   posts each prompt individually.

4. **Owner-guarded creation.** Same lease check as
   `_persist_pending`: stale workers can't poison batch state for a
   job they no longer own.

State machine on `consent_batches.approved`:

  NULL   -> pending; bot has either not posted yet or operator hasn't
           clicked. Drainer will post if posted_message_id IS NULL.
  1      -> approve-all clicked; all linked pending_consents rows get
           approved=1 in the same transaction.
  0      -> decline-all clicked; all linked rows get approved=0.
  2      -> expanded; operator wants per-tool decisions. Linked rows
           are unlinked (batch_id set to NULL) so the legacy single-
           tool drain path takes over.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..logging import get_logger
from ..memory import ids as ids_mod
from ..memory.db import connect, transaction
from ..types import JobStatus, ToolEntry

log = get_logger(__name__)


# Sentinel value for `consent_batches.approved` meaning "operator hit
# Show details — split this batch back into individual prompts."
BATCH_APPROVED_INDIVIDUAL = 2


@dataclass
class BatchedConsentRequest:
    """Transfer object the Slack drainer uses to render a batch prompt.

    `entries` is a list of (tool_entry, arguments, pending_id) triples,
    one per tool_use in the batch, ordered the way the agent produced
    them. The renderer iterates this to build the body.
    """
    job_id: str
    batch_id: str
    tainted: bool
    entries: list[tuple[ToolEntry, dict[str, Any], str]]


def create_batch(
    *,
    job_id: str,
    worker_id: str | None,
    members: list[tuple[ToolEntry, dict[str, Any]]],
    job_tainted: bool,
) -> tuple[str, list[str]] | None:
    """Persist one consent_batches row + N pending_consents rows linked
    to it, all under one transaction. Owner-guarded the same way
    `_persist_pending` is.

    `members` is the ordered list of (tool_entry, args) for the tools
    in this batch that need consent. Caller must have already filtered
    out any entries that auto-approve (NEVER mode or existing job-scope
    grant for ONCE_PER_JOB).

    Returns (batch_id, [pending_id_1, ..., pending_id_N]) on success or
    None if the worker has lost lease (caller should treat each as
    `lease_lost` and bail).
    """
    if len(members) < 2:
        # Single-tool batches don't earn the batch path's overhead.
        # Caller should fall back to the legacy `consent.check` path.
        raise ValueError(
            "create_batch requires >= 2 members; use consent.check for one"
        )

    # Batch is tainted if the job is tainted at batch-creation time, or
    # if any member tool is taint-marking (matches the per-tool render
    # logic that uses job_tainted at consent time).
    batch_tainted = bool(job_tainted) or any(
        e.taints_job for e, _ in members
    )
    batch_id = ids_mod.new_id("cb")
    pending_ids: list[str] = []

    conn = connect()
    try:
        with transaction(conn):
            # Same lease-loss guard as _persist_pending: refuse to
            # write any batch state if we no longer own this job.
            if worker_id is not None:
                row = conn.execute(
                    "SELECT owner, status FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if (
                    row is None
                    or row["owner"] != worker_id
                    or row["status"] != "running"
                ):
                    return None

            conn.execute(
                "INSERT INTO consent_batches "
                "(id, job_id, worker_id, tainted) VALUES (?, ?, ?, ?)",
                (batch_id, job_id, worker_id, 1 if batch_tainted else 0),
            )
            for entry, args in members:
                pid = ids_mod.new_id("pend")
                conn.execute(
                    "INSERT INTO pending_consents "
                    "(id, job_id, tool_name, arguments, tainted, batch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        pid,
                        job_id,
                        entry.name,
                        json.dumps(args, default=str),
                        1 if (job_tainted or entry.taints_job) else 0,
                        batch_id,
                    ),
                )
                pending_ids.append(pid)

            # Mirror the per-tool path: flip job to PAUSED_AWAITING_CONSENT
            # so the watchdog can flag a stuck batch the same way it
            # flags a stuck individual prompt.
            if worker_id is not None:
                conn.execute(
                    "UPDATE jobs SET status = ? "
                    "WHERE id = ? AND owner = ? AND status = 'running'",
                    (
                        JobStatus.PAUSED_AWAITING_CONSENT.value,
                        job_id,
                        worker_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status = ? "
                    "WHERE id = ? AND status = 'running'",
                    (JobStatus.PAUSED_AWAITING_CONSENT.value, job_id),
                )
    finally:
        conn.close()
    return batch_id, pending_ids


def resolve_batch(*, batch_id: str, approved: int) -> bool:
    """Apply an approve-all (1) or decline-all (0) decision to all
    pending_consents rows linked to this batch, in one transaction.

    Returns True if rows were actually updated (i.e. this is the first
    decision; double-clicks are no-ops because we guard on
    `approved IS NULL`). Caller can use the bool to decide whether to
    chat.update the posted message.
    """
    if approved not in (0, 1):
        raise ValueError(
            f"approved must be 0 or 1 for resolve_batch, got {approved!r}"
        )
    conn = connect()
    try:
        with transaction(conn):
            cur = conn.execute(
                "UPDATE consent_batches "
                "SET approved = ?, decided_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND approved IS NULL",
                (approved, batch_id),
            )
            if cur.rowcount == 0:
                return False
            # Cascade the decision to every linked pending_consents row.
            # `approved IS NULL` ensures we don't re-decide rows that
            # somehow got their own per-tool resolution first (e.g.
            # operator expanded then decided one tool).
            conn.execute(
                "UPDATE pending_consents "
                "SET approved = ?, decided_at = CURRENT_TIMESTAMP "
                "WHERE batch_id = ? AND approved IS NULL",
                (approved, batch_id),
            )
    finally:
        conn.close()
    return True


def expand_batch(*, batch_id: str) -> bool:
    """Operator hit "Show details" — flip the batch to "individual" mode
    so the existing single-prompt drainer takes over.

    Concretely: set `consent_batches.approved = 2` (sentinel) and clear
    `pending_consents.batch_id` for every linked row. The drainer's
    "post-if-not-posted" gate will then re-post each row as a normal
    single-tool prompt because `posted_message_id` is still NULL.

    Returns True on first expansion; False if already expanded /
    decided. (Idempotent; safe to invoke twice.)
    """
    conn = connect()
    try:
        with transaction(conn):
            cur = conn.execute(
                "UPDATE consent_batches "
                "SET approved = ?, decided_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND approved IS NULL",
                (BATCH_APPROVED_INDIVIDUAL, batch_id),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                "UPDATE pending_consents SET batch_id = NULL "
                "WHERE batch_id = ? AND approved IS NULL",
                (batch_id,),
            )
    finally:
        conn.close()
    return True


def list_unposted_batches() -> list[dict]:
    """On startup the bot checks for batches that survived a restart so
    they can be re-posted. Returns batches whose approval is still
    pending and whose prompt has not yet been posted.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, job_id, tainted, posted_channel_id, posted_message_id, "
            "       created_at "
            "FROM consent_batches "
            "WHERE approved IS NULL AND posted_message_id IS NULL "
            "ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def load_batch_members(batch_id: str) -> list[dict]:
    """Return the pending_consents rows linked to this batch in
    insertion order (the order the agent emitted them). Used by the
    Slack drainer to render the batch prompt body.

    Ordering: SQLite's CURRENT_TIMESTAMP is second-granularity so
    multiple rows inserted in the same transaction share a created_at.
    rowid is monotonic per insert and breaks the tie deterministically
    so the rendered prompt matches the agent's tool_use emission order.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, job_id, tool_name, arguments, tainted "
            "FROM pending_consents "
            "WHERE batch_id = ? "
            "ORDER BY rowid",
            (batch_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def mark_batch_posted(
    *, batch_id: str, channel_id: str, message_id: str,
) -> None:
    """The drainer calls this after successfully posting the merged
    Block Kit message so the next drain tick doesn't re-post."""
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE consent_batches "
                "SET posted_channel_id = ?, posted_message_id = ? "
                "WHERE id = ?",
                (channel_id, message_id, batch_id),
            )
    finally:
        conn.close()


def get_batch(batch_id: str) -> dict | None:
    """Inspect a batch row. Used by the action handlers to look up the
    posted message + status before applying a decision.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM consent_batches WHERE id = ?", (batch_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None
