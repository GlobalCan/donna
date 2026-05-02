"""V0.6 #8: integration spine.

Codex 2026-05-01: "414 tests and a 1:1 test-to-source ratio is strong
for a young system, but the shape is too unit-heavy. The risk is exactly:
'tests pass, prod breaks.' You already saw that with scheduler delivery,
cross-process outbox, and adapter migration issues. Add 8 to 12 boring
integration tests that exercise real SQLite, real migrations, fake
Slack, fake model, fake embeddings."

These tests glue together the actual modules across process boundaries
(JobContext / outbox / drainer / async runner / sanitizer) using fake
Slack clients + fake model adapters. Each one exercises a seam that
has caused real production bugs before.

Specifically:
  1. Chat-mode finalize -> outbox -> drainer -> chat.postMessage -> row deleted
     (P1-3/P1-4 historical: chat mode's final_text was orphaned)
  2. Terminal Slack error -> drainer routes to outbox_dead_letter, source
     row deleted (V50-1: was infinite retry loop)
  3. rate_limited error -> drainer respects Retry-After cool-down
     (V50-1 follow-on: was hammering Slack 1/sec forever)
  4. Tainted assistant row -> async_task enqueued -> AsyncTaskRunner
     dispatches -> handler sanitizes -> safe_summary persisted
     (V50-8 + v0.6 #2: pre-fix the task was lost on worker restart)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError

from donna.adapter.slack_adapter import DonnaSlackBot
from donna.adapter.slack_errors import ErrorClass
from donna.agent.context import JobContext
from donna.jobs.async_runner import AsyncTaskRunner
from donna.memory import jobs as jobs_mod
from donna.memory import threads as threads_mod
from donna.memory.db import connect, transaction

# ---------- helpers ------------------------------------------------------


class _FakeResponse:
    def __init__(self, data: dict, headers: dict | None = None):
        self.data = data
        self.headers = headers or {}


def _slack_error(code: str, headers: dict | None = None) -> SlackApiError:
    return SlackApiError(
        message=f"slack rejected: {code}",
        response=_FakeResponse(
            data={"ok": False, "error": code}, headers=headers,
        ),
    )


def _build_bot_no_app() -> DonnaSlackBot:
    """Construct DonnaSlackBot bypassing __init__ (which would try to
    open a real Socket Mode connection)."""
    bot = DonnaSlackBot.__new__(DonnaSlackBot)
    bot._last_sent_per_channel = {}
    bot._rate_limited_until = {}
    bot._alert_throttle = {}
    bot.client = MagicMock()
    return bot


def _make_job_in_thread(*, channel: str = "C_test") -> tuple[str, str]:
    """Create a thread + a chat-mode job inside it. Returns (job_id,
    thread_id). Sets up the FK chain that finalize and the drainer
    expect."""
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id=channel, thread_external_id=None,
            )
            jid = jobs_mod.insert_job(
                conn, task="hello", thread_id=tid,
            )
            # Claim the lease so finalize's owner-guard passes.
            conn.execute(
                "UPDATE jobs SET status = 'running', owner = ?, "
                "lease_until = datetime('now', '+5 minutes') "
                "WHERE id = ?",
                ("integration-worker", jid),
            )
    finally:
        conn.close()
    return jid, tid


# ---------- 1. Chat-mode roundtrip --------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_chat_finalize_outbox_drainer_post_deletes_row() -> None:
    """End-to-end: chat job's final_text reaches the channel and the
    outbox row is cleaned up. Pre-fix (Phase 1 P1-3/P1-4) this orphaned
    silently — finalize wrote final_text to a field nobody read."""
    jid, _tid = _make_job_in_thread()

    # Run finalize
    conn = connect()
    try:
        job = jobs_mod.get_job(conn, jid)
    finally:
        conn.close()
    ctx = JobContext(job, worker_id="integration-worker")
    ctx.state.final_text = "Mark Twain civilization summary."
    ctx.state.done = True
    assert ctx.finalize() is True

    # Outbox row should exist
    conn = connect()
    try:
        before = conn.execute(
            "SELECT id, text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(before) == 1
    assert before[0]["text"] == "Mark Twain civilization summary."

    # Now the drainer with a mock client
    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        return_value={"ok": True, "ts": "1.0"},
    )

    # Read the row back the way the drainer would
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE id = ?", (before[0]["id"],),
        ).fetchone()
    finally:
        conn.close()

    result = await bot._post_update(
        channel="C_test", job_id=jid, thread_ts=None,
        text=row["text"], tainted=False,
    )
    assert result.ok is True
    bot._handle_update_result(
        row=row, channel="C_test", thread_ts=None,
        result=result, last_sent_per_job={},
    )

    # Row deleted
    conn = connect()
    try:
        after = conn.execute(
            "SELECT id FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(after) == 0
    bot.client.chat_postMessage.assert_awaited_once()


# ---------- 2. V50-1 dead-letter routing -------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_terminal_error_routes_source_to_dead_letter() -> None:
    """V50-1 end-to-end: bot tries to deliver, Slack returns not_in_channel,
    drainer routes to outbox_dead_letter + deletes source row. Pre-fix
    this was an infinite retry loop at 1.5s intervals."""
    jid, _tid = _make_job_in_thread(channel="C_DEAD")

    ctx = JobContext(_load(jid), worker_id="integration-worker")
    ctx.state.final_text = "won't deliver"
    ctx.state.done = True
    assert ctx.finalize() is True

    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        side_effect=_slack_error("not_in_channel"),
    )

    # Drain
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()

    result = await bot._post_update(
        channel="C_DEAD", job_id=jid, thread_ts=None,
        text=row["text"], tainted=False,
    )
    assert result.ok is False
    assert result.error_class is ErrorClass.TERMINAL

    bot._handle_update_result(
        row=row, channel="C_DEAD", thread_ts=None,
        result=result, last_sent_per_job={},
    )

    conn = connect()
    try:
        outbox = conn.execute(
            "SELECT id FROM outbox_updates WHERE id = ?", (row["id"],),
        ).fetchone()
        dl = conn.execute(
            "SELECT source_id, error_code, error_class "
            "FROM outbox_dead_letter WHERE source_id = ?", (row["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert outbox is None  # source row gone
    assert dl is not None
    assert dl["error_code"] == "not_in_channel"
    assert dl["error_class"] == "terminal"


# ---------- 3. V50-1 rate-limited cool-down ----------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_rate_limited_sets_per_channel_cool_down() -> None:
    """V50-1 follow-on: rate_limited with Retry-After must populate the
    bot's _rate_limited_until map so the drainer skips that channel
    until the cool-down expires. Pre-fix (v0.5.0) the drainer just
    backed off ~1.5s and hammered Slack again."""
    jid, _tid = _make_job_in_thread(channel="C_LIM")
    ctx = JobContext(_load(jid), worker_id="integration-worker")
    ctx.state.final_text = "rate-limited test"
    ctx.state.done = True
    ctx.finalize()

    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        side_effect=_slack_error("rate_limited", headers={"Retry-After": "45"}),
    )
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()

    result = await bot._post_update(
        channel="C_LIM", job_id=jid, thread_ts=None,
        text=row["text"], tainted=False,
    )
    assert result.error_class is ErrorClass.TRANSIENT
    assert result.retry_after_s == 45.0

    import time
    before = time.time()
    bot._handle_update_result(
        row=row, channel="C_LIM", thread_ts=None,
        result=result, last_sent_per_job={},
    )
    until = bot._rate_limited_until.get("C_LIM")
    assert until is not None
    assert until >= before + 44.0  # ~45s cool-down

    # Source row stayed (transient = retry)
    conn = connect()
    try:
        still_there = conn.execute(
            "SELECT attempt_count FROM outbox_updates WHERE id = ?",
            (row["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert still_there is not None
    assert still_there["attempt_count"] == 1


# ---------- 4. V50-8 + v0.6 #2: queue-backed safe_summary backfill ----


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_tainted_finalize_enqueues_then_runner_persists_summary() -> None:
    """End-to-end: tainted job's finalize-hook enqueues an async_task,
    AsyncTaskRunner picks it up, handler runs (mocked) sanitizer,
    safe_summary lands on the messages row. Pre-v0.6 this was
    fire-and-forget — worker death between finalize and sanitize lost
    the work."""
    from donna.agent.context import _enqueue_safe_summary_backfill

    jid, tid = _make_job_in_thread()

    # Insert a tainted assistant message (what finalize would do for a
    # tainted job) and capture its id.
    conn = connect()
    try:
        with transaction(conn):
            mid = threads_mod.insert_message(
                conn, thread_id=tid, role="assistant",
                content="raw web summary with attacker tokens",
                tainted=True,
            )
    finally:
        conn.close()

    # Simulate finalize's enqueue
    _enqueue_safe_summary_backfill(
        message_id=mid, content="raw web summary with attacker tokens",
        job_id=jid,
    )

    # Verify a pending async_task exists
    conn = connect()
    try:
        pending = conn.execute(
            "SELECT id, kind, status FROM async_tasks "
            "WHERE kind = 'safe_summary_backfill' AND status = 'pending'"
        ).fetchall()
    finally:
        conn.close()
    assert len(pending) == 1

    # Spin up the runner with mocked sanitize
    from donna.agent.context import handle_safe_summary_backfill
    runner = AsyncTaskRunner(
        worker_id="integration-async",
        kinds=["safe_summary_backfill"],
        handlers={"safe_summary_backfill": handle_safe_summary_backfill},
    )
    fake_sanitize = AsyncMock(return_value="Web said the weather was nice.")
    with patch(
        "donna.security.sanitize.sanitize_untrusted", new=fake_sanitize,
    ):
        await runner._tick()

    # Task done, safe_summary persisted
    conn = connect()
    try:
        task_status = conn.execute(
            "SELECT status FROM async_tasks "
            "WHERE kind = 'safe_summary_backfill'"
        ).fetchone()["status"]
        msg = conn.execute(
            "SELECT safe_summary, content FROM messages WHERE id = ?",
            (mid,),
        ).fetchone()
    finally:
        conn.close()
    assert task_status == "done"
    assert msg["safe_summary"] == "Web said the weather was nice."
    # Raw audit field intact
    assert "attacker tokens" in msg["content"]


# ---------- helpers (continued) -----------------------------------------


def _load(jid: str):
    conn = connect()
    try:
        return jobs_mod.get_job(conn, jid)
    finally:
        conn.close()
