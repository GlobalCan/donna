"""V0.6 #2: async_tasks supervised work-queue tests.

Three layers:
  1. memory.async_tasks DB ops (enqueue / claim / complete / fail / recover)
  2. AsyncTaskRunner dispatch + retry semantics
  3. handle_safe_summary_backfill via the queue (replaces v0.5.2 fire-and-forget)

Validates the contract: durably persisted + leased + retried + dead-lettered,
with deserialization + handler-missing defenses.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from donna.jobs.async_runner import AsyncTaskRunner
from donna.memory import async_tasks as at_mod
from donna.memory.db import connect, transaction

# ---------- helpers -------------------------------------------------------


def _enq(kind: str = "test_kind", payload: dict | None = None,
         scheduled_for: datetime | None = None) -> str:
    conn = connect()
    try:
        with transaction(conn):
            return at_mod.enqueue(
                conn, kind=kind, payload=payload or {"x": 1},
                scheduled_for=scheduled_for,
            )
    finally:
        conn.close()


def _claim(worker: str = "w1", kinds: list[str] | None = None):
    conn = connect()
    try:
        with transaction(conn):
            return at_mod.claim_one(
                conn, worker_id=worker, kinds=kinds or ["test_kind"],
            )
    finally:
        conn.close()


def _read_row(task_id: str):
    conn = connect()
    try:
        return conn.execute(
            "SELECT * FROM async_tasks WHERE id = ?", (task_id,),
        ).fetchone()
    finally:
        conn.close()


# ---------- enqueue / claim_one / complete / fail ----------------------


@pytest.mark.usefixtures("fresh_db")
def test_enqueue_creates_pending_row() -> None:
    tid = _enq(kind="t", payload={"a": "b"})
    row = _read_row(tid)
    assert row is not None
    assert row["status"] == "pending"
    assert row["kind"] == "t"
    assert row["attempts"] == 0
    assert json.loads(row["payload"]) == {"a": "b"}


@pytest.mark.usefixtures("fresh_db")
def test_claim_one_returns_pending_and_marks_running() -> None:
    tid = _enq()
    row = _claim()
    assert row is not None
    assert row["id"] == tid
    assert row["status"] == "running"
    assert row["locked_by"] == "w1"
    assert row["attempts"] == 1
    assert row["started_at"] is not None
    assert row["locked_until"] is not None


@pytest.mark.usefixtures("fresh_db")
def test_claim_one_returns_none_when_no_pending() -> None:
    assert _claim() is None


@pytest.mark.usefixtures("fresh_db")
def test_claim_one_filters_by_kind() -> None:
    """A runner with kinds=[A] must NOT pick up a kind=B task."""
    tid_a = _enq(kind="kind_a")
    _enq(kind="kind_b")
    row = _claim(kinds=["kind_a"])
    assert row is not None
    assert row["id"] == tid_a
    assert row["kind"] == "kind_a"
    # Run again with kind_a only — nothing left of that kind
    assert _claim(kinds=["kind_a"]) is None
    # But kind_b is still pending
    row_b = _claim(kinds=["kind_b"])
    assert row_b is not None
    assert row_b["kind"] == "kind_b"


@pytest.mark.usefixtures("fresh_db")
def test_claim_one_skips_future_scheduled_tasks() -> None:
    """A task scheduled_for=now+10min isn't claimable yet — backoff
    semantics depend on this."""
    future = datetime.now(UTC) + timedelta(minutes=10)
    _enq(scheduled_for=future)
    assert _claim() is None


@pytest.mark.usefixtures("fresh_db")
def test_claim_one_is_race_safe_under_concurrent_runners() -> None:
    """Two runners attempting claim_one on the same single pending task
    must produce one winner + one None. The single-statement UPDATE...
    RETURNING with a subselect is atomic under WAL."""
    _enq()
    conns = [connect(), connect()]
    try:
        # Round-robin two simulated runners; only one should win.
        with transaction(conns[0]):
            r1 = at_mod.claim_one(conns[0], worker_id="w1", kinds=["test_kind"])
        with transaction(conns[1]):
            r2 = at_mod.claim_one(conns[1], worker_id="w2", kinds=["test_kind"])
    finally:
        for c in conns:
            c.close()
    won = [r for r in (r1, r2) if r is not None]
    lost = [r for r in (r1, r2) if r is None]
    assert len(won) == 1
    assert len(lost) == 1


@pytest.mark.usefixtures("fresh_db")
def test_complete_marks_done_owner_guarded() -> None:
    tid = _enq()
    _claim(worker="w1")
    conn = connect()
    try:
        with transaction(conn):
            ok = at_mod.complete(conn, task_id=tid, worker_id="w1")
    finally:
        conn.close()
    assert ok is True
    row = _read_row(tid)
    assert row["status"] == "done"
    assert row["finished_at"] is not None
    assert row["locked_by"] is None


@pytest.mark.usefixtures("fresh_db")
def test_complete_owner_guard_rejects_wrong_worker() -> None:
    """If the lease was reclaimed by another runner, the original holder
    can't mark done — preserves single-runner-wins semantics."""
    tid = _enq()
    _claim(worker="w1")
    conn = connect()
    try:
        with transaction(conn):
            ok = at_mod.complete(conn, task_id=tid, worker_id="w_other")
    finally:
        conn.close()
    assert ok is False
    row = _read_row(tid)
    # Status unchanged
    assert row["status"] == "running"
    assert row["locked_by"] == "w1"


