"""Watchdog: stuck-job alerting + dedupe + failure-tolerant notifier.

Codex review #13 added this because "Phoenix is a debugger, not an ops
story" — you need to find out the bot's wedged BEFORE you notice it's
silent for hours. Pinning the three checks + the 12h dedupe + the
notifier-failure tolerance:

1. `_check_stuck_consent`  — alerts jobs in PAUSED_AWAITING_CONSENT >1h
2. `_check_stuck_running`  — alerts jobs in RUNNING >30m
3. `_check_recent_failures` — alerts when ≥3 jobs failed in the last hour

All three dedupe via an in-memory `(kind, id) → last_alerted_at` map
with a 12h window, so you get one DM per stuck event rather than one
every tick.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction
from donna.observability.watchdog import Watchdog


class _Collector:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, msg: str) -> None:
        self.messages.append(msg)


async def _noop(_msg: str) -> None:
    return None


def _insert_job_with_state(
    *, status: str, task: str = "t",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> str:
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(conn, task=task)
            # Direct UPDATE bypasses claim logic so we can fabricate
            # state/timing for the watchdog checks
            if started_at and finished_at:
                conn.execute(
                    "UPDATE jobs SET status = ?, started_at = ?, "
                    "finished_at = ? WHERE id = ?",
                    (status, started_at, finished_at, jid),
                )
            elif started_at:
                conn.execute(
                    "UPDATE jobs SET status = ?, started_at = ? WHERE id = ?",
                    (status, started_at, jid),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status = ? WHERE id = ?", (status, jid),
                )
    finally:
        conn.close()
    return jid


# ---------- stuck-consent ---------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_stuck_consent_over_1h_alerts() -> None:
    _insert_job_with_state(
        status="paused_awaiting_consent", task="needs consent",
        started_at=datetime.now(UTC) - timedelta(hours=2),
    )
    bot = _Collector()
    await Watchdog(bot).tick()
    assert len(bot.messages) == 1
    assert "waiting for consent" in bot.messages[0]
    assert "needs consent" in bot.messages[0]


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_stuck_consent_under_1h_silent() -> None:
    _insert_job_with_state(
        status="paused_awaiting_consent",
        started_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    bot = _Collector()
    await Watchdog(bot).tick()
    # No consent alert (30min < 1h cutoff)
    assert not any("consent" in m for m in bot.messages)


# ---------- stuck-running ---------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_stuck_running_over_30m_alerts() -> None:
    _insert_job_with_state(
        status="running", task="wedged task",
        started_at=datetime.now(UTC) - timedelta(minutes=45),
    )
    bot = _Collector()
    await Watchdog(bot).tick()
    assert len(bot.messages) == 1
    assert "running" in bot.messages[0].lower()
    assert "wedged task" in bot.messages[0]


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_stuck_running_under_30m_silent() -> None:
    _insert_job_with_state(
        status="running",
        started_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    bot = _Collector()
    await Watchdog(bot).tick()
    assert bot.messages == []


# ---------- recent failures ---------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_3_recent_failures_alerts() -> None:
    now = datetime.now(UTC)
    for i in range(3):
        _insert_job_with_state(
            status="failed", task=f"fail-{i}",
            started_at=now - timedelta(minutes=30 + i),
            finished_at=now - timedelta(minutes=15),
        )
    bot = _Collector()
    await Watchdog(bot).tick()
    assert any("3 jobs have failed" in m for m in bot.messages)


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_2_recent_failures_silent() -> None:
    """Threshold is >=3. 2 failures should NOT alert — transient
    stuff that'll probably self-heal."""
    now = datetime.now(UTC)
    for _ in range(2):
        _insert_job_with_state(
            status="failed",
            started_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=10),
        )
    bot = _Collector()
    await Watchdog(bot).tick()
    assert not any("jobs have failed" in m for m in bot.messages)


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_old_failures_outside_1h_window_excluded() -> None:
    now = datetime.now(UTC)
    # 3 failures but all finished > 1h ago
    for _ in range(3):
        _insert_job_with_state(
            status="failed",
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=2),
        )
    bot = _Collector()
    await Watchdog(bot).tick()
    assert not any("jobs have failed" in m for m in bot.messages)


# ---------- dedupe -------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_same_stuck_job_alerted_once_within_12h() -> None:
    """Dedupe is the difference between 'one nudge' and 'noise at 5-min
    cadence'. Without it, every tick for 2h = 24 duplicate DMs."""
    _insert_job_with_state(
        status="running",
        started_at=datetime.now(UTC) - timedelta(hours=2),
    )
    bot = _Collector()
    wd = Watchdog(bot)
    await wd.tick()
    await wd.tick()
    await wd.tick()
    assert len(bot.messages) == 1, (
        f"expected 1 alert across 3 ticks, got {len(bot.messages)}: {bot.messages}"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_different_kinds_for_same_job_both_alert() -> None:
    """If a job hits two distinct watchdog kinds (somehow — rare), both
    should alert. Dedupe key is (kind, id), not id alone."""
    now = datetime.now(UTC)
    _insert_job_with_state(
        status="paused_awaiting_consent",
        started_at=now - timedelta(hours=2),
    )
    # Plus 3 failures for the recent-failures check
    for _ in range(3):
        _insert_job_with_state(
            status="failed",
            started_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=10),
        )
    bot = _Collector()
    await Watchdog(bot).tick()
    # Two distinct kinds of alert
    assert any("consent" in m for m in bot.messages)
    assert any("jobs have failed" in m for m in bot.messages)
    assert len(bot.messages) >= 2


# ---------- notifier failure tolerance ----------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_notifier_exception_does_not_crash_tick() -> None:
    """If the Discord DM fails (network, rate limit, whatever), the
    watchdog must NOT raise — otherwise a single DM blip would stop
    the entire check loop. Errors log; tick proceeds."""
    _insert_job_with_state(
        status="running",
        started_at=datetime.now(UTC) - timedelta(hours=1),
    )

    async def _boom(_msg: str) -> None:
        raise RuntimeError("Discord unavailable")

    wd = Watchdog(_boom)
    # Must NOT raise
    await wd.tick()


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_no_alerts_for_empty_db() -> None:
    bot = _Collector()
    await Watchdog(bot).tick()
    assert bot.messages == []
