"""DB ops for the async_tasks supervised work queue.

Each row represents one unit of fire-and-forget work that needs durable
persistence: tainted-row sanitization backfill, operator-alert DM
delivery, future morning-brief composition, etc. Distinct from `jobs`
(which run a full agent loop with tools/consent/checkpoint) — async
tasks are short-lived single-handler invocations.

State machine:

  pending -> running -> done
                     -> failed (after MAX_ATTEMPTS or non-retryable)
                     -> pending again (if retry scheduled)

Lease semantics mirror `jobs` lite: a runner UPDATEs status='running' +
locked_until=now+lease in one atomic statement; if it dies mid-task,
`recover_stale` finds rows whose locked_until < now and flips them back
to pending.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta


def enqueue(
    conn: sqlite3.Connection,
    *,
    kind: str,
    payload: dict,
    scheduled_for: datetime | None = None,
) -> str:
    """Insert a new pending task. Returns the task id (`at_<hex12>`).

    `scheduled_for` defaults to now (immediately runnable). Pass a future
    datetime to defer.
    """
    task_id = f"at_{uuid.uuid4().hex[:12]}"
    sched = scheduled_for or datetime.now(UTC)
    conn.execute(
        "INSERT INTO async_tasks "
        "(id, kind, payload, scheduled_for) "
        "VALUES (?, ?, ?, ?)",
        (task_id, kind, json.dumps(payload), sched),
    )
    return task_id


def claim_one(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    kinds: Sequence[str],
    lease_seconds: int = 60,
) -> sqlite3.Row | None:
    """Atomically claim one due pending task whose kind is in `kinds`.

    Returns the row (with status flipped to 'running' and locked_*
    populated) or None if nothing is currently due. The atomic UPDATE
    pattern (single statement with subselect) is race-safe under WAL
    against multiple concurrent runners.
    """
    if not kinds:
        return None
    now = datetime.now(UTC)
    until = now + timedelta(seconds=lease_seconds)
    placeholders = ",".join("?" for _ in kinds)
    # Two-step inside one connection is fine here because we COMMIT
    # immediately. Wrapping in BEGIN IMMEDIATE prevents another writer
    # from grabbing the same row.
    cur = conn.execute(
        f"""
        UPDATE async_tasks
           SET status = 'running',
               locked_until = ?,
               locked_by = ?,
               started_at = COALESCE(started_at, ?),
               attempts = attempts + 1
         WHERE id = (
             SELECT id FROM async_tasks
              WHERE status = 'pending'
                AND scheduled_for <= ?
                AND kind IN ({placeholders})
              ORDER BY scheduled_for, created_at
              LIMIT 1
         )
         RETURNING *
        """,
        (until, worker_id, now, now, *kinds),
    )
    row = cur.fetchone()
    return row


def complete(
    conn: sqlite3.Connection, *, task_id: str, worker_id: str,
) -> bool:
    """Mark a running task as done. Owner-guarded — silently no-ops if
    `worker_id` doesn't match `locked_by` (lease was reclaimed by another
    runner)."""
    cur = conn.execute(
        "UPDATE async_tasks "
        "SET status = 'done', "
        "    finished_at = CURRENT_TIMESTAMP, "
        "    locked_until = NULL, "
        "    locked_by = NULL "
        "WHERE id = ? AND locked_by = ?",
        (task_id, worker_id),
    )
    return cur.rowcount > 0


def fail(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    worker_id: str,
    error_msg: str,
    max_attempts: int = 3,
    retry_backoff_s: int = 60,
) -> bool:
    """Record a failed run.

    If `attempts < max_attempts`: re-queue the task with `scheduled_for`
    pushed into the future (linear backoff: `retry_backoff_s * attempts`).
    If at limit: mark status='failed' permanently (operator inspects via
    `botctl async-tasks list`).

    Owner-guarded.
    """
    row = conn.execute(
        "SELECT attempts FROM async_tasks WHERE id = ? AND locked_by = ?",
        (task_id, worker_id),
    ).fetchone()
    if row is None:
        return False
    attempts = int(row["attempts"])
    if attempts >= max_attempts:
        cur = conn.execute(
            "UPDATE async_tasks "
            "SET status = 'failed', "
            "    last_error = ?, "
            "    finished_at = CURRENT_TIMESTAMP, "
            "    locked_until = NULL, "
            "    locked_by = NULL "
            "WHERE id = ? AND locked_by = ?",
            (error_msg[:1000], task_id, worker_id),
        )
        return cur.rowcount > 0
    next_sched = datetime.now(UTC) + timedelta(
        seconds=retry_backoff_s * attempts,
    )
    cur = conn.execute(
        "UPDATE async_tasks "
        "SET status = 'pending', "
        "    last_error = ?, "
        "    scheduled_for = ?, "
        "    locked_until = NULL, "
        "    locked_by = NULL "
        "WHERE id = ? AND locked_by = ?",
        (error_msg[:1000], next_sched, task_id, worker_id),
    )
    return cur.rowcount > 0


def recover_stale(conn: sqlite3.Connection, *, worker_id: str) -> int:
    """Re-queue tasks whose lease expired (runner died mid-task).

    Returns the count of recovered tasks. Should be called periodically
    by every runner before claim_one — eventual consistency is acceptable
    because the runner will eventually pick them up.
    """
    now = datetime.now(UTC)
    cur = conn.execute(
        "UPDATE async_tasks "
        "SET status = 'pending', "
        "    locked_until = NULL, "
        "    locked_by = NULL, "
        "    last_error = COALESCE(last_error, '') || "
        "                 char(10) || 'lease expired; recovered by ' || ? "
        "WHERE status = 'running' "
        "  AND locked_until IS NOT NULL "
        "  AND locked_until < ?",
        (worker_id, now),
    )
    return cur.rowcount


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> Sequence[sqlite3.Row]:
    """Inspection helper for botctl. Newest first."""
    where = []
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    sql = "SELECT * FROM async_tasks"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    """Quick health snapshot — how many tasks in each state."""
    rows = conn.execute(
        "SELECT status, COUNT(*) AS c FROM async_tasks GROUP BY status"
    ).fetchall()
    return {r["status"]: int(r["c"]) for r in rows}
