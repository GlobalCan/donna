"""brief_runs (v0.7.0) — idempotency log for morning brief schedule fires.

Codex 2026-05-02 review on the overnight plan: "Add idempotency now.
Duplicate delivery is the failure users actually notice."

Each row is one (schedule_id, fire_key) attempt to fire a morning
brief. UNIQUE(schedule_id, fire_key) means two simultaneous scheduler
ticks for the same minute can race the INSERT and exactly one wins;
the loser sees IntegrityError and skips. Same effect for retries from
recover_stale, multi-process workers, etc.

`fire_key` is the intended UTC fire datetime truncated to minute, ISO
formatted (e.g. "2026-05-02T12:00:00+00:00"). Truncating to minute
gives us deduplication strong enough for daily/hourly schedules
without risking fire_key collisions across legitimately different
days.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from . import ids


def fire_key_for(when: datetime) -> str:
    """Compute the fire_key for a given UTC datetime.

    Truncated to the minute so two scheduler ticks within the same
    minute (or any other within-minute race) produce the same key
    and thus the same UNIQUE-constraint dedup.
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.replace(second=0, microsecond=0).isoformat()


def claim_brief_run(
    conn: sqlite3.Connection,
    *,
    schedule_id: str,
    fire_key: str,
    job_id: str,
) -> bool:
    """Try to register a brief_run for (schedule_id, fire_key). Return
    True if we won the race (this is the canonical fire) or False if
    another caller already claimed this key.

    Caller must wrap in a transaction. Uses INSERT ... ON CONFLICT DO
    NOTHING so the loser doesn't bubble an IntegrityError up the
    scheduler stack.
    """
    rid = ids.new_id("br")
    cur = conn.execute(
        """
        INSERT INTO brief_runs
            (id, schedule_id, fire_key, job_id, status)
        VALUES (?, ?, ?, ?, 'queued')
        ON CONFLICT(schedule_id, fire_key) DO NOTHING
        """,
        (rid, schedule_id, fire_key, job_id),
    )
    return cur.rowcount > 0


def list_recent_runs(
    conn: sqlite3.Connection, *, limit: int = 25,
) -> list[dict]:
    """Recent brief_runs (newest first). For botctl observability."""
    rows = conn.execute(
        """
        SELECT id, schedule_id, fire_key, job_id, status, created_at
        FROM brief_runs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_status(
    conn: sqlite3.Connection, *, run_id: str, status: str,
) -> None:
    """Update brief_run.status — caller wraps in transaction."""
    conn.execute(
        "UPDATE brief_runs SET status = ? WHERE id = ?", (status, run_id),
    )
