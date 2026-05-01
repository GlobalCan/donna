"""V50-1: outbox drainer routes terminal/unknown failures to dead-letter
table; transient failures bump attempt_count and stay; rate_limited with
Retry-After triggers a per-channel cool-down.

Tests the routing helper `_handle_update_result` directly (pure logic over
DB state) plus an end-to-end check that `_post_update` translates
SlackApiError into a classified PostResult.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from donna.adapter.slack_adapter import DonnaSlackBot, PostResult
from donna.adapter.slack_errors import ErrorClass
from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction

# ---------- helpers -------------------------------------------------------


class _FakeResponse:
    def __init__(self, data: dict | None = None, headers: dict | None = None):
        self.data = data
        self.headers = headers


def _slack_error(code: str, headers: dict | None = None) -> SlackApiError:
    return SlackApiError(
        message=f"slack failure: {code}",
        response=_FakeResponse(
            data={"ok": False, "error": code}, headers=headers,
        ),
    )


def _make_job(task: str = "t") -> str:
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(conn, task=task)
    finally:
        conn.close()
    return jid


def _enqueue_outbox_row(
    *, job_id: str, text: str = "hi", tainted: int = 0,
    attempt_count: int = 0,
) -> str:
    """Insert directly into outbox_updates and return the row id."""
    import uuid

    row_id = f"out_{uuid.uuid4().hex[:12]}"
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO outbox_updates "
                "(id, job_id, text, tainted, created_at, attempt_count) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
                (row_id, job_id, text, tainted, attempt_count),
            )
    finally:
        conn.close()
    return row_id


def _build_bot_no_app() -> DonnaSlackBot:
    """Construct a bot without going through __init__ (which connects to
    Slack). We only need the methods + state maps for routing tests."""
    bot = DonnaSlackBot.__new__(DonnaSlackBot)
    bot._last_sent_per_channel = {}
    bot._rate_limited_until = {}
    bot.client = MagicMock()
    return bot


def _select_outbox_row(row_id: str):
    conn = connect()
    try:
        return conn.execute(
            "SELECT id, attempt_count, last_error, last_attempt_at "
            "FROM outbox_updates WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()


def _select_dead_letter_for(source_id: str):
    conn = connect()
    try:
        return conn.execute(
            "SELECT * FROM outbox_dead_letter WHERE source_id = ?",
            (source_id,),
        ).fetchone()
    finally:
        conn.close()


# ---------- _handle_update_result routing --------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_terminal_error_moves_row_to_dead_letter() -> None:
    """V50-1: not_in_channel, channel_not_found, etc. drop the row out of
    outbox_updates and capture full provenance in outbox_dead_letter."""
    jid = _make_job()
    row_id = _enqueue_outbox_row(job_id=jid, text="undeliverable")

    bot = _build_bot_no_app()
    last_sent: dict[str, float] = {}
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    bot._handle_update_result(
        row=row,
        channel="C_DEAD",
        thread_ts=None,
        result=PostResult(
            ok=False,
            error_code="not_in_channel",
            error_class=ErrorClass.TERMINAL,
            error_msg="not_in_channel",
        ),
        last_sent_per_job=last_sent,
    )

    # Source row gone, dead-letter row present with full provenance.
    assert _select_outbox_row(row_id) is None
    dl = _select_dead_letter_for(row_id)
    assert dl is not None
    assert dl["source_table"] == "outbox_updates"
    assert dl["job_id"] == jid
    assert dl["channel_id"] == "C_DEAD"
    assert dl["payload"] == "undeliverable"
    assert dl["error_code"] == "not_in_channel"
    assert dl["error_class"] == "terminal"
    assert dl["attempt_count"] == 1


@pytest.mark.usefixtures("fresh_db")
def test_unknown_error_moves_row_to_dead_letter() -> None:
    """V50-1: a never-seen-before error code goes to dead-letter so the
    operator decides classification rather than the drainer guessing."""
    jid = _make_job()
    row_id = _enqueue_outbox_row(job_id=jid)
    bot = _build_bot_no_app()

    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    bot._handle_update_result(
        row=row,
        channel="C_X",
        thread_ts=None,
        result=PostResult(
            ok=False,
            error_code="a_new_slack_error",
            error_class=ErrorClass.UNKNOWN,
        ),
        last_sent_per_job={},
    )

    assert _select_outbox_row(row_id) is None
    dl = _select_dead_letter_for(row_id)
    assert dl is not None
    assert dl["error_class"] == "unknown"
    assert dl["error_code"] == "a_new_slack_error"


@pytest.mark.usefixtures("fresh_db")
def test_transient_error_keeps_row_and_bumps_attempt_count() -> None:
    """V50-1: rate_limited / server_error leave the row in place for the
    next drain tick; attempt_count + last_error become operator-visible."""
    jid = _make_job()
    row_id = _enqueue_outbox_row(job_id=jid)
    bot = _build_bot_no_app()

    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    bot._handle_update_result(
        row=row,
        channel="C_OK",
        thread_ts=None,
        result=PostResult(
            ok=False,
            error_code="rate_limited",
            error_class=ErrorClass.TRANSIENT,
            retry_after_s=None,
        ),
        last_sent_per_job={},
    )

    persisted = _select_outbox_row(row_id)
    assert persisted is not None
    assert persisted["attempt_count"] == 1
    assert persisted["last_error"] == "rate_limited"
    assert persisted["last_attempt_at"] is not None
    # Nothing in dead-letter
    assert _select_dead_letter_for(row_id) is None


@pytest.mark.usefixtures("fresh_db")
def test_transient_with_retry_after_sets_per_channel_cool_down() -> None:
    """V50-1: when Slack returns rate_limited with Retry-After, the drainer
    must respect that interval before posting to the same channel again,
    not just the soft 1.2s pacing gate."""
    jid = _make_job()
    row_id = _enqueue_outbox_row(job_id=jid)
    bot = _build_bot_no_app()

    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    before = time.time()
    bot._handle_update_result(
        row=row,
        channel="C_THROTTLED",
        thread_ts=None,
        result=PostResult(
            ok=False,
            error_code="rate_limited",
            error_class=ErrorClass.TRANSIENT,
            retry_after_s=30.0,
        ),
        last_sent_per_job={},
    )
    after = time.time()

    until = bot._rate_limited_until.get("C_THROTTLED")
    assert until is not None
    # Cool-down is at least the Retry-After duration after the attempt
    # (allow 1s slack on each side for clock drift / test-machine load).
    assert before + 29.0 <= until <= after + 31.0


@pytest.mark.usefixtures("fresh_db")
def test_transient_retry_after_clamped_to_5_minutes() -> None:
    """V50-1: a malicious / runaway Retry-After (like 86400s) shouldn't
    silently park the row for a day. The drainer caps the cool-down at
    300s so the supervisor can recover via restart instead."""
    jid = _make_job()
    row_id = _enqueue_outbox_row(job_id=jid)
    bot = _build_bot_no_app()

    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    before = time.time()
    bot._handle_update_result(
        row=row,
        channel="C_RUNAWAY",
        thread_ts=None,
        result=PostResult(
            ok=False,
            error_code="rate_limited",
            error_class=ErrorClass.TRANSIENT,
            retry_after_s=86400.0,
        ),
        last_sent_per_job={},
    )

    until = bot._rate_limited_until["C_RUNAWAY"]
    # Cap at 300s, not 86400.
    assert until <= before + 301.0


@pytest.mark.usefixtures("fresh_db")
def test_ok_result_deletes_row_and_records_per_channel_send_time() -> None:
    """Regression guard: the success path still works after the V50-1
    refactor — row gets deleted, last_sent_per_channel updated."""
    jid = _make_job()
    row_id = _enqueue_outbox_row(job_id=jid)
    bot = _build_bot_no_app()

    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, job_id, text, tainted, attempt_count, created_at "
            "FROM outbox_updates WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()

    last_sent: dict[str, float] = {}
    bot._handle_update_result(
        row=row,
        channel="C_OK",
        thread_ts=None,
        result=PostResult(ok=True),
        last_sent_per_job=last_sent,
    )

    assert _select_outbox_row(row_id) is None
    assert "C_OK" in bot._last_sent_per_channel
    assert jid in last_sent


# ---------- _post_update SlackApiError -> PostResult mapping -------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_post_update_maps_terminal_error() -> None:
    """V50-1: a SlackApiError with a known terminal code becomes a
    classified PostResult; the drainer can route on PostResult.error_class
    without re-parsing the exception."""
    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        side_effect=_slack_error("not_in_channel"),
    )

    result = await bot._post_update(
        channel="C_X", job_id="job_x", thread_ts=None,
        text="hello", tainted=False,
    )
    assert result.ok is False
    assert result.error_code == "not_in_channel"
    assert result.error_class is ErrorClass.TERMINAL
    assert result.retry_after_s is None
    assert result.error_msg


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_post_update_maps_rate_limited_with_retry_after() -> None:
    """V50-1: rate_limited carries Retry-After through the PostResult so
    the drainer can apply a per-channel cool-down."""
    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        side_effect=_slack_error("rate_limited", headers={"Retry-After": "12"}),
    )
    result = await bot._post_update(
        channel="C_X", job_id="job_x", thread_ts=None,
        text="hello", tainted=False,
    )
    assert result.ok is False
    assert result.error_class is ErrorClass.TRANSIENT
    assert result.retry_after_s == 12.0


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_post_update_maps_non_slack_exception_to_unknown() -> None:
    """Network errors etc. are SDK-wrapped as plain Exception, not
    SlackApiError. The drainer treats these as unknown so the row gets
    moved to dead-letter rather than spinning."""
    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        side_effect=ConnectionError("dns down"),
    )
    result = await bot._post_update(
        channel="C_X", job_id="job_x", thread_ts=None,
        text="hello", tainted=False,
    )
    assert result.ok is False
    assert result.error_class is ErrorClass.UNKNOWN
    assert result.error_code is None
    assert "dns down" in (result.error_msg or "")


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_post_update_success_returns_ok() -> None:
    """Sanity: success path still returns PostResult(ok=True)."""
    bot = _build_bot_no_app()
    bot.client.chat_postMessage = AsyncMock(
        return_value={"ok": True, "ts": "1234.5678"},
    )
    result = await bot._post_update(
        channel="C_X", job_id="job_x", thread_ts=None,
        text="hello", tainted=False,
    )
    assert result.ok is True
    assert result.error_code is None
