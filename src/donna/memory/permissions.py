"""Permission grants — approvals with expiry scoped to job or global."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import ids


def has_grant(conn: sqlite3.Connection, *, job_id: str, tool_name: str) -> bool:
    now = datetime.now(timezone.utc)
    row = conn.execute(
        """
        SELECT 1 FROM permission_grants
        WHERE tool_name = ?
          AND (job_id = ? OR scope = 'global')
          AND (expires_at IS NULL OR expires_at > ?)
        LIMIT 1
        """,
        (tool_name, job_id, now),
    ).fetchone()
    return row is not None


def insert_grant(
    conn: sqlite3.Connection,
    *,
    job_id: str | None,
    tool_name: str,
    scope: str = "job",
    expires_at: datetime | None = None,
) -> str:
    gid = ids.grant_id()
    conn.execute(
        """
        INSERT INTO permission_grants (id, job_id, tool_name, scope, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (gid, job_id, tool_name, scope, expires_at),
    )
    return gid
