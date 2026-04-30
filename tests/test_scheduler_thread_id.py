"""Scheduler must propagate `thread_id` from schedule → job so replies
can deliver back to Discord.

Bug surfaced 2026-04-30 during the first live smoke test of the
scheduler in production. The scheduler ticked correctly, the worker ran
the jobs to status=done, but no Discord message ever arrived because:

1. `schedules` table had no `thread_id` column to remember the
   originating Discord channel.
2. `Scheduler._fire` therefore called `insert_job` without thread_id.
3. `_resolve_channel_for_job` in the adapter returned None for jobs
   with thread_id=NULL.
4. `_post_update` returned False; outbox row sat undeliverable forever.

Migration 0006 added the column. `/schedule` (Discord) now captures the
current channel via `get_or_create_thread`. `Scheduler._fire` propagates
to the new job. These tests pin the data-layer pieces; the UI capture
in discord_ux is exercised manually via the live smoke runbook.
"""
from __future__ import annotations

import pytest

from donna.jobs.scheduler import Scheduler
from donna.memory import schedules as sched_mod
from donna.memory import threads as threads_mod
from donna.memory.db import connect, transaction


@pytest.mark.usefixtures("fresh_db")
def test_insert_schedule_persists_thread_id() -> None:
    """`/schedule`'s data-layer call must store the thread_id so it
    survives the worker's later `_fire` lookup."""
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, discord_channel="123456789", discord_thread=None,
            )
            sid = sched_mod.insert_schedule(
                conn, cron_expr="* * * * *", task="every minute",
                thread_id=tid,
            )
        row = conn.execute(
            "SELECT thread_id FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()
    assert row["thread_id"] == tid


@pytest.mark.usefixtures("fresh_db")
def test_insert_schedule_default_thread_id_is_null() -> None:
    """Backwards-compatibility: existing call sites that don't pass
    thread_id (e.g. `botctl schedule add` without `--discord-channel`)
    must still succeed and produce a row with NULL thread_id.
    """
    conn = connect()
    try:
        with transaction(conn):
            sid = sched_mod.insert_schedule(
                conn, cron_expr="* * * * *", task="t",
            )
        row = conn.execute(
            "SELECT thread_id FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()
    assert row["thread_id"] is None


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_fire_propagates_thread_id_to_job() -> None:
    """The core regression: when scheduler fires a schedule that has a
    thread_id, the resulting job MUST also have that thread_id — that's
    what enables the adapter's `_resolve_channel_for_job` to find a
    delivery target."""
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, discord_channel="987654321", discord_thread=None,
            )
            sid = sched_mod.insert_schedule(
                conn, cron_expr="* * * * *", task="reply SCHED_OK",
                thread_id=tid,
            )
            # Backdate next_run_at so the schedule appears due
            conn.execute(
                "UPDATE schedules SET next_run_at = '2020-01-01 00:00:00' "
                "WHERE id = ?",
                (sid,),
            )
        sched_row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()

    await Scheduler()._fire(dict(sched_row))

    conn = connect()
    try:
        job_row = conn.execute(
            "SELECT id, thread_id, task FROM jobs WHERE task = ?",
            ("reply SCHED_OK",),
        ).fetchone()
    finally:
        conn.close()
    assert job_row is not None, "expected scheduler to insert a job"
    assert job_row["thread_id"] == tid, (
        "scheduler must propagate thread_id from schedule to job; without "
        "this the adapter cannot resolve a Discord channel and the reply "
        "is never delivered"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_fire_with_null_thread_id_still_creates_job() -> None:
    """CLI-created schedules without --discord-channel have thread_id=NULL.
    The scheduler must still fire them (they're useful for local-only
    automation, e.g. data sweeps); they just won't deliver to Discord.
    The job should be visible via `botctl jobs`.
    """
    conn = connect()
    try:
        with transaction(conn):
            sid = sched_mod.insert_schedule(
                conn, cron_expr="* * * * *", task="cli-only task",
            )
            conn.execute(
                "UPDATE schedules SET next_run_at = '2020-01-01 00:00:00' "
                "WHERE id = ?",
                (sid,),
            )
        sched_row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()

    await Scheduler()._fire(dict(sched_row))

    conn = connect()
    try:
        job_row = conn.execute(
            "SELECT id, thread_id FROM jobs WHERE task = ?",
            ("cli-only task",),
        ).fetchone()
    finally:
        conn.close()
    assert job_row is not None
    assert job_row["thread_id"] is None
