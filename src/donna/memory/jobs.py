"""Jobs table primitives."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from ..types import Job, JobMode, JobStatus
from . import ids


def insert_job(
    conn: sqlite3.Connection,
    *,
    task: str,
    agent_scope: str = "orchestrator",
    mode: JobMode = JobMode.CHAT,
    thread_id: str | None = None,
    schedule_id: str | None = None,
    priority: int = 5,
) -> str:
    """Insert a queued job row.

    `schedule_id` (v0.6.3) back-links to the originating schedule for
    scheduler-fired jobs. Lets the Slack adapter's
    `_resolve_channel_for_job` prefer `schedules.target_channel_id` over
    the (potentially stale) thread.channel_id when delivering scheduled
    output. NULL for interactive jobs (DM, /donna_ask, app_mention).
    """
    jid = ids.job_id()
    conn.execute(
        """
        INSERT INTO jobs
            (id, thread_id, schedule_id, agent_scope, task, mode, status, priority)
        VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
        """,
        (jid, thread_id, schedule_id, agent_scope, task, mode.value, priority),
    )
    return jid


def claim_next_queued(conn: sqlite3.Connection, worker_id: str, ttl_seconds: int = 300) -> Job | None:
    """Atomic claim of the oldest queued job (or reclaim an expired lease).

    Returns the Job, or None if nothing available.
    """
    now = datetime.now(UTC)
    lease_until = now + timedelta(seconds=ttl_seconds)

    # Atomic UPDATE...RETURNING — pick a job that is either queued-unowned
    # or has an expired lease.
    row = conn.execute(
        """
        UPDATE jobs
        SET status = 'running',
            owner = ?,
            lease_until = ?,
            heartbeat_at = ?,
            started_at = COALESCE(started_at, ?)
        WHERE id = (
            SELECT id FROM jobs
            WHERE status IN ('queued', 'running')
              AND (
                    owner IS NULL
                 OR lease_until < ?
              )
            ORDER BY priority ASC, created_at ASC
            LIMIT 1
        )
        RETURNING id
        """,
        (worker_id, lease_until, now, now, now),
    ).fetchone()

    if row is None:
        return None
    return get_job(conn, row["id"])


def renew_lease(conn: sqlite3.Connection, job_id: str, worker_id: str, ttl_seconds: int = 300) -> bool:
    now = datetime.now(UTC)
    cur = conn.execute(
        """
        UPDATE jobs
        SET lease_until = ?, heartbeat_at = ?
        WHERE id = ? AND owner = ?
        """,
        (now + timedelta(seconds=ttl_seconds), now, job_id, worker_id),
    )
    return cur.rowcount > 0


def save_checkpoint(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    state: dict[str, Any],
    tainted: bool,
    taint_source_tool: str | None,
    tool_call_count: int,
    worker_id: str | None = None,
) -> bool:
    """Write checkpoint. If worker_id is passed, write is conditional on
    owner match — returns False if the lease has been taken by another worker.

    Deliberately does NOT write `cost_usd` — that's incremented authoritatively
    by the cost ledger (record_llm_usage) and must not be clobbered from
    stale in-memory state.
    """
    if worker_id is not None:
        cur = conn.execute(
            """
            UPDATE jobs
            SET checkpoint_state = ?,
                tainted = ?,
                taint_source_tool = ?,
                tool_call_count = ?
            WHERE id = ? AND owner = ?
            """,
            (
                json.dumps(state),
                1 if tainted else 0,
                taint_source_tool,
                tool_call_count,
                job_id,
                worker_id,
            ),
        )
        return cur.rowcount > 0
    conn.execute(
        """
        UPDATE jobs
        SET checkpoint_state = ?,
            tainted = ?,
            taint_source_tool = ?,
            tool_call_count = ?
        WHERE id = ?
        """,
        (
            json.dumps(state),
            1 if tainted else 0,
            taint_source_tool,
            tool_call_count,
            job_id,
        ),
    )
    return True


def set_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: JobStatus,
    *,
    error: str | None = None,
    worker_id: str | None = None,
) -> bool:
    """Transition job status. If worker_id is passed, transition is conditional
    on owner match — returns False if the lease was lost."""
    finished = status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)
    if finished:
        if worker_id is not None:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status = ?, finished_at = ?, error = ?, owner = NULL, lease_until = NULL
                WHERE id = ? AND owner = ?
                """,
                (status.value, datetime.now(UTC), error, job_id, worker_id),
            )
            return cur.rowcount > 0
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, finished_at = ?, error = ?, owner = NULL, lease_until = NULL
            WHERE id = ?
            """,
            (status.value, datetime.now(UTC), error, job_id),
        )
        return True
    conn.execute(
        "UPDATE jobs SET status = ?, error = ? WHERE id = ?",
        (status.value, error, job_id),
    )
    return True


def get_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return _row_to_job(row)


def recent_jobs(
    conn: sqlite3.Connection,
    limit: int = 25,
    since: timedelta | None = None,
) -> list[Job]:
    """Return recent jobs, optionally filtered to those created within the
    last `since` window. Ordering is newest-first."""
    if since is None:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        cutoff = datetime.now(UTC) - since
        rows = conn.execute(
            "SELECT * FROM jobs WHERE created_at >= ? "
            "ORDER BY created_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def _row_to_job(row: sqlite3.Row) -> Job:
    # model_tier_override is optional — only present after migration 0004
    try:
        tier_override = row["model_tier_override"]
    except (KeyError, IndexError):
        tier_override = None
    # schedule_id is optional — only present after migration 0012 (v0.6.3)
    try:
        sched_id = row["schedule_id"]
    except (KeyError, IndexError):
        sched_id = None
    return Job(
        id=row["id"],
        agent_scope=row["agent_scope"],
        task=row["task"],
        mode=JobMode(row["mode"]),
        status=JobStatus(row["status"]),
        thread_id=row["thread_id"],
        priority=row["priority"],
        owner=row["owner"],
        lease_until=_dt(row["lease_until"]),
        checkpoint_state=json.loads(row["checkpoint_state"]) if row["checkpoint_state"] else None,
        tainted=bool(row["tainted"]),
        cost_usd=float(row["cost_usd"] or 0.0),
        tool_call_count=int(row["tool_call_count"] or 0),
        created_at=_dt(row["created_at"]) or datetime.now(UTC),
        started_at=_dt(row["started_at"]),
        finished_at=_dt(row["finished_at"]),
        error=row["error"],
        model_tier_override=tier_override,
        schedule_id=sched_id,
    )


def _dt(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except ValueError:
        return None
