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

V0.7 surfaces (V70-3):
  5. Scheduler-fired morning_brief -> finalize -> outbox -> drainer posts to
     schedules.target_channel_id (full v0.7.0 cron-to-Slack path)
  6. Two scheduler ticks within the same minute produce exactly ONE
     delivered brief (claim_brief_run dedup at the scheduler level)
  7. /donna_validate refusal -> finalize -> outbox -> drainer delivers
     refusal text (SSRF-blocked URL exits cleanly through the same path)
  8. /donna_validate happy path with mocked fetch + mocked model_step:
     tainted artifact saved, ctx.state.tainted=True, ✅ validated badge,
     finalize delivers to outbox
  9. target_channel_id resolver: legacy kind='task' schedule with
     diverged target_channel_id vs. thread.channel_id ends up posting
     to schedules.target_channel_id (v0.6.3 fix wired through to the
     drainer, end-to-end)
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


def _claim_lease(jid: str, *, worker_id: str = "integration-worker") -> None:
    """Mark a job 'running' with `worker_id` so finalize's owner-guard
    passes. The scheduler-fired path leaves jobs queued; tests that
    drive finalize directly need the lease."""
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE jobs SET status = 'running', owner = ?, "
                "lease_until = datetime('now', '+5 minutes') "
                "WHERE id = ?",
                (worker_id, jid),
            )
    finally:
        conn.close()


