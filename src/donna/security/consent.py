"""Consent system — 4 modes (never / once_per_job / always / high_impact_always),
Discord reaction approval flow with DB-persistent pending state (Codex #5 fix).

Pending approvals are persisted to `pending_consents` + job.status is set
to 'paused_awaiting_consent' so restarts can resume, re-prompt, and not
silently drop the request."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..logging import get_logger
from ..memory import ids as ids_mod
from ..memory import jobs as jobs_mod
from ..memory import permissions as perm_mod
from ..memory.db import connect, transaction
from ..types import ConfirmationMode, JobStatus, ToolEntry
from .taint import effective_confirmation

log = get_logger(__name__)


@dataclass
class ConsentRequest:
    job_id: str
    tool_entry: ToolEntry
    arguments: dict[str, Any]
    tainted: bool
    future: asyncio.Future[bool]
    pending_id: str | None = None   # row id in pending_consents, for cleanup


@dataclass
class ConsentResult:
    approved: bool
    reason: str = ""


# Outbox queue drained by Discord adapter
_consent_queue: asyncio.Queue[ConsentRequest] | None = None


def init_queue() -> None:
    global _consent_queue
    if _consent_queue is None:
        _consent_queue = asyncio.Queue()


def consent_queue() -> asyncio.Queue[ConsentRequest]:
    init_queue()
    assert _consent_queue is not None
    return _consent_queue


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
    # ALWAYS or HIGH_IMPACT_ALWAYS: always prompt; don't honor existing grants for HIGH_IMPACT

    # Persist pending state BEFORE enqueuing so restarts can recover
    pending_id = _persist_pending(
        job_id=job_id, tool_name=entry.name, arguments=arguments, tainted=tainted,
    )

    fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
    await consent_queue().put(
        ConsentRequest(
            job_id=job_id, tool_entry=entry, arguments=arguments,
            tainted=tainted, future=fut, pending_id=pending_id,
        )
    )
    try:
        approved = await asyncio.wait_for(fut, timeout=1800)  # 30 min
    except asyncio.TimeoutError:
        _clear_pending(pending_id)
        _resume_job_status(job_id)
        return ConsentResult(approved=False, reason="timeout")

    _clear_pending(pending_id)
    _resume_job_status(job_id)

    if approved and mode == ConfirmationMode.ONCE_PER_JOB:
        conn = connect()
        try:
            perm_mod.insert_grant(conn, job_id=job_id, tool_name=entry.name, scope="job")
        finally:
            conn.close()

    return ConsentResult(
        approved=approved,
        reason="user approved" if approved else "user declined",
    )


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
            "SELECT id, job_id, tool_name, arguments, tainted, created_at "
            "FROM pending_consents ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