@pytest.mark.usefixtures("fresh_db")
def test_fail_requeues_with_backoff_when_below_max_attempts() -> None:
    tid = _enq()
    _claim(worker="w1")
    before = datetime.now(UTC)
    conn = connect()
    try:
        with transaction(conn):
            ok = at_mod.fail(
                conn, task_id=tid, worker_id="w1",
                error_msg="boom", max_attempts=3, retry_backoff_s=10,
            )
    finally:
        conn.close()
    assert ok is True
    row = _read_row(tid)
    assert row["status"] == "pending"
    assert row["last_error"] == "boom"
    assert row["locked_by"] is None
    # scheduled_for pushed at least retry_backoff_s * 1 seconds out
    sched = (
        datetime.fromisoformat(row["scheduled_for"])
        if isinstance(row["scheduled_for"], str)
        else row["scheduled_for"]
    )
    if sched.tzinfo is None:
        sched = sched.replace(tzinfo=UTC)
    assert sched >= before + timedelta(seconds=8)  # ~10s with timing slack


@pytest.mark.usefixtures("fresh_db")
def test_fail_marks_terminal_failed_at_max_attempts() -> None:
    tid = _enq()
    # Three rounds of claim + fail to hit max_attempts=3.
    for _ in range(3):
        _claim(worker="w1")
        conn = connect()
        try:
            with transaction(conn):
                at_mod.fail(
                    conn, task_id=tid, worker_id="w1",
                    error_msg="still failing",
                    max_attempts=3, retry_backoff_s=0,
                )
        finally:
            conn.close()
    row = _read_row(tid)
    assert row["status"] == "failed"
    assert row["finished_at"] is not None


@pytest.mark.usefixtures("fresh_db")
def test_recover_stale_requeues_expired_leases() -> None:
    """If a runner crashed mid-task, its locked_until passes; next
    runner's recover_stale picks the row back up as pending."""
    tid = _enq()
    _claim(worker="w1")
    # Manually expire the lease (simulating a crashed runner that didn't
    # complete or fail).
    past = datetime.now(UTC) - timedelta(minutes=10)
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE async_tasks SET locked_until = ? WHERE id = ?",
                (past, tid),
            )
        with transaction(conn):
            recovered = at_mod.recover_stale(conn, worker_id="w2")
    finally:
        conn.close()
    assert recovered == 1
    row = _read_row(tid)
    assert row["status"] == "pending"
    assert row["locked_by"] is None
    assert "lease expired" in (row["last_error"] or "")


@pytest.mark.usefixtures("fresh_db")
def test_recover_stale_skips_fresh_running_tasks() -> None:
    """A running task whose lease hasn't expired should NOT be touched."""
    tid = _enq()
    _claim(worker="w1")  # fresh lease, ~60s into the future
    conn = connect()
    try:
        with transaction(conn):
            recovered = at_mod.recover_stale(conn, worker_id="w2")
    finally:
        conn.close()
    assert recovered == 0
    row = _read_row(tid)
    assert row["status"] == "running"
    assert row["locked_by"] == "w1"


@pytest.mark.usefixtures("fresh_db")
def test_count_by_status_returns_snapshot() -> None:
    _enq()
    _enq()
    _claim(worker="w1")
    # Now there's 1 pending + 1 running
    conn = connect()
    try:
        counts = at_mod.count_by_status(conn)
    finally:
        conn.close()
    assert counts.get("pending", 0) == 1
    assert counts.get("running", 0) == 1


