"""V0.6 #5: retention policy + auto-purge.

Codex's 2026-05-01 review: "Traces, dead letters, tool calls, raw tainted
content, and artifacts will grow forever."

Policy as code (not config). Per-table age cutoffs in days. Tables that
hold operator-content (artifacts, knowledge_*, messages, cost_ledger)
are NOT auto-purged — those need explicit operator commands. Auto-purge
covers operational state with an audit horizon:

| Table                | Days  | Why |
|---|---|---|
| traces               | 30    | Span audit; tail rarely needed past 30d |
| outbox_dead_letter   | 90    | Operator review window |
| tool_calls           | 90    | Per-job audit (pairs with traces) |
| async_tasks (terminal) | 30  | done/failed rows only; pending stays |
| jobs (terminal)      | 90    | done/failed/cancelled only |

Order honors FK direction: tool_calls (child) deleted before jobs
(parent). FOREIGN KEYS pragma is on, so reverse order would fail.

`purge_old(conn, dry_run=False)` returns counts per table.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

# Policy table — edit here, not in caller.
RETENTION_DAYS: dict[str, int] = {
    "traces": 30,
    "outbox_dead_letter": 90,
    "tool_calls": 90,
    "async_tasks_terminal": 30,
    "jobs_terminal": 90,
}


def _cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


def purge_old(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, int]:
    """Purge rows older than the retention horizon for each table.

    `dry_run=True` returns the counts that WOULD be purged without
    actually deleting. Useful for `botctl retention status`.
    """
    now = now or datetime.now(UTC)
    counts: dict[str, int] = {}

    # 1. tool_calls — must come BEFORE jobs to honor FK direction.
    #    Only delete rows whose parent job is finished + old.
    cutoff = _cutoff(now, RETENTION_DAYS["tool_calls"])
    counts["tool_calls"] = _purge_or_count(
        conn,
        select_sql=(
            "SELECT COUNT(*) FROM tool_calls "
            "WHERE job_id IN ("
            "  SELECT id FROM jobs WHERE finished_at < ? "
            "    AND status IN ('done', 'failed', 'cancelled')"
            ")"
        ),
        delete_sql=(
            "DELETE FROM tool_calls "
            "WHERE job_id IN ("
            "  SELECT id FROM jobs WHERE finished_at < ? "
            "    AND status IN ('done', 'failed', 'cancelled')"
            ")"
        ),
        params=(cutoff,),
        dry_run=dry_run,
    )

    # 2. traces — independent.
    cutoff = _cutoff(now, RETENTION_DAYS["traces"])
    counts["traces"] = _purge_or_count(
        conn,
        select_sql="SELECT COUNT(*) FROM traces WHERE started_at < ?",
        delete_sql="DELETE FROM traces WHERE started_at < ?",
        params=(cutoff,),
        dry_run=dry_run,
    )

    # 3. outbox_dead_letter — independent.
    cutoff = _cutoff(now, RETENTION_DAYS["outbox_dead_letter"])
    counts["outbox_dead_letter"] = _purge_or_count(
        conn,
        select_sql="SELECT COUNT(*) FROM outbox_dead_letter WHERE moved_at < ?",
        delete_sql="DELETE FROM outbox_dead_letter WHERE moved_at < ?",
        params=(cutoff,),
        dry_run=dry_run,
    )

    # 4. async_tasks — terminal rows only (status in done/failed).
    #    Pending tasks must NEVER be purged; they're the work queue.
    cutoff = _cutoff(now, RETENTION_DAYS["async_tasks_terminal"])
    counts["async_tasks"] = _purge_or_count(
        conn,
        select_sql=(
            "SELECT COUNT(*) FROM async_tasks "
            "WHERE finished_at < ? AND status IN ('done', 'failed')"
        ),
        delete_sql=(
            "DELETE FROM async_tasks "
            "WHERE finished_at < ? AND status IN ('done', 'failed')"
        ),
        params=(cutoff,),
        dry_run=dry_run,
    )

    # 5. jobs — terminal rows only. Their tool_calls have already been
    #    purged in step 1 (or earlier passes), so the FK constraint is
    #    satisfied.
    cutoff = _cutoff(now, RETENTION_DAYS["jobs_terminal"])
    counts["jobs"] = _purge_or_count(
        conn,
        select_sql=(
            "SELECT COUNT(*) FROM jobs "
            "WHERE finished_at < ? "
            "  AND status IN ('done', 'failed', 'cancelled')"
        ),
        delete_sql=(
            "DELETE FROM jobs "
            "WHERE finished_at < ? "
            "  AND status IN ('done', 'failed', 'cancelled')"
        ),
        params=(cutoff,),
        dry_run=dry_run,
    )

    return counts


def _purge_or_count(
    conn: sqlite3.Connection,
    *,
    select_sql: str,
    delete_sql: str,
    params: tuple,
    dry_run: bool,
) -> int:
    """Either count matching rows (dry_run=True) or delete them.

    Same WHERE clause for both paths so the dry-run is honest about
    what the actual delete would do.
    """
    if dry_run:
        row = conn.execute(select_sql, params).fetchone()
        return int(row[0]) if row else 0
    cur = conn.execute(delete_sql, params)
    return cur.rowcount


def status(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return per-table totals + would-purge counts. Powers `botctl
    retention status`."""
    out: dict[str, dict] = {}
    for table in (
        "traces", "outbox_dead_letter", "tool_calls",
        "async_tasks", "jobs",
    ):
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            # Table missing (older schema). Skip.
            continue
        out[table] = {"total": int(total)}
    would_purge = purge_old(conn, dry_run=True)
    for table, n in would_purge.items():
        if table in out:
            out[table]["would_purge"] = int(n)
        else:
            out[table] = {"total": 0, "would_purge": int(n)}
    return out
