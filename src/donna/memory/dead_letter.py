"""Helpers for the outbox_dead_letter table.

V50-1: when the Slack outbox drainer hits a terminal or unknown error,
the offending row is captured here for operator review. Surfaces via
`botctl dead-letter list`.

Provenance is preserved (source_table + source_id) so a future
`botctl dead-letter requeue <id>` could re-enqueue if the underlying issue
is fixable (e.g. operator re-invites Donna to the channel).
"""
from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime


def record_dead_letter(
    conn: sqlite3.Connection,
    *,
    source_table: str,
    source_id: str,
    job_id: str | None,
    channel_id: str | None,
    thread_ts: str | None,
    payload: str | None,
    tainted: bool,
    error_code: str,
    error_class: str,
    attempt_count: int,
    first_attempt_at: datetime | None,
) -> str:
    """Insert one dead-letter row. Returns the new dl_<hex12> id.

    Caller is responsible for deleting the source row in the same
    transaction.
    """
    dl_id = f"dl_{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)
    conn.execute(
        """
        INSERT INTO outbox_dead_letter
          (id, source_table, source_id, job_id, channel_id, thread_ts,
           payload, tainted, error_code, error_class,
           attempt_count, first_attempt_at, last_attempt_at, moved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dl_id, source_table, source_id, job_id, channel_id, thread_ts,
            payload, 1 if tainted else 0, error_code, error_class,
            attempt_count, first_attempt_at, now, now,
        ),
    )
    return dl_id


def list_dead_letter(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    since: datetime | None = None,
) -> Sequence[sqlite3.Row]:
    """Return dead-letter rows, newest first."""
    if since is None:
        return conn.execute(
            "SELECT * FROM outbox_dead_letter "
            "ORDER BY moved_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM outbox_dead_letter WHERE moved_at >= ? "
        "ORDER BY moved_at DESC LIMIT ?",
        (since, limit),
    ).fetchall()


def count_dead_letter(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM outbox_dead_letter"
    ).fetchone()
    return int(row["c"]) if row else 0
