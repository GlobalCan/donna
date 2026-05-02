"""V0.6 #7: cost runaway guard tests.

Validates the pure-logic CostStatus + the intake-side enforcement at
_enqueue_dm_task / _enqueue_slash_task. The actual Slack reply path
(_post_cost_cap_refusal) is exercised separately via mocked clients.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from donna.memory import cost as cost_mod
from donna.memory.db import connect, transaction
from donna.observability import cost_guard


def _record_cost(*, days_ago: int, usd: float) -> None:
    """Insert a cost_ledger row with a backdated created_at."""
    import uuid

    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO cost_ledger "
                "(id, model, kind, cost_usd, created_at) "
                "VALUES (?, ?, 'llm', ?, ?)",
                (
                    f"co_{uuid.uuid4().hex[:12]}", "test-model",
                    usd, datetime.now(UTC) - timedelta(days=days_ago),
                ),
            )
    finally:
        conn.close()


# ---------- CostStatus ---------------------------------------------------


def test_cost_status_not_blocked_when_below_caps() -> None:
    s = cost_guard.CostStatus(
        daily_spend=1.0, daily_cap=20.0,
        weekly_spend=5.0, weekly_cap=100.0,
    )
    assert s.blocked is False
    assert s.daily_blocked is False
    assert s.weekly_blocked is False
    assert s.reason() == ""


def test_cost_status_daily_block() -> None:
    s = cost_guard.CostStatus(
        daily_spend=25.0, daily_cap=20.0,
        weekly_spend=30.0, weekly_cap=100.0,
    )
    assert s.daily_blocked is True
    assert s.weekly_blocked is False
    assert s.blocked is True
    assert "daily spend $25.00" in s.reason()


def test_cost_status_weekly_block() -> None:
    s = cost_guard.CostStatus(
        daily_spend=1.0, daily_cap=20.0,
        weekly_spend=120.0, weekly_cap=100.0,
    )
    assert s.daily_blocked is False
    assert s.weekly_blocked is True
    assert s.blocked is True
    assert "7-day rolling spend $120.00" in s.reason()


def test_cost_status_both_blocked() -> None:
    s = cost_guard.CostStatus(
        daily_spend=25.0, daily_cap=20.0,
        weekly_spend=120.0, weekly_cap=100.0,
    )
    assert s.blocked is True
    assert "daily spend" in s.reason()
    assert "weekly spend" in s.reason()


def test_cost_status_zero_caps_disable_enforcement() -> None:
    """Setting cap=0 means 'no enforcement' — blocked stays False even
    if spend is huge."""
    s = cost_guard.CostStatus(
        daily_spend=1000.0, daily_cap=0.0,
        weekly_spend=10000.0, weekly_cap=0.0,
    )
    assert s.daily_blocked is False
    assert s.weekly_blocked is False
    assert s.blocked is False


# ---------- current_status reads from cost_ledger ----------------------


@pytest.mark.usefixtures("fresh_db")
def test_current_status_reads_actual_spend() -> None:
    _record_cost(days_ago=0, usd=5.50)
    _record_cost(days_ago=2, usd=3.25)
    _record_cost(days_ago=10, usd=99.99)  # outside 7-day window

    status = cost_guard.current_status()
    assert status.daily_spend == pytest.approx(5.50, abs=0.01)
    # Weekly = today + 2-day-ago = 8.75
    assert status.weekly_spend == pytest.approx(8.75, abs=0.01)


@pytest.mark.usefixtures("fresh_db")
def test_current_status_uses_settings_for_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DONNA_DAILY_HARD_CAP_USD", "7.50")
    monkeypatch.setenv("DONNA_WEEKLY_HARD_CAP_USD", "50")
    from donna import config as cfg
    cfg._settings = None  # force re-read

    status = cost_guard.current_status()
    assert status.daily_cap == 7.50
    assert status.weekly_cap == 50.0


@pytest.mark.usefixtures("fresh_db")
def test_is_intake_blocked_true_when_daily_cap_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DONNA_DAILY_HARD_CAP_USD", "5")
    from donna import config as cfg
    cfg._settings = None

    _record_cost(days_ago=0, usd=10.0)
    assert cost_guard.is_intake_blocked() is True


@pytest.mark.usefixtures("fresh_db")
def test_is_intake_blocked_false_when_below() -> None:
    _record_cost(days_ago=0, usd=2.0)
    assert cost_guard.is_intake_blocked() is False


# ---------- spend_this_week (cost.py addition) -------------------------


@pytest.mark.usefixtures("fresh_db")
def test_spend_this_week_includes_rolling_7_days() -> None:
    _record_cost(days_ago=0, usd=1.0)
    _record_cost(days_ago=3, usd=2.0)
    _record_cost(days_ago=6, usd=3.0)
    _record_cost(days_ago=8, usd=99.0)  # outside

    conn = connect()
    try:
        weekly = cost_mod.spend_this_week(conn)
    finally:
        conn.close()
    assert weekly == pytest.approx(6.0, abs=0.01)


# ---------- intake refusal (CostCapExceeded propagation) --------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_enqueue_dm_task_raises_when_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the cap is hit, _enqueue_dm_task raises CostCapExceeded
    instead of creating a job. Caller (handler) catches and posts
    refusal."""
    monkeypatch.setenv("DONNA_DAILY_HARD_CAP_USD", "1")
    from donna import config as cfg
    cfg._settings = None

    _record_cost(days_ago=0, usd=5.0)

    from donna.adapter.slack_ux import CostCapExceeded, _enqueue_dm_task
    with pytest.raises(CostCapExceeded) as exc_info:
        await _enqueue_dm_task(
            content="hi",
            channel_id="C_test",
            thread_ts=None,
            external_msg_id=None,
        )
    assert "daily spend" in exc_info.value.reason


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_enqueue_dm_task_works_when_below_cap() -> None:
    """Sanity: under the cap, _enqueue_dm_task creates a job normally."""
    from donna.adapter.slack_ux import _enqueue_dm_task

    _record_cost(days_ago=0, usd=1.0)  # below default 20.0 cap

    job_id = await _enqueue_dm_task(
        content="hello",
        channel_id="C_test",
        thread_ts=None,
        external_msg_id=None,
    )
    assert job_id.startswith("job_")
    conn = connect()
    try:
        row = conn.execute(
            "SELECT task FROM jobs WHERE id = ?", (job_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row["task"] == "hello"


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_enqueue_slash_task_raises_when_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DONNA_DAILY_HARD_CAP_USD", "1")
    from donna import config as cfg
    cfg._settings = None

    _record_cost(days_ago=0, usd=10.0)

    from donna.adapter.slack_ux import CostCapExceeded, _enqueue_slash_task
    from donna.types import JobMode
    with pytest.raises(CostCapExceeded):
        await _enqueue_slash_task(
            body={"channel_id": "C_test"},
            content="ask something",
            agent_scope="orchestrator",
            mode=JobMode.GROUNDED,
        )


# ---------- _post_cost_cap_refusal posts polite reply ----------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_post_cost_cap_refusal_sends_explanation() -> None:
    from unittest.mock import AsyncMock

    from donna.adapter.slack_ux import _post_cost_cap_refusal

    client = AsyncMock()
    await _post_cost_cap_refusal(
        client, channel_id="C_test", thread_ts="123.456",
        reason="daily spend $25.00 >= cap $20.00",
    )
    client.chat_postMessage.assert_awaited_once()
    call = client.chat_postMessage.call_args.kwargs
    assert call["channel"] == "C_test"
    assert call["thread_ts"] == "123.456"
    text = call["text"]
    assert "cost cap is engaged" in text
    assert "daily spend $25.00" in text
    # Operator hint to raise the cap is included
    assert "DONNA_DAILY_HARD_CAP_USD" in text
