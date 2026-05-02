"""V0.6 #5: retention policy + auto-purge tests.

Covers per-table age cutoffs, FK safety (tool_calls deleted before jobs),
terminal-only filters (async_tasks pending NEVER purged), dry-run honesty
(same WHERE clause as the real delete), and the botctl surface.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from donna.cli.botctl import app
from donna.memory import async_tasks as at_mod
from donna.memory import jobs as jobs_mod
from donna.memory import retention as ret_mod
from donna.memory.db import connect, transaction
from donna.types import JobStatus

runner = CliRunner()


def _ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


# ---------- helpers ------------------------------------------------------


def _make_done_job(*, finished_days_ago: int) -> str:
    """Insert a finished job with a backdated finished_at."""
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(conn, task="t")
            jobs_mod.set_status(conn, jid, JobStatus.DONE)
            conn.execute(
                "UPDATE jobs SET finished_at = ? WHERE id = ?",
                (_ago(finished_days_ago), jid),
            )
    finally:
        conn.close()
    return jid


def _make_tool_call(*, job_id: str, days_ago: int) -> None:
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO tool_calls "
                "(id, job_id, tool_name, arguments, status, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"tc_{uuid.uuid4().hex[:12]}", job_id, "tool",
                    "{}", "ok", _ago(days_ago),
                ),
            )
    finally:
        conn.close()


def _make_trace(*, days_ago: int) -> None:
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO traces "
                "(id, span_name, attributes, started_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    f"sp_{uuid.uuid4().hex[:12]}", "test_span", "{}",
                    _ago(days_ago),
                ),
            )
    finally:
        conn.close()


def _make_dl(*, moved_days_ago: int) -> str:
    """Backdate the moved_at timestamp."""
    from donna.memory import dead_letter as dl_mod
    job_id = _make_done_job(finished_days_ago=0)
    conn = connect()
    try:
        with transaction(conn):
            dl_id = dl_mod.record_dead_letter(
                conn, source_table="outbox_updates", source_id="x",
                job_id=job_id, channel_id="C_X", thread_ts=None,
                payload="p", tainted=False, error_code="x",
                error_class="terminal", attempt_count=1,
                first_attempt_at=None,
            )
        with transaction(conn):
            conn.execute(
                "UPDATE outbox_dead_letter SET moved_at = ? WHERE id = ?",
                (_ago(moved_days_ago), dl_id),
            )
    finally:
        conn.close()
    return dl_id


def _count(table: str) -> int:
    conn = connect()
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


# ---------- purge_old per-table behavior ---------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_purge_old_on_empty_db_returns_zero_counts() -> None:
    conn = connect()
    try:
        with transaction(conn):
            counts = ret_mod.purge_old(conn)
    finally:
        conn.close()
    assert all(n == 0 for n in counts.values()), counts


@pytest.mark.usefixtures("fresh_db")
def test_purge_traces_drops_old_keeps_fresh() -> None:
    """traces retention is 30 days. Verify boundary."""
    _make_trace(days_ago=10)   # fresh
    _make_trace(days_ago=45)   # old
    _make_trace(days_ago=200)  # ancient
    assert _count("traces") == 3
    conn = connect()
    try:
        with transaction(conn):
            counts = ret_mod.purge_old(conn)
    finally:
        conn.close()
    assert counts["traces"] == 2
    assert _count("traces") == 1


@pytest.mark.usefixtures("fresh_db")
def test_purge_dead_letter_uses_moved_at() -> None:
    """Dead-letter rows past 90d horizon are purged."""
    fresh = _make_dl(moved_days_ago=30)
    old = _make_dl(moved_days_ago=120)
    assert _count("outbox_dead_letter") == 2
    conn = connect()
    try:
        with transaction(conn):
            counts = ret_mod.purge_old(conn)
    finally:
        conn.close()
    assert counts["outbox_dead_letter"] == 1
    conn = connect()
    try:
        remaining = {
            r["id"] for r in conn.execute(
                "SELECT id FROM outbox_dead_letter"
            ).fetchall()
        }
    finally:
        conn.close()
    assert remaining == {fresh}
    assert old not in remaining


@pytest.mark.usefixtures("fresh_db")
def test_purge_jobs_terminal_only_keeps_running() -> None:
    """Active (running) jobs from any era must NOT be purged."""
    # An ancient running job — never finished
    conn = connect()
    try:
        with transaction(conn):
            running_id = jobs_mod.insert_job(conn, task="long-running")
            conn.execute(
                "UPDATE jobs SET status = 'running', "
                "  created_at = ?, finished_at = NULL "
                "WHERE id = ?",
                (_ago(365), running_id),
            )
    finally:
        conn.close()
    # Old terminal jobs (should be purged)
    _make_done_job(finished_days_ago=200)
    # Fresh terminal job (must NOT be purged)
    fresh_done = _make_done_job(finished_days_ago=10)

    conn = connect()
    try:
        with transaction(conn):
            counts = ret_mod.purge_old(conn)
    finally:
        conn.close()
    assert counts["jobs"] == 1  # only the 200d-old one
    conn = connect()
    try:
        remaining = {
            r["id"] for r in conn.execute(
                "SELECT id FROM jobs"
            ).fetchall()
        }
    finally:
        conn.close()
    assert running_id in remaining
    assert fresh_done in remaining


@pytest.mark.usefixtures("fresh_db")
def test_purge_tool_calls_before_parent_jobs_for_fk_safety() -> None:
    """FK direction: tool_calls.job_id -> jobs.id. With foreign_keys=ON
    we must purge tool_calls BEFORE their parent jobs or DELETE fails."""
    job = _make_done_job(finished_days_ago=200)
    _make_tool_call(job_id=job, days_ago=200)
    _make_tool_call(job_id=job, days_ago=200)
    # If purge order is wrong, this raises sqlite IntegrityError.
    conn = connect()
    try:
        with transaction(conn):
            counts = ret_mod.purge_old(conn)
    finally:
        conn.close()
    assert counts["tool_calls"] == 2
    assert counts["jobs"] == 1
    assert _count("tool_calls") == 0
    assert _count("jobs") == 0


@pytest.mark.usefixtures("fresh_db")
def test_purge_async_tasks_terminal_only() -> None:
    """Pending async_tasks must NEVER be purged — they're the work queue.
    Only done/failed rows past horizon are removed."""
    conn = connect()
    try:
        with transaction(conn):
            # Pending — must survive
            pending_id = at_mod.enqueue(
                conn, kind="t", payload={"x": 1},
            )
            # Old done — should purge
            old_done = at_mod.enqueue(
                conn, kind="t", payload={"x": 2},
            )
            conn.execute(
                "UPDATE async_tasks SET status = 'done', "
                "finished_at = ? WHERE id = ?",
                (_ago(60), old_done),
            )
            # Old failed — should purge
            old_failed = at_mod.enqueue(
                conn, kind="t", payload={"x": 3},
            )
            conn.execute(
                "UPDATE async_tasks SET status = 'failed', "
                "finished_at = ? WHERE id = ?",
                (_ago(60), old_failed),
            )
            # Fresh done — must survive (under 30d horizon)
            fresh_done = at_mod.enqueue(
                conn, kind="t", payload={"x": 4},
            )
            conn.execute(
                "UPDATE async_tasks SET status = 'done', "
                "finished_at = ? WHERE id = ?",
                (_ago(5), fresh_done),
            )
    finally:
        conn.close()
    conn = connect()
    try:
        with transaction(conn):
            counts = ret_mod.purge_old(conn)
    finally:
        conn.close()
    assert counts["async_tasks"] == 2
    conn = connect()
    try:
        remaining = {
            r["id"] for r in conn.execute(
                "SELECT id FROM async_tasks"
            ).fetchall()
        }
    finally:
        conn.close()
    assert pending_id in remaining
    assert fresh_done in remaining
    assert old_done not in remaining
    assert old_failed not in remaining


# ---------- dry_run ------------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_dry_run_returns_same_counts_without_deleting() -> None:
    """Dry-run honesty: must use the same WHERE clause as the real
    delete, and must NOT mutate the DB."""
    _make_trace(days_ago=200)
    _make_trace(days_ago=200)
    before = _count("traces")
    conn = connect()
    try:
        with transaction(conn):
            dry_counts = ret_mod.purge_old(conn, dry_run=True)
    finally:
        conn.close()
    after = _count("traces")
    assert before == after  # no deletes happened
    assert dry_counts["traces"] == 2

    # Real run now produces the same count
    conn = connect()
    try:
        with transaction(conn):
            real_counts = ret_mod.purge_old(conn)
    finally:
        conn.close()
    assert real_counts["traces"] == dry_counts["traces"]


# ---------- status() snapshot --------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_status_returns_total_and_would_purge() -> None:
    _make_trace(days_ago=10)
    _make_trace(days_ago=200)
    conn = connect()
    try:
        snap = ret_mod.status(conn)
    finally:
        conn.close()
    assert snap["traces"]["total"] == 2
    assert snap["traces"]["would_purge"] == 1


# ---------- botctl retention surface -------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_botctl_retention_status_renders_table() -> None:
    _make_trace(days_ago=200)
    result = runner.invoke(app, ["retention", "status"])
    assert result.exit_code == 0, result.output
    assert "traces" in result.output
    assert "would purge" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_botctl_retention_purge_dry_run_does_not_delete() -> None:
    _make_trace(days_ago=200)
    result = runner.invoke(app, ["retention", "purge", "--dry-run"])
    assert result.exit_code == 0
    assert "would purge" in result.output
    # Trace still present
    assert _count("traces") == 1


@pytest.mark.usefixtures("fresh_db")
def test_botctl_retention_purge_actually_deletes() -> None:
    _make_trace(days_ago=200)
    _make_trace(days_ago=10)  # fresh — should survive
    assert _count("traces") == 2
    result = runner.invoke(app, ["retention", "purge"])
    assert result.exit_code == 0
    assert "purged" in result.output
    assert _count("traces") == 1
