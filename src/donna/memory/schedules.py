"""Cron schedules — v1's only proactive trigger.

v0.5.0 adds `target_channel_id` so scheduled tasks can post to a
specific channel (e.g. `#morning-brief`) instead of cluttering the
operator's DM. Set via the `/schedule` modal's channel-select input.
When NULL, replies go to the originating thread (the channel from
which `/schedule` was invoked).

`target_thread_ts` is reserved for replying inside an existing thread;
not yet wired through `/schedule` UX.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from croniter import croniter

from . import ids


def insert_schedule(
    conn: sqlite3.Connection,
    *,
    cron_expr: str,
    task: str,
    agent_scope: str = "orchestrator",
    mode: str = "chat",
    thread_id: str | None = None,
    target_channel_id: str | None = None,
    target_thread_ts: str | None = None,
) -> str:
    """Insert a schedule row.

    `thread_id` records the originating Discord thread (legacy v0.4.3
    fix). `target_channel_id` overrides delivery to a specific channel
    when present; otherwise replies use the originating thread's
    channel.
    """
    _validate_cron(cron_expr)
    sid = ids.schedule_id()
    next_run = croniter(cron_expr, datetime.now(UTC)).get_next(datetime)
    conn.execute(
        """
        INSERT INTO schedules
            (id, agent_scope, cron_expr, task, mode, next_run_at,
             thread_id, target_channel_id, target_thread_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sid, agent_scope, cron_expr, task, mode, next_run,
            thread_id, target_channel_id, target_thread_ts,
        ),
    )
    return sid


def list_schedules(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM schedules WHERE enabled = 1 ORDER BY next_run_at"
    ).fetchall()
    return [dict(r) for r in rows]


def due_schedules(conn: sqlite3.Connection) -> list[dict]:
    now = datetime.now(UTC)
    rows = conn.execute(
        "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at <= ?",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_ran(conn: sqlite3.Connection, *, schedule_id: str, cron_expr: str) -> None:
    now = datetime.now(UTC)
    next_run = croniter(cron_expr, now).get_next(datetime)
    conn.execute(
        "UPDATE schedules SET last_run_at = ?, next_run_at = ? WHERE id = ?",
        (now, next_run, schedule_id),
    )


def disable_schedule(conn: sqlite3.Connection, schedule_id: str) -> None:
    conn.execute("UPDATE schedules SET enabled = 0 WHERE id = ?", (schedule_id,))


def _validate_cron(expr: str) -> None:
    if not croniter.is_valid(expr):
        raise ValueError(f"Invalid cron expression: {expr}")
