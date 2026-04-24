"""Scheduler: bad-cron auto-disable + happy-path fire.

Two scenarios this guards against:

1. **Happy path** — a valid cron-expression schedule becomes due, fires a
   job, updates next_run_at, and gets picked up by the worker.

2. **Corrupted cron_expr** — some row in `schedules` has a cron that
   croniter can't parse (data corruption, manual SQL, migration gone
   wrong). Without the guard added in this commit, every scheduler tick
   (60s) would re-select the row, call `mark_ran` inside a transaction,
   hit croniter's parse error, roll back, and log an exception. Forever.
   With the guard: the schedule is auto-disabled on the first failed
   tick with a distinct `scheduler.disabling_bad_cron` log event.

Insertion-time validation (`_validate_cron` in `memory/schedules.py`)
protects the happy path already; this test doesn't duplicate that.
"""
from __future__ import annotations

import pytest

from donna.jobs.scheduler import Scheduler
from donna.memory.db import connect, transaction


def _insert_schedule_bypass_validation(
    *, sid: str, cron_expr: str, task: str = "t",
    next_run_at: str = "2020-01-01 00:00:00",
) -> None:
    """Directly insert a schedule row without going through
    `insert_schedule` — simulates data-corruption / manual-SQL path."""
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO schedules "
                "(id, agent_scope, cron_expr, task, mode, next_run_at, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (sid, "orchestrator", cron_expr, task, "chat", next_run_at),
            )
    finally:
        conn.close()


def _get_schedule(sid: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, enabled, next_run_at FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_bad_cron_expr_auto_disables_on_first_tick() -> None:
    """This is the regression guard: without the fix, the scheduler would
    retry this row every 60s forever. With the fix, it's disabled after
    one failed attempt and never selected again."""
    _insert_schedule_bypass_validation(sid="sch_broken", cron_expr="not a cron")

    await Scheduler()._fire({
        "id": "sch_broken",
        "cron_expr": "not a cron",
        "task": "t",
        "agent_scope": "orchestrator",
        "mode": "chat",
    })

    row = _get_schedule("sch_broken")
    assert row is not None
    assert row["enabled"] == 0, "bad cron row must be auto-disabled"

    # And it's no longer in the due set
    from donna.memory import schedules as sched_mod
    conn = connect()
    try:
        due = sched_mod.due_schedules(conn)
    finally:
        conn.close()
    assert not any(s["id"] == "sch_broken" for s in due)


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_empty_cron_expr_auto_disables() -> None:
    _insert_schedule_bypass_validation(sid="sch_empty", cron_expr="")
    await Scheduler()._fire({
        "id": "sch_empty", "cron_expr": "", "task": "t",
        "agent_scope": "orchestrator", "mode": "chat",
    })
    assert _get_schedule("sch_empty")["enabled"] == 0


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_whitespace_cron_expr_auto_disables() -> None:
    _insert_schedule_bypass_validation(sid="sch_ws", cron_expr="   ")
    await Scheduler()._fire({
        "id": "sch_ws", "cron_expr": "   ", "task": "t",
        "agent_scope": "orchestrator", "mode": "chat",
    })
    assert _get_schedule("sch_ws")["enabled"] == 0


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_valid_cron_fires_job_and_advances_next_run() -> None:
    """Happy path: valid cron → job created, next_run_at advances, schedule
    stays enabled."""
    from donna.memory import schedules as sched_mod
    conn = connect()
    try:
        with transaction(conn):
            sid = sched_mod.insert_schedule(
                conn, cron_expr="* * * * *", task="every minute",
            )
            # Force the schedule to be "due" by backdating next_run_at
            conn.execute(
                "UPDATE schedules SET next_run_at = '2020-01-01 00:00:00' WHERE id = ?",
                (sid,),
            )
        sched = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()

    await Scheduler()._fire(dict(sched))

    conn = connect()
    try:
        row = conn.execute(
            "SELECT enabled, next_run_at FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
        job_rows = conn.execute(
            "SELECT id, task FROM jobs WHERE task = ?", ("every minute",),
        ).fetchall()
    finally:
        conn.close()
    assert row["enabled"] == 1
    # next_run_at advanced beyond the backdated value
    assert str(row["next_run_at"]) > "2020-01-01 00:00:00"
    assert len(job_rows) == 1


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_invalid_minute_value_auto_disables() -> None:
    """Cron syntax edge: minute 60 is invalid (0-59). croniter rejects it
    at `is_valid` time — the guard catches before attempting the tx."""
    _insert_schedule_bypass_validation(
        sid="sch_bad_minute", cron_expr="60 * * * *",
    )
    await Scheduler()._fire({
        "id": "sch_bad_minute", "cron_expr": "60 * * * *", "task": "t",
        "agent_scope": "orchestrator", "mode": "chat",
    })
    assert _get_schedule("sch_bad_minute")["enabled"] == 0


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_insert_schedule_still_rejects_bad_cron_at_write_time() -> None:
    """The primary defense — insert_schedule's validator — remains the
    first line of protection. Duplicate coverage with the memory-layer
    test, but pinning it here so anyone reading the scheduler tests sees
    the full picture: validation at write + guard at read."""
    from donna.memory import schedules as sched_mod

    conn = connect()
    try:
        with pytest.raises(ValueError, match="Invalid cron expression"), transaction(conn):
            sched_mod.insert_schedule(
                conn, cron_expr="not a cron", task="t",
            )
    finally:
        conn.close()