async def _drain_one(
    bot: DonnaSlackBot, *, job_id: str, expected_channel: str,
) -> None:
    """Run one full drainer iteration for the row(s) belonging to
    `job_id`: resolve the channel via the bot's resolver, post via the
    mocked client, run _handle_update_result. Mirrors the production
    poll loop's per-row branch."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE job_id = ?", (job_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"no outbox row for job_id={job_id}"
    chan = await bot._resolve_channel_for_job(job_id)
    assert chan == expected_channel, (
        f"resolver gave {chan!r}, expected {expected_channel!r}"
    )
    result = await bot._post_update(
        channel=chan, job_id=job_id, thread_ts=None,
        text=row["text"], tainted=bool(row["tainted"]),
    )
    bot._handle_update_result(
        row=row, channel=chan, thread_ts=None,
        result=result, last_sent_per_job={},
    )


# ---------- 5. v0.7.0 scheduler-fired morning brief end-to-end -----------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_scheduler_morning_brief_finalize_outbox_drainer_to_target_channel() -> None:
    """End-to-end v0.7.0: Scheduler._fire on a kind='morning_brief'
    schedule creates a brief_run row + a chat-mode job back-linked to
    the schedule. After the agent loop finishes (simulated by setting
    final_text directly), finalize writes to outbox; the drainer
    resolves the schedule's target_channel_id ("C_BRIEF") and posts
    there. Pre-v0.7 there was no such path at all."""
    from donna.jobs.scheduler import Scheduler
    from donna.memory import schedules as sched_mod

    # Build a morning_brief schedule pointed at C_BRIEF, with a thread
    # also in C_BRIEF (matches the V50-2 modal flow's co-set behavior).
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_BRIEF", thread_external_id=None,
            )
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr="0 12 * * *",
                task="brief auto",
                mode="chat",
                thread_id=tid,
                target_channel_id="C_BRIEF",
                kind="morning_brief",
                payload={"topics": ["AI safety"], "tz": "UTC"},
            )
            sched = dict(conn.execute(
                "SELECT * FROM schedules WHERE id = ?", (sid,),
            ).fetchone())
    finally:
        conn.close()

    # Scheduler fires the brief: creates brief_run + the chat job.
    await Scheduler()._fire(sched)

    conn = connect()
    try:
        runs = conn.execute(
            "SELECT id, job_id, status FROM brief_runs WHERE schedule_id = ?",
            (sid,),
        ).fetchall()
        jobs = conn.execute(
            "SELECT id, schedule_id, mode, thread_id "
            "FROM jobs WHERE schedule_id = ?", (sid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(runs) == 1
    assert len(jobs) == 1
    assert jobs[0]["mode"] == "chat"
    assert jobs[0]["schedule_id"] == sid
    jid = jobs[0]["id"]
    assert runs[0]["job_id"] == jid

    # Simulate the agent loop finishing — claim the lease, set
    # final_text, finalize. Mocked model_step is implicit here: we
    # don't run agent.loop; we just stuff the final result the way the
    # chat loop would.
    _claim_lease(jid)
    job = _load(jid)
    ctx = JobContext(job, worker_id="integration-worker")
    ctx.state.final_text = "Today: AI safety updates from this morning."
    ctx.state.done = True
    assert ctx.finalize() is True

    # Outbox row exists.
    conn = connect()
    try:
        outbox_rows = conn.execute(
            "SELECT id, text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(outbox_rows) == 1

    # Drain via the resolver path. Resolver must return C_BRIEF (from
    # schedule.target_channel_id), drainer posts there, row deleted.
    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        return_value={"ok": True, "ts": "1.0"},
    )
    await _drain_one(bot, job_id=jid, expected_channel="C_BRIEF")

    bot.client.chat_postMessage.assert_awaited_once()
    sent_kwargs = bot.client.chat_postMessage.await_args.kwargs
    assert sent_kwargs["channel"] == "C_BRIEF"
    assert "AI safety updates" in sent_kwargs["text"]

    # Source row gone.
    conn = connect()
    try:
        after = conn.execute(
            "SELECT id FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(after) == 0


# ---------- 6. Within-minute scheduler dedup -----------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_two_scheduler_ticks_same_minute_produce_one_brief() -> None:
    """Codex 2026-05-02 idempotency contract: two scheduler ticks
    inside the same minute (within-minute race / retry / multi-worker)
    must produce exactly one brief_run, one job, one outbox row. The
    UNIQUE(schedule_id, fire_key) on brief_runs enforces it; this test
    exercises the contract through the full Scheduler._fire path
    rather than only the claim_brief_run helper."""
    from datetime import UTC, datetime

    from donna.jobs import scheduler as sched_module
    from donna.jobs.scheduler import Scheduler
    from donna.memory import schedules as sched_mod

    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_BRIEF", thread_external_id=None,
            )
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr="0 12 * * *",
                task="brief auto",
                mode="chat",
                thread_id=tid,
                target_channel_id="C_BRIEF",
                kind="morning_brief",
                payload={"topics": ["x"]},
            )
            sched = dict(conn.execute(
                "SELECT * FROM schedules WHERE id = ?", (sid,),
            ).fetchone())
    finally:
        conn.close()

    # Pin wall time inside scheduler so two _fire calls 30s apart land
    # in the same minute regardless of when the test runs.
    fire_a = datetime(2026, 5, 2, 12, 0, 5, tzinfo=UTC)
    fire_b = datetime(2026, 5, 2, 12, 0, 35, tzinfo=UTC)

    class _FakeDT:
        @staticmethod
        def now(tz=None):
            return _FakeDT._fixed

    _FakeDT._fixed = fire_a
    with patch.object(sched_module, "datetime", _FakeDT):
        await Scheduler()._fire(sched)
        # Reload schedule (mark_ran updated next_run_at) so second call
        # sees the same identity but fresh state.
        conn = connect()
        try:
            sched_b = dict(conn.execute(
                "SELECT * FROM schedules WHERE id = ?", (sid,),
            ).fetchone())
        finally:
            conn.close()
        _FakeDT._fixed = fire_b
        await Scheduler()._fire(sched_b)

    # Exactly one brief_run, one job, one outbox row.
    conn = connect()
    try:
        runs = conn.execute(
            "SELECT id, job_id FROM brief_runs WHERE schedule_id = ?",
            (sid,),
        ).fetchall()
        jobs_rows = conn.execute(
            "SELECT id FROM jobs WHERE schedule_id = ?", (sid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(runs) == 1, (
        f"expected exactly 1 brief_run; got {len(runs)} — within-minute dedup broken"
    )
    assert len(jobs_rows) == 1, (
        f"expected exactly 1 job; got {len(jobs_rows)} — loser of the race leaked"
    )
    jid = jobs_rows[0]["id"]
    assert runs[0]["job_id"] == jid

    # Outbox: simulate finalize for the surviving job and check that
    # only one outbox row exists.
    _claim_lease(jid)
    job = _load(jid)
    ctx = JobContext(job, worker_id="integration-worker")
    ctx.state.final_text = "deduped brief output"
    ctx.state.done = True
    assert ctx.finalize() is True

    conn = connect()
    try:
        outbox_count = conn.execute(
            "SELECT COUNT(*) AS n FROM outbox_updates WHERE job_id = ?",
            (jid,),
        ).fetchone()["n"]
    finally:
        conn.close()
    assert outbox_count == 1


# ---------- 7. /donna_validate refusal end-to-end ------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_validate_refusal_finalize_outbox_drainer() -> None:
    """v0.7.1 SSRF refusal path: a localhost URL must produce a
    refusal final_text via run_validate, finalize must persist it to
    outbox, and the drainer must deliver it to the operator's thread.
    Pre-v0.7.1 there was no such mode at all; this locks in that the
    refusal still hits the same delivery spine."""
    from donna.modes.validate import run_validate
    from donna.types import JobMode

    # Insert a validate-mode job in a normal thread.
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_VAL", thread_external_id=None,
            )
            jid = jobs_mod.insert_job(
                conn,
                task="http://localhost/admin",
                mode=JobMode.VALIDATE,
                thread_id=tid,
                agent_scope="validate_url",
            )
    finally:
        conn.close()
    _claim_lease(jid)

    job = _load(jid)
    ctx = JobContext(job, worker_id="integration-worker")
    # Don't actually call model_step on refusal; assert it's never used.
    ctx.model_step = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("model_step must not run on refusal"),
    )
    await run_validate(ctx)

    assert ctx.state.done is True
    assert ctx.state.tainted is True  # validate jobs are always tainted
    assert ctx.state.final_text is not None
    assert ctx.state.final_text.startswith("[validate · refused]")

    # Drive finalize -> outbox -> drainer.
    assert ctx.finalize() is True

    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        return_value={"ok": True, "ts": "1.0"},
    )
    await _drain_one(bot, job_id=jid, expected_channel="C_VAL")

    bot.client.chat_postMessage.assert_awaited_once()
    sent_text = bot.client.chat_postMessage.await_args.kwargs["text"]
    assert "validate · refused" in sent_text

    conn = connect()
    try:
        leftover = conn.execute(
            "SELECT id FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(leftover) == 0


# ---------- 8. /donna_validate happy path with mocked fetch + model ------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_validate_happy_path_with_mocked_fetch_delivers_validated_badge() -> None:
    """v0.7.1 happy path: mocked SSRF-safe fetch returns a deterministic
    article; mocked model_step returns a JSON response with verbatim
    quoted_span. run_validate saves a tainted artifact, builds chunks,
    runs _do_validation, sets final_text with the ✅ validated badge.
    finalize then delivers via outbox + drainer."""
    import json as _json
    from unittest.mock import AsyncMock, patch

    from donna.agent.model_adapter import GenerateResult
    from donna.modes import validate as validate_mod
    from donna.modes.validate import run_validate
    from donna.types import Chunk, JobMode

    # Insert a validate-mode job pointed at a benign URL.
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_VAL2", thread_external_id=None,
            )
            jid = jobs_mod.insert_job(
                conn,
                task="https://example.com/article",
                mode=JobMode.VALIDATE,
                thread_id=tid,
                agent_scope="validate_url",
            )
    finally:
        conn.close()
    _claim_lease(jid)

    # Deterministic chunk content the mocked model can quote verbatim.
    article_md = (
        "# Title\n\nFirst paragraph: the framework standardizes "
        "validation output for grounded agents.\n\nSecond paragraph: "
        "developers can audit each claim against its cited chunk."
    )

    async def _fake_fetch(url: str) -> tuple[str, str]:
        return (article_md, "text/markdown")

    # We patch _build_chunks_from_text to inject a chunk with a known
    # id/content pair so the mocked model output's citations and
    # quoted_span line up regardless of the artifact_id randomness.
    fixed_chunk_id = "validate_chunk_0"
    fixed_chunk_content = (
        "the framework standardizes validation output for grounded agents"
    )
    fixed_chunks = [Chunk(
        id=fixed_chunk_id,
        source_id="art_validate_test",
        agent_scope="validate_url",
        work_id=None,
        publication_date=None,
        source_type="url",
        content=fixed_chunk_content,
        score=1.0,
        chunk_index=0,
        is_style_anchor=False,
        source_title="https://example.com/article",
    )]

    def _fake_build_chunks(*, text, source_id, source_title):
        return fixed_chunks

    canned_json = _json.dumps({
        "claims": [{
            "text": "The framework standardizes grounded validation output.",
            "citations": [fixed_chunk_id],
            # Verbatim ≥20 char substring of fixed_chunk_content.
            "quoted_span": "the framework standardizes validation output",
        }],
        "prose": (
            "The article describes how the framework standardizes "
            f"validation output for grounded agents [#{fixed_chunk_id}]."
        ),
    })
    canned_result = GenerateResult(
        text=canned_json,
        stop_reason="end_turn",
        tool_uses=[],
        raw_content=[],
        model="mock-model",
        input_tokens=10,
        output_tokens=10,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=0.0,
    )

    job = _load(jid)
    ctx = JobContext(job, worker_id="integration-worker")
    ctx.model_step = AsyncMock(  # type: ignore[method-assign]
        return_value=canned_result,
    )

    # Bypass the pre-flight DNS-driven SSRF check too — the test runs
    # offline and example.com would 403 on most CI sandboxes anyway.
    # Only the URL safety contract is being asserted by the refusal
    # test (#7); this one exercises the post-fetch validate path.
    def _noop_assert_safe(_url: str) -> None:
        return None

    with patch.object(
        validate_mod, "_ssrf_safe_fetch", new=_fake_fetch,
    ), patch.object(
        validate_mod, "_build_chunks_from_text", new=_fake_build_chunks,
    ), patch.object(
        validate_mod, "assert_safe_url", new=_noop_assert_safe,
    ):
        await run_validate(ctx)

    # Validate-mode contract assertions.
    assert ctx.state.done is True
    assert ctx.state.tainted is True
    assert ctx.state.final_text is not None
    final = ctx.state.final_text
    # Prose from the mocked JSON.
    assert "framework standardizes validation output" in final
    # Validated badge (validation.ok == True).
    assert "validated" in final
    assert "✅" in final

    # Tainted artifact saved with the markdown content.
    conn = connect()
    try:
        artifact_rows = conn.execute(
            "SELECT id, mime, tainted FROM artifacts "
            "WHERE created_by_job = ?", (jid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(artifact_rows) == 1
    assert artifact_rows[0]["tainted"] == 1

    # finalize -> outbox -> drainer.
    assert ctx.finalize() is True
    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        return_value={"ok": True, "ts": "1.0"},
    )
    await _drain_one(bot, job_id=jid, expected_channel="C_VAL2")

    bot.client.chat_postMessage.assert_awaited_once()
    sent = bot.client.chat_postMessage.await_args.kwargs
    assert sent["channel"] == "C_VAL2"
    assert "framework standardizes" in sent["text"]
    # Tainted output: unfurls disabled.
    assert sent["unfurl_links"] is False
    assert sent["unfurl_media"] is False


# ---------- 9. target_channel_id resolver wired through to drainer -------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_legacy_task_schedule_drainer_posts_to_target_channel_id() -> None:
    """v0.6.3 end-to-end (V60-6): a legacy kind='task' schedule with
    target_channel_id="C_NEW" but a thread pointing to C_OLD must get
    its delivery routed to C_NEW via the canonical resolver — proving
    the v0.6.3 fix is wired all the way through finalize -> outbox ->
    drainer, not just unit-level resolver behavior."""
    from donna.jobs.scheduler import Scheduler
    from donna.memory import schedules as sched_mod

    # Schedule with diverged channels (the half-wired bug).
    conn = connect()
    try:
        with transaction(conn):
            tid_old = threads_mod.get_or_create_thread(
                conn, channel_id="C_OLD", thread_external_id=None,
            )
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr="* * * * *",
                task="legacy task",
                mode="chat",
                thread_id=tid_old,
                target_channel_id="C_NEW",
                # kind defaults to 'task'
            )
            sched = dict(conn.execute(
                "SELECT * FROM schedules WHERE id = ?", (sid,),
            ).fetchone())
    finally:
        conn.close()

    # Fire — legacy path inserts a job with schedule_id back-link.
    await Scheduler()._fire(sched)

    conn = connect()
    try:
        jobs_rows = conn.execute(
            "SELECT id, schedule_id, thread_id FROM jobs "
            "WHERE schedule_id = ?", (sid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(jobs_rows) == 1
    jid = jobs_rows[0]["id"]
    assert jobs_rows[0]["schedule_id"] == sid
    assert jobs_rows[0]["thread_id"] == tid_old

    # Resolver alone: must prefer schedule.target_channel_id over thread.
    bot = _build_bot_no_app()
    resolved = await bot._resolve_channel_for_job(jid)
    assert resolved == "C_NEW", (
        f"resolver returned {resolved!r}, not C_NEW — v0.6.3 regressed"
    )
    assert resolved != "C_OLD"

    # Now drive the full path: finalize, then drain.
    _claim_lease(jid)
    job = _load(jid)
    ctx = JobContext(job, worker_id="integration-worker")
    ctx.state.final_text = "scheduled output should land in C_NEW"
    ctx.state.done = True
    assert ctx.finalize() is True

    bot.client.chat_postMessage = AsyncMock(
        return_value={"ok": True, "ts": "1.0"},
    )
    await _drain_one(bot, job_id=jid, expected_channel="C_NEW")

    bot.client.chat_postMessage.assert_awaited_once()
    sent_kwargs = bot.client.chat_postMessage.await_args.kwargs
    assert sent_kwargs["channel"] == "C_NEW"
    assert sent_kwargs["channel"] != "C_OLD"
