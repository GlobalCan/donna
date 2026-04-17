"""Tool-call log rows."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import ids


def insert_tool_call(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    tool_name: str,
    arguments: dict,
    result: dict | str | None,
    duration_ms: int,
    cost_usd: float = 0.0,
    idempotent: bool = True,
    tainted: bool = False,
    status: str = "done",
    error: str | None = None,
    result_artifact_id: str | None = None,
) -> str:
    tcid = ids.tool_call_id()
    now = datetime.now(timezone.utc)
    conn.execute(
        """
        INSERT INTO tool_calls
            (id, job_id, tool_name, arguments, result, result_artifact_id,
             started_at, finished_at, duration_ms, cost_usd,
             idempotent, tainted, status, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tcid, job_id, tool_name,
            json.dumps(arguments, default=str),
            json.dumps(result, default=str) if result is not None else None,
            result_artifact_id,
            now, now, duration_ms, cost_usd,
            1 if idempotent else 0,
            1 if tainted else 0,
            status, error,
        ),
    )
    return tcid


def tool_calls_for(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM tool_calls WHERE job_id = ? ORDER BY started_at",
        (job_id,),
    ).fetchall()
    return [dict(r) for r in rows]
