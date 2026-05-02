"""V60-5 (v0.6.2): Slack-callable schedule disable + smart `/donna_cancel`
routing.

Pre-fix `/donna_cancel sch_...` silently succeeded because
`jobs_mod.set_status` is called against the `jobs` table — schedule IDs
miss every row but the function returns True regardless of rowcount when
worker_id is None. Operator hit this 2026-05-02 trying to stop a
`* * * * *` test schedule that had already fired ~30 SCHED_OK messages
into #donna-test before the operator escalated.

These tests exercise the helpers behind the `/donna_cancel` and
`/donna_schedule_disable` slash commands.
"""
from __future__ import annotations

import pytest

from donna.adapter.slack_ux import (
    _cancel_job_by_id,
    _disable_schedule_by_id,
    _route_cancel_or_disable,
)
from donna.memory import jobs as jobs_mod
from donna.memory import schedules as sched_mod
from donna.memory.db import connect, transaction
from donna.types import JobMode, JobStatus


def _make_schedule(*, cron: str = "* * * * *", task: str = "ping") -> str:
    conn = connect()
    try:
        with transaction(conn):
            sid = sched_mod.insert_schedule(
                conn, cron_expr=cron, task=task,
                target_channel_id="C_test",
            )
    finally:
        conn.close()
    return sid


def _make_job(*, task: str = "respond ok") -> str:
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task=task, mode=JobMode.CHAT,
            )
    finally:
        conn.close()
    return jid


def _is_schedule_enabled(sid: str) -> bool:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT enabled FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()
    return bool(row and row["enabled"])


def _job_status(jid: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    return row["status"] if row else None


# ---------- smart-route: schedule path -------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_route_disables_schedule_when_id_starts_with_sch_prefix() -> None:
    """The bug behind V60-5: pre-fix this would pass the sch_ ID to
    jobs_mod.set_status which would no-op silently. Post-fix the prefix
    routes to disable_schedule."""
    sid = _make_schedule()
    assert _is_schedule_enabled(sid)

    msg = _route_cancel_or_disable(sid)

    assert "disabled schedule" in msg
    assert sid[:20] in msg
    assert not _is_schedule_enabled(sid)


@pytest.mark.usefixtures("fresh_db")
def test_route_idempotent_on_already_disabled_schedule() -> None:
    """Second cancel should report 'already disabled' rather than
    re-running the SQL or pretending to succeed."""
    sid = _make_schedule()
    _route_cancel_or_disable(sid)  # first call disables

    msg = _route_cancel_or_disable(sid)

    assert "already disabled" in msg
    assert not _is_schedule_enabled(sid)


@pytest.mark.usefixtures("fresh_db")
def test_route_reports_not_found_for_unknown_schedule_id() -> None:
    """A typo'd or stale sch_ ID must report 'not found' so the
    operator knows their command had no effect."""
    msg = _route_cancel_or_disable("sch_deadbeef_xxxxx")
    assert "not found" in msg


# ---------- smart-route: job path ------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_route_cancels_job_when_id_does_not_start_with_sch() -> None:
    jid = _make_job()
    assert _job_status(jid) == "queued"

    msg = _route_cancel_or_disable(jid)

    assert "cancelled job" in msg
    assert _job_status(jid) == JobStatus.CANCELLED.value


@pytest.mark.usefixtures("fresh_db")
def test_route_reports_not_found_for_unknown_job_id() -> None:
    """V60-5 also fixes the silent-success on cancel against a
    non-existent job ID — pre-fix `/donna_cancel deadbeef` returned
    'cancelled deadbeef' even though no row existed."""
    msg = _route_cancel_or_disable("job_deadbeef_xxxxx")
    assert "not found" in msg


# ---------- explicit /donna_schedule_disable helper ------------------------


@pytest.mark.usefixtures("fresh_db")
def test_disable_schedule_helper_disables_active_schedule() -> None:
    sid = _make_schedule()
    conn = connect()
    try:
        msg = _disable_schedule_by_id(conn, sid)
    finally:
        conn.close()
    assert "disabled schedule" in msg
    assert not _is_schedule_enabled(sid)


@pytest.mark.usefixtures("fresh_db")
def test_disable_schedule_helper_idempotent() -> None:
    sid = _make_schedule()
    conn = connect()
    try:
        _disable_schedule_by_id(conn, sid)
        msg = _disable_schedule_by_id(conn, sid)
    finally:
        conn.close()
    assert "already disabled" in msg


@pytest.mark.usefixtures("fresh_db")
def test_disable_schedule_helper_reports_not_found() -> None:
    conn = connect()
    try:
        msg = _disable_schedule_by_id(conn, "sch_nonexistent_xxxxx")
    finally:
        conn.close()
    assert "not found" in msg


# ---------- _cancel_job_by_id ----------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_cancel_job_helper_cancels_existing_job() -> None:
    jid = _make_job()
    conn = connect()
    try:
        msg = _cancel_job_by_id(conn, jid)
    finally:
        conn.close()
    assert "cancelled job" in msg
    assert _job_status(jid) == JobStatus.CANCELLED.value


@pytest.mark.usefixtures("fresh_db")
def test_cancel_job_helper_reports_not_found_with_hint() -> None:
    """The 'schedule IDs start with `sch_`' hint nudges operators who
    grabbed the wrong ID type."""
    conn = connect()
    try:
        msg = _cancel_job_by_id(conn, "job_nonexistent_xxxxx")
    finally:
        conn.close()
    assert "not found" in msg
    assert "sch_" in msg