# ---------- AsyncTaskRunner dispatch ------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_runner_dispatches_to_handler_and_marks_done() -> None:
    seen: list[dict] = []

    async def handler(payload: dict) -> None:
        seen.append(payload)

    runner = AsyncTaskRunner(
        worker_id="r1", kinds=["test_kind"],
        handlers={"test_kind": handler},
    )
    tid = _enq(payload={"hello": "world"})
    await runner._tick()  # one cycle
    assert seen == [{"hello": "world"}]
    assert _read_row(tid)["status"] == "done"


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_runner_marks_failed_on_handler_exception_at_max_attempts() -> None:
    async def boom(payload: dict) -> None:
        raise RuntimeError("nope")

    runner = AsyncTaskRunner(
        worker_id="r1", kinds=["test_kind"],
        handlers={"test_kind": boom},
    )
    runner.MAX_ATTEMPTS = 1  # fail immediately
    runner.RETRY_BACKOFF_S = 0
    tid = _enq()
    await runner._tick()
    row = _read_row(tid)
    assert row["status"] == "failed"
    assert "nope" in (row["last_error"] or "")


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_runner_retries_and_eventually_succeeds() -> None:
    """Handler fails twice, succeeds third — task lands in 'done'."""
    calls = {"n": 0}

    async def flaky(payload: dict) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(f"flake #{calls['n']}")

    runner = AsyncTaskRunner(
        worker_id="r1", kinds=["test_kind"],
        handlers={"test_kind": flaky},
    )
    runner.MAX_ATTEMPTS = 5
    runner.RETRY_BACKOFF_S = 0  # no wait between retries
    tid = _enq()
    for _ in range(3):
        await runner._tick()
    assert calls["n"] == 3
    assert _read_row(tid)["status"] == "done"


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_runner_fails_task_with_bad_json_payload() -> None:
    """Defensive: malformed JSON in payload is a permanent failure, not
    a transient retry — re-running can't fix the bytes."""

    async def handler(payload: dict) -> None:
        raise AssertionError("should not be called")

    runner = AsyncTaskRunner(
        worker_id="r1", kinds=["test_kind"],
        handlers={"test_kind": handler},
    )
    runner.MAX_ATTEMPTS = 1
    runner.RETRY_BACKOFF_S = 0
    # Manually insert a row with invalid JSON payload
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO async_tasks (id, kind, payload) "
                "VALUES (?, ?, ?)",
                ("at_bad", "test_kind", "not-json{{{"),
            )
    finally:
        conn.close()
    await runner._tick()
    row = _read_row("at_bad")
    assert row["status"] == "failed"
    assert "JSON" in (row["last_error"] or "") or "valid" in (row["last_error"] or "")


def test_runner_construction_validates_kinds_have_handlers() -> None:
    async def h(_: dict) -> None: ...
    with pytest.raises(ValueError, match="no registered handler"):
        AsyncTaskRunner(
            worker_id="r1",
            kinds=["a", "b"],
            handlers={"a": h},  # b has no handler
        )


def test_runner_construction_requires_at_least_one_kind() -> None:
    with pytest.raises(ValueError, match="at least one kind"):
        AsyncTaskRunner(worker_id="r1", kinds=[], handlers={})


