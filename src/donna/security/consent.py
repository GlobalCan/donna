"""Consent system — 4 modes (never / once_per_job / always / high_impact_always).

All state lives in `pending_consents`. The worker INSERTs a row, then polls
the `approved` column; the bot posts the prompt in Discord, records the
message id on the row, and on reaction UPDATEs `approved`. This works
across the bot/worker process boundary.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from ..logging import get_logger
from ..memory import ids as ids_mod
from ..memory import permissions as perm_mod
from ..memory.db import connect, transaction
from ..types import ConfirmationMode, JobStatus, ToolEntry
from .taint import effective_confirmation

log = get_logger(__name__)


@dataclass
class ConsentRequest:
    """Transfer object for the Discord adapter's post method.

    Kept as a dataclass (not a dict) so type-hints and `consent_embed()`
    access the same shape whether built from a DB row or constructed in-test.
    `pending_id` is the `pending_consents.id` — the primary key the
    reaction handler uses to record the decision.
    """
    job_id: str
    tool_entry: ToolEntry
    arguments: dict[str, Any]
    tainted: bool
    pending_id: str


@dataclass
class ConsentResult:
    approved: bool
    reason: str = ""


# Polling interval the worker uses while waiting for the user's reaction.
_POLL_INTERVAL_S = 2.0
# Matches prior behavior.
_CONSENT_TIMEOUT_S = 1800.0


async def check(
    *,
    job_id: str,
    entry: ToolEntry,
    arguments: dict[str, Any],
    tainted: bool,
) -> ConsentResult:
    """Evaluate whether a tool call proceeds, blocks for approval, or is auto-approved."""
    mode = effective_confirmation(entry, job_tainted=tainted)

    if mode == ConfirmationMode.NEVER:
        return ConsentResult(approved=True)

    if mode == ConfirmationMode.ONCE_PER_JOB:
        conn = connect()
        try:
            if perm_mod.has_grant(conn, job_id=job_id, tool_name=entry.name):
                return ConsentResult(approved=True, reason="existing grant")
        finally:
            conn.close()
        # Fall through to prompt

    # Persist pending state. The bot's drain task will pick this up and post.
    pending_id = _persist_pending(
        job_id=job_id, tool_name=entry.name, arguments=arguments, tainted=tainted,
    )

    loop = asyncio.get_event_loop()
    deadline = loop.time() + _CONSENT_TIMEOUT_S
    try:
        while loop.time() < deadline:
            await asyncio.sleep(_POLL_INTERVAL_S)
            conn = connect()
            try:
                row = conn.execute(
                    "SELECT approved FROM pending_consents WHERE id = ?",
                    (pending_id,),
                ).fetchone()
            finally:
                conn.close()
            if row is None:
                return ConsentResult(approved=False, reason="cleared")
            if row["approved"] is not None:
                approved = bool(row["approved"])
                if approved and mode == ConfirmationMode.ONCE_PER_JOB:
                    conn = connect()
                    try:
                        perm_mod.insert_grant(
                            conn, job_id=job_id, tool_name=entry.name, scope="job",
                        )
                    finally:
                        conn.close()
                return ConsentResult(
                    approved=approved,
                    reason="user approved" if approved else "user declined",
                )
        return ConsentResult(approved=False, reason="timeout")
    finally:
        _clear_pending(pending_id)
        _resume_job_status(job_id)


# ---------- persistence helpers --------------------------------------------


def _persist_pending(
    *, job_id: str, tool_name: str, arguments: dict, tainted: bool,
) -> str:
    pid = ids_mod.new_id("pend")
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                """
                INSERT INTO pending_consents (id, job_id, tool_name, arguments, tainted)
                VALUES (?, ?, ?, ?, ?)
                """,
                (pid, job_id, tool_name, json.dumps(arguments, default=str),
                 1 if tainted else 0),
            )
            conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ? AND status = 'running'",
                (JobStatus.PAUSED_AWAITING_CONSENT.value, job_id),
            )
    finally:
        conn.close()
    return pid


def _clear_pending(pending_id: str | None) -> None:
    if not pending_id:
        return
    conn = connect()
    try:
        with transaction(conn):
            conn.execute("DELETE FROM pending_consents WHERE id = ?", (pending_id,))
    finally:
        conn.close()


def _resume_job_status(job_id: str) -> None:
    """If there are no more pending consents for this job, flip status back."""
    conn = connect()
    try:
        with transaction(conn):
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM pending_consents WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row["n"] == 0:
                conn.execute(
                    "UPDATE jobs SET status = 'running' WHERE id = ? AND status = ?",
                    (job_id, JobStatus.PAUSED_AWAITING_CONSENT.value),
                )
    finally:
        conn.close()


def list_unresolved_pendings() -> list[dict]:
    """On startup the adapter calls this to find pending consent prompts
    that survived a restart, so they can be re-posted to Discord."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, job_id, tool_name, arguments, tainted, created_at, "
            "posted_channel_id, posted_message_id "
            "FROM pending_consents ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
