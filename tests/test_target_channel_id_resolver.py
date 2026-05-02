"""V0.6.3: target_channel_id canonical resolver path.

Codex 2026-05-02 review on the overnight plan flagged that
`schedules.target_channel_id` was "semantically half-wired": the column
was set by the modal but the runtime path
(`_resolve_channel_for_job`) reads `threads.channel_id` via
`jobs.thread_id` instead.

V50-2 was live-validated because the modal flow co-set target_channel_id
AND created a thread with the matching channel_id, then propagated
thread_id through the schedule. But:

1. Operator `UPDATE schedules SET target_channel_id = 'C_NEW'` was a
   silent no-op — runtime path ignored the column.
2. Future morning brief work would compound this risk because the
   operator would want to redirect briefs at runtime.

Fix: jobs.schedule_id back-link (migration 0012) +
_resolve_channel_for_job preferring `schedules.target_channel_id` over
threads.channel_id when present.

These tests lock in the resolver priority so morning brief and any
future scheduled-job feature can rely on the contract.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from donna.adapter.slack_adapter import DonnaSlackBot
from donna.jobs.scheduler import Scheduler
from donna.memory import jobs as jobs_mod
from donna.memory import schedules as sched_mod
from donna.memory import threads as threads_mod
from donna.memory.db import connect, transaction
from donna.types import JobMode


def _build_bot_no_socket() -> DonnaSlackBot:
    """Construct DonnaSlackBot bypassing __init__ so we don't open a
    real Socket Mode connection."""
    bot = DonnaSlackBot.__new__(DonnaSlackBot)
    bot._last_sent_per_channel = {}
    bot._rate_limited_until = {}
    bot._alert_throttle = {}
    bot.client = MagicMock()
    return bot


def _make_thread(channel_id: str) -> str:
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id=channel_id,
                thread_external_id=None,
            )
    finally:
        conn.close()
    return tid


def _make_schedule_with_target(
    *,
    target_channel_id: str | None,
    thread_channel_id: str | None,
) -> tuple[str, str | None]:
    """Insert a schedule with both target_channel_id (display canonical)
    and a thread_id pointing to a thread in `thread_channel_id`.

    Returns (schedule_id, thread_id).
    """
    tid = _make_thread(thread_channel_id) if thread_channel_id else None
    conn = connect()
    try:
        with transaction(conn):
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr="* * * * *",
                task="brief task",
                thread_id=tid,
                target_channel_id=target_channel_id,
            )
    finally:
        conn.close()
    return sid, tid


def _fire_schedule(sid: str) -> str:
    """Fire `sid` and return the resulting job_id."""
    sched = None
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (sid,),
        ).fetchall()
        if rows:
            sched = dict(rows[0])
    finally:
        conn.close()
    assert sched is not None, f"schedule {sid} not found"

    import asyncio
    scheduler = Scheduler()
    asyncio.run(scheduler._fire(sched))

    # The most recent job is the fired one.
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM jobs ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no job created by _fire"
    return row["id"]


# ---------- Scenario 1: target_channel_id == thread.channel_id ------------


@pytest.mark.usefixtures("fresh_db")
def test_resolver_returns_target_when_target_matches_thread() -> None:
    """The V50-2 happy path: modal flow co-sets both. Resolver must
    return the target."""
    sid, _ = _make_schedule_with_target(
        target_channel_id="C_TARGET",
        thread_channel_id="C_TARGET",
    )
    jid = _fire_schedule(sid)

    bot = _build_bot_no_socket()
    import asyncio
    chan = asyncio.run(bot._resolve_channel_for_job(jid))

    assert chan == "C_TARGET"


# ---------- Scenario 2: target_channel_id != thread.channel_id (the bug) --


@pytest.mark.usefixtures("fresh_db")
def test_resolver_prefers_target_over_thread_when_diverged() -> None:
    """The half-wired bug Codex flagged. Operator updated
    target_channel_id but thread still points to the old channel.
    Pre-v0.6.3 the resolver returned the thread's stale channel,
    silently ignoring the operator's edit. Post-fix it must return
    target_channel_id."""
    sid, _ = _make_schedule_with_target(
        target_channel_id="C_NEW",
        thread_channel_id="C_OLD",
    )
    jid = _fire_schedule(sid)

    bot = _build_bot_no_socket()
    import asyncio
    chan = asyncio.run(bot._resolve_channel_for_job(jid))

    assert chan == "C_NEW"
    assert chan != "C_OLD"


# ---------- Scenario 3: thread_id only, target NULL -----------------------


@pytest.mark.usefixtures("fresh_db")
def test_resolver_falls_back_to_thread_when_target_is_null() -> None:
    """A schedule created without a target channel (legacy, or operator
    deliberately routed to originating thread) must still deliver via
    the thread path."""
    sid, _ = _make_schedule_with_target(
        target_channel_id=None,
        thread_channel_id="C_ORIGIN",
    )
    jid = _fire_schedule(sid)

    bot = _build_bot_no_socket()
    import asyncio
    chan = asyncio.run(bot._resolve_channel_for_job(jid))

    assert chan == "C_ORIGIN"


# ---------- Scenario 4: interactive job (no schedule_id) ------------------


@pytest.mark.usefixtures("fresh_db")
def test_resolver_uses_thread_channel_for_interactive_jobs() -> None:
    """DM / app_mention jobs have no schedule_id. Resolver must use
    the thread.channel_id path."""
    tid = _make_thread("C_DM")
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="hello", mode=JobMode.CHAT, thread_id=tid,
            )
    finally:
        conn.close()

    bot = _build_bot_no_socket()
    import asyncio
    chan = asyncio.run(bot._resolve_channel_for_job(jid))

    assert chan == "C_DM"


# ---------- Scenario 5: target set, thread_id NULL ------------------------


@pytest.mark.usefixtures("fresh_db")
def test_resolver_returns_target_even_when_thread_id_null() -> None:
    """A schedule with target_channel_id but no thread (CLI-created
    without a known origin) used to return None pre-v0.6.3 because the
    resolver only checked thread_id. Post-fix it must use the target."""
    sid, _ = _make_schedule_with_target(
        target_channel_id="C_HEADLESS",
        thread_channel_id=None,
    )
    jid = _fire_schedule(sid)

    bot = _build_bot_no_socket()
    import asyncio
    chan = asyncio.run(bot._resolve_channel_for_job(jid))

    assert chan == "C_HEADLESS"


# ---------- Scenario 6: scheduler back-link populated --------------------


@pytest.mark.usefixtures("fresh_db")
def test_scheduler_fire_populates_jobs_schedule_id() -> None:
    """v0.6.3: Scheduler._fire must write the schedule_id onto the new
    job row so downstream resolvers can find the originating schedule.
    Pre-fix this column was always NULL even for scheduler-created jobs."""
    sid, _ = _make_schedule_with_target(
        target_channel_id="C_TARGET",
        thread_channel_id="C_TARGET",
    )
    jid = _fire_schedule(sid)

    conn = connect()
    try:
        row = conn.execute(
            "SELECT schedule_id FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["schedule_id"] == sid


# ---------- Scenario 7: no destination at all -----------------------------


@pytest.mark.usefixtures("fresh_db")
def test_resolver_returns_none_when_no_destination() -> None:
    """A job with no thread_id, no schedule_id, no nothing must return
    None (drainer leaves the row in place rather than dropping output
    into a void)."""
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="orphan", mode=JobMode.CHAT,
            )
    finally:
        conn.close()

    bot = _build_bot_no_socket()
    import asyncio
    chan = asyncio.run(bot._resolve_channel_for_job(jid))

    assert chan is None


# ---------- Scenario 8: legacy scheduled job (no schedule_id propagation) -


@pytest.mark.usefixtures("fresh_db")
def test_resolver_falls_back_for_legacy_schedule_job_without_back_link() -> None:
    """Existing scheduled jobs (created before migration 0012) have
    schedule_id=NULL but thread_id is set. Resolver must fall back to
    thread.channel_id so they continue working under the new code."""
    # Simulate a legacy state: schedule + job, but job.schedule_id NULL.
    tid = _make_thread("C_LEGACY")
    conn = connect()
    try:
        with transaction(conn):
            sched_mod.insert_schedule(
                conn, cron_expr="0 8 * * *",
                task="brief task",
                thread_id=tid,
                target_channel_id="C_NEW",  # operator wanted this
            )
            # Insert a job WITHOUT schedule_id, simulating pre-v0.6.3
            jid = jobs_mod.insert_job(
                conn, task="legacy fired job",
                mode=JobMode.CHAT, thread_id=tid,
                # schedule_id intentionally omitted
            )
    finally:
        conn.close()

    bot = _build_bot_no_socket()
    import asyncio
    chan = asyncio.run(bot._resolve_channel_for_job(jid))

    # Without back-link the resolver can't use target_channel_id; it
    # falls back to thread, which still gets delivery to *some* channel
    # (the V50-2-style indirect propagation). This proves the migration
    # is non-breaking for existing rows.
    assert chan == "C_LEGACY"