# ---------- handle_safe_summary_backfill via the queue ------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_handle_safe_summary_backfill_persists_on_success() -> None:
    """Replaces v0.5.2's direct `_backfill_safe_summary` test: handler
    invoked via the queue path persists the sanitized summary."""
    from donna.agent.context import handle_safe_summary_backfill
    from donna.memory import threads as threads_mod

    # Set up a thread + tainted assistant message
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_test", thread_external_id=None,
            )
            mid = threads_mod.insert_message(
                conn, thread_id=tid, role="assistant",
                content="raw with tokens", tainted=True,
            )
    finally:
        conn.close()

    fake_sanitize = AsyncMock(return_value="paraphrase")
    with patch(
        "donna.security.sanitize.sanitize_untrusted", new=fake_sanitize,
    ):
        await handle_safe_summary_backfill({
            "message_id": mid, "content": "raw with tokens",
            "job_id": "job_x",
        })

    fake_sanitize.assert_awaited_once()
    conn = connect()
    try:
        row = conn.execute(
            "SELECT safe_summary FROM messages WHERE id = ?", (mid,),
        ).fetchone()
    finally:
        conn.close()
    assert row["safe_summary"] == "paraphrase"


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_handle_safe_summary_backfill_raises_on_sanitize_error() -> None:
    """v0.6 #2 contract change: sanitize errors PROPAGATE so the runner's
    retry policy applies. Pre-fix v0.5.2 swallowed errors."""
    from donna.agent.context import handle_safe_summary_backfill

    fake_sanitize = AsyncMock(side_effect=RuntimeError("haiku 500"))
    with patch(
        "donna.security.sanitize.sanitize_untrusted", new=fake_sanitize,
    ), pytest.raises(RuntimeError, match="haiku 500"):
        await handle_safe_summary_backfill({
            "message_id": "msg_x", "content": "raw",
            "job_id": "job_x",
        })


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_handle_safe_summary_backfill_skips_empty_summary() -> None:
    """Empty/whitespace summary is a normal return (not error) — runner
    marks task done, message safe_summary stays NULL."""
    from donna.agent.context import handle_safe_summary_backfill
    from donna.memory import threads as threads_mod

    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_test", thread_external_id=None,
            )
            mid = threads_mod.insert_message(
                conn, thread_id=tid, role="assistant",
                content="raw", tainted=True,
            )
    finally:
        conn.close()

    fake_sanitize = AsyncMock(return_value="   ")
    with patch(
        "donna.security.sanitize.sanitize_untrusted", new=fake_sanitize,
    ):
        # Should NOT raise
        await handle_safe_summary_backfill({
            "message_id": mid, "content": "raw", "job_id": "job_x",
        })
    conn = connect()
    try:
        row = conn.execute(
            "SELECT safe_summary FROM messages WHERE id = ?", (mid,),
        ).fetchone()
    finally:
        conn.close()
    assert row["safe_summary"] is None


# ---------- end-to-end: enqueue from finalize, drain via runner --------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_enqueue_from_finalize_then_runner_dispatches() -> None:
    """The full v0.6 #2 contract: a tainted job's finalize-hook enqueue
    is later picked up by the worker's AsyncTaskRunner and the
    safe_summary appears on the message row."""
    from donna.agent.context import (
        _enqueue_safe_summary_backfill,
        handle_safe_summary_backfill,
    )
    from donna.memory import threads as threads_mod

    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_test", thread_external_id=None,
            )
            mid = threads_mod.insert_message(
                conn, thread_id=tid, role="assistant",
                content="raw weather summary", tainted=True,
            )
    finally:
        conn.close()

    # Simulate finalize's enqueue
    _enqueue_safe_summary_backfill(
        message_id=mid, content="raw weather summary", job_id="job_x",
    )

    # One row should be pending of kind safe_summary_backfill
    conn = connect()
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) c FROM async_tasks "
            "WHERE kind = 'safe_summary_backfill' AND status = 'pending'"
        ).fetchone()["c"]
    finally:
        conn.close()
    assert cnt == 1

    # Runner picks it up, dispatches, completes
    runner = AsyncTaskRunner(
        worker_id="worker-async",
        kinds=["safe_summary_backfill"],
        handlers={"safe_summary_backfill": handle_safe_summary_backfill},
    )
    fake_sanitize = AsyncMock(return_value="Ottawa was 7C and clear.")
    with patch(
        "donna.security.sanitize.sanitize_untrusted", new=fake_sanitize,
    ):
        await runner._tick()

    conn = connect()
    try:
        row = conn.execute(
            "SELECT safe_summary FROM messages WHERE id = ?", (mid,),
        ).fetchone()
        task_status = conn.execute(
            "SELECT status FROM async_tasks "
            "WHERE kind = 'safe_summary_backfill'"
        ).fetchone()["status"]
    finally:
        conn.close()
    assert row["safe_summary"] == "Ottawa was 7C and clear."
    assert task_status == "done"


@pytest.mark.usefixtures("fresh_db")
def test_async_tasks_table_exists() -> None:
    conn = connect()
    try:
        cols = {
            r["name"] for r in conn.execute(
                "PRAGMA table_info(async_tasks)"
            ).fetchall()
        }
    finally:
        conn.close()
    assert {
        "id", "kind", "payload", "status", "attempts", "last_error",
        "scheduled_for", "created_at", "started_at", "finished_at",
        "locked_until", "locked_by",
    } <= cols
