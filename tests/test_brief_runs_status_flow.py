"""V70-1 (v0.7.3): brief_runs.status mirrors job state transitions.

Codex 2026-04-30 review on the v0.7 morning-brief slice flagged that
`brief_runs.status` was always 'queued' regardless of what the
underlying chat job did — making `botctl brief-runs list` lie to
operators. This module locks down the four mirror points:

- claim_next_queued (queued → running) — set in jobs/runner.py
- JobContext.finalize DONE                  — set in agent/context.py
- runner exception path FAILED              — set in jobs/runner.py
- /donna_cancel CANCELLED                   — set in adapter/slack_ux.py
- /donna_cancel sch_X (schedule disable)    — set in adapter/slack_ux.py

And the negative case: a regular non-brief chat job's finalize/claim/
fail/cancel must NOT touch brief_runs (UPDATE matches 0 rows, no error).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from donna.adapter import slack_ux as slack_ux_mod
from donna.agent.context import JobContext
from donna.jobs import morning_brief as brief_mod
from donna.jobs.runner import Worker
from donna.memory import brief_runs as br_mod
from donna.memory import jobs as jobs_mod
from donna.memory import schedules as sched_mod
from donna.memory import threads as threads_mod
from donna.memory.db import connect, transaction
from donna.types import JobMode, JobStatus

# ---------- helpers --------------------------------------------------------


def _make_morning_brief_schedule(
    *,
    target_channel_id: str = "C_BRIEF",
    cron: str = "0 12 * * *",
    topics: list[str] | None = None,
) -> str:
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn,
                channel_id=target_channel_id,
                thread_external_id=None,
            )
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr=cron,
                task="brief auto-generated",
                mode="chat",
                thread_id=tid,
                target_channel_id=target_channel_id,
                kind="morning_brief",
                payload={
                    "topics": topics if topics is not None else ["alpha"],
                    "tz": "America/New_York",
                },
            )
    finally:
        conn.close()
    return sid


def _load_schedule(sid: str) -> dict:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row)


def _fire_brief_returning_job_id(sid: str) -> str:
    """Convenience: fire a morning brief and return the new job_id."""
    sched = _load_schedule(sid)
    fire_at = datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC)
    jid = brief_mod.fire_morning_brief(sched=sched, fire_at=fire_at)
    assert jid is not None, "fire_morning_brief should produce a job"
    return jid


def _brief_run_status_for_job(job_id: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT status FROM brief_runs WHERE job_id = ?", (job_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["status"] if row else None


def _seed_running_job(task: str, worker_id: str) -> str:
    """Insert a queued chat job and force-claim it for the given worker."""
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn,
                task=task,
                agent_scope="orchestrator",
                mode=JobMode.CHAT,
            )
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                (worker_id, jid),
            )
    finally:
        conn.close()
    return jid


# ---------- finalize → DONE ------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_finalize_marks_brief_run_done() -> None:
    """JobContext.finalize on a brief job flips brief_runs.status='done'.
    The flip happens inside the same transaction as the DONE write so a
    finalize rollback also rolls back the brief_runs flip (Codex
    pitfall: don't let services open their own transaction during
    finalize)."""
    sid = _make_morning_brief_schedule()
    jid = _fire_brief_returning_job_id(sid)
    # brief is in 'queued' state immediately post-fire
    assert _brief_run_status_for_job(jid) == "queued"

    # Force-claim the job for our worker (so the owner-guarded
    # set_status inside finalize succeeds).
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                ("test-worker", jid),
            )
    finally:
        conn.close()

    async with JobContext.open(jid, worker_id="test-worker") as ctx:
        assert ctx is not None
        ctx.state.final_text = "morning brief content"
        ctx.state.done = True

    assert _brief_run_status_for_job(jid) == "done"

    # Sanity: the job itself is also DONE.
    conn = connect()
    try:
        row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == JobStatus.DONE.value


# ---------- worker.claim → RUNNING ------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_runner_marks_brief_run_running_on_claim() -> None:
    """Worker._tick claims a queued brief job and the matching
    brief_runs row flips from 'queued' to 'running' in the same
    transaction as the job claim."""
    sid = _make_morning_brief_schedule()
    jid = _fire_brief_returning_job_id(sid)
    assert _brief_run_status_for_job(jid) == "queued"

    worker = Worker()
    # Stub `_run_one` so we don't actually drive the agent loop —
    # we only care that the claim path mirrored onto brief_runs.
    worker._run_one = lambda job_id: asyncio.sleep(0)  # type: ignore[assignment]

    await worker._tick()

    assert _brief_run_status_for_job(jid) == "running"


# ---------- worker exception → FAILED ---------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_failed_job_marks_brief_run_failed() -> None:
    """If the agent loop raises mid-job, runner._run_one's except
    clause flips the job to FAILED and the brief_runs row mirrors to
    'failed' inside the same owner-guarded transaction."""
    sid = _make_morning_brief_schedule()
    jid = _fire_brief_returning_job_id(sid)

    # Pre-claim the job for our worker so the owner-guarded
    # set_status(FAILED) succeeds.
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                ("worker-x", jid),
            )
    finally:
        conn.close()

    worker = Worker()
    worker.worker_id = "worker-x"

    async def _boom(*args, **kwargs) -> None:
        raise RuntimeError("simulated brief failure")

    with patch("donna.jobs.runner.run_job", side_effect=_boom):
        await worker._run_one(jid)

    assert _brief_run_status_for_job(jid) == "failed"

    conn = connect()
    try:
        row = conn.execute(
            "SELECT status, error FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == JobStatus.FAILED.value
    assert "simulated brief failure" in (row["error"] or "")


# ---------- /donna_cancel paths -> FAILED -----------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_cancel_job_marks_brief_run_failed() -> None:
    """`/donna_cancel job_Y` (cancelling the brief's running job)
    flips brief_runs.status='failed' for the matching run."""
    sid = _make_morning_brief_schedule()
    jid = _fire_brief_returning_job_id(sid)
    assert _brief_run_status_for_job(jid) == "queued"

    msg = slack_ux_mod._route_cancel_or_disable(jid)
    assert "cancelled" in msg.lower()

    assert _brief_run_status_for_job(jid) == "failed"

    conn = connect()
    try:
        row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == JobStatus.CANCELLED.value


@pytest.mark.usefixtures("fresh_db")
def test_cancel_schedule_marks_active_brief_runs_failed() -> None:
    """`/donna_cancel sch_X` (smart-routes to disable) flips any
    queued/running brief_runs for that schedule to 'failed'.
    A finished (status='done') run from the past is left alone."""
    sid = _make_morning_brief_schedule()
    # Fresh fire: brief_run is 'queued'
    jid = _fire_brief_returning_job_id(sid)
    assert _brief_run_status_for_job(jid) == "queued"

    # Plant a historical 'done' run in the same schedule so we can
    # verify we ONLY touch active rows.
    conn = connect()
    try:
        with transaction(conn):
            old_jid = jobs_mod.insert_job(
                conn, task="historical brief", mode=JobMode.CHAT,
                schedule_id=sid,
            )
            br_mod.claim_brief_run(
                conn,
                schedule_id=sid,
                fire_key="2026-05-01T12:00:00+00:00",
                job_id=old_jid,
            )
            br_mod.update_status_by_job_id(
                conn, job_id=old_jid, status="done",
            )
    finally:
        conn.close()
    assert _brief_run_status_for_job(old_jid) == "done"

    msg = slack_ux_mod._route_cancel_or_disable(sid)
    assert "disabled" in msg.lower()

    # Active run flipped to failed.
    assert _brief_run_status_for_job(jid) == "failed"
    # Historical 'done' run untouched.
    assert _brief_run_status_for_job(old_jid) == "done"

    # Sanity: schedule is disabled now.
    conn = connect()
    try:
        row = conn.execute(
            "SELECT enabled FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()
    assert not row["enabled"]


@pytest.mark.usefixtures("fresh_db")
def test_cancel_legacy_task_schedule_does_not_fan_out_to_brief_runs() -> None:
    """Disabling a kind='task' schedule must not error out trying to
    update brief_runs (there shouldn't be any rows for it; just
    skip the fan-out entirely)."""
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_LEGACY",
                thread_external_id=None,
            )
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr="0 12 * * *",
                task="legacy task",
                mode="chat",
                thread_id=tid,
                target_channel_id="C_LEGACY",
                # kind defaults to 'task'
            )
    finally:
        conn.close()

    msg = slack_ux_mod._route_cancel_or_disable(sid)
    assert "disabled" in msg.lower()


# ---------- non-brief jobs untouched ----------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_non_brief_finalize_does_not_touch_brief_runs() -> None:
    """A regular interactive chat job (no schedule_id, no brief_runs
    row) finalizes cleanly. The brief_runs UPDATE is the SQL-level
    is-this-a-brief filter — 0 rows matched, no error.

    We verify by seeding an unrelated brief_runs row and confirming
    its status stays untouched after finalizing the chat job.
    """
    chat_jid = _seed_running_job("interactive chat", "worker-z")

    # Plant an unrelated brief_runs row (different job entirely).
    other_sid = _make_morning_brief_schedule(target_channel_id="C_OTHER")
    other_jid = _fire_brief_returning_job_id(other_sid)
    assert _brief_run_status_for_job(other_jid) == "queued"

    async with JobContext.open(chat_jid, worker_id="worker-z") as ctx:
        assert ctx is not None
        ctx.state.final_text = "chat reply"
        ctx.state.done = True

    # Chat job has no brief_runs row.
    assert _brief_run_status_for_job(chat_jid) is None
    # Unrelated brief_run still 'queued' (not collateral-damaged).
    assert _brief_run_status_for_job(other_jid) == "queued"


@pytest.mark.usefixtures("fresh_db")
def test_non_brief_cancel_does_not_touch_brief_runs() -> None:
    """`/donna_cancel job_Y` on a regular (non-brief) job must not
    error and must not touch any brief_runs row."""
    chat_jid = _seed_running_job("interactive chat", "worker-z")

    other_sid = _make_morning_brief_schedule(target_channel_id="C_OTHER")
    other_jid = _fire_brief_returning_job_id(other_sid)
    assert _brief_run_status_for_job(other_jid) == "queued"

    msg = slack_ux_mod._route_cancel_or_disable(chat_jid)
    assert "cancelled" in msg.lower()

    assert _brief_run_status_for_job(chat_jid) is None
    assert _brief_run_status_for_job(other_jid) == "queued"


# ---------- helper-level contract ------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_update_status_by_job_id_returns_zero_when_no_row() -> None:
    """No-op contract: updating a job_id that has no brief_runs row
    returns rowcount=0 and does not error."""
    conn = connect()
    try:
        with transaction(conn):
            n = br_mod.update_status_by_job_id(
                conn, job_id="job_does_not_exist", status="done",
            )
    finally:
        conn.close()
    assert n == 0


@pytest.mark.usefixtures("fresh_db")
def test_update_status_by_job_id_flips_matching_row() -> None:
    """Sanity: the SQL helper actually mutates the matching row."""
    sid = _make_morning_brief_schedule()
    jid = _fire_brief_returning_job_id(sid)
    assert _brief_run_status_for_job(jid) == "queued"

    conn = connect()
    try:
        with transaction(conn):
            n = br_mod.update_status_by_job_id(
                conn, job_id=jid, status="running",
            )
    finally:
        conn.close()
    assert n == 1
    assert _brief_run_status_for_job(jid) == "running"
