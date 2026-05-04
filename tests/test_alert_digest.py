"""Alert digest — v0.7.3 / Track A.3 / Codex #11 (operator fatigue).

When `DONNA_ALERT_DIGEST_INTERVAL_MIN > 0`, alert producers
(`BudgetWatcher`, `Watchdog`, `_maybe_alert_operator`) route through
`alert_digest.route_alert` which queues rows in `alert_digest_queue`.
A background flusher batches due rows into one merged DM per cadence.

Default `interval_min = 0` keeps the legacy immediate-DM behavior.

These tests cover:

- Schema shape (alert_digest_queue exists, expected columns)
- route_alert: immediate path when interval = 0
- route_alert: enqueue path when interval > 0
- flush_due_now: dedup by `dedup_key` collapses N→1 line
- flush_due_now: rows newer than cutoff are NOT delivered
- render_digest: severity prefixes + count formatting
- backwards-compat: legacy notifier semantics preserved when interval=0
- queued_count helper for botctl + slash commands
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from donna.config import settings
from donna.memory.db import connect
from donna.observability import alert_digest as ad_mod
from donna.observability.alert_digest import (
    DigestRow,
    flush_due_now,
    queued_count,
    render_digest,
    route_alert,
)

# ---------- schema --------------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_alert_digest_queue_table_exists() -> None:
    """0014 must have created the alert_digest_queue table with the
    expected column shape."""
    conn = connect()
    try:
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(alert_digest_queue)"
        ).fetchall()}
    finally:
        conn.close()
    assert cols >= {
        "id", "kind", "severity", "message", "dedup_key",
        "created_at", "delivered_at",
    }, f"missing alert_digest_queue columns: {cols}"


@pytest.mark.usefixtures("fresh_db")
def test_pending_index_exists_for_flusher() -> None:
    """The flusher's hot-path query filters by delivered_at IS NULL +
    created_at; we need a partial index to keep that fast."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND tbl_name = 'alert_digest_queue'"
        ).fetchall()
    finally:
        conn.close()
    names = {r["name"] for r in rows}
    assert "ix_alert_digest_pending" in names


# ---------- route_alert immediate path -----------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_route_alert_immediate_when_interval_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default behavior (interval = 0): DM immediately via notifier,
    queue stays empty."""
    s = settings()
    monkeypatch.setattr(s, "alert_digest_interval_min", 0)
    delivered: list[str] = []

    async def fake_notifier(msg: str) -> None:
        delivered.append(msg)

    await route_alert(
        fake_notifier,
        kind="budget", message="hello",
        dedup_key="budget:5", severity="warning",
    )
    assert delivered == ["hello"]
    assert queued_count() == 0


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_route_alert_enqueues_when_interval_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = settings()
    monkeypatch.setattr(s, "alert_digest_interval_min", 30)
    delivered: list[str] = []

    async def fake_notifier(msg: str) -> None:
        delivered.append(msg)

    await route_alert(
        fake_notifier,
        kind="budget", message="hello",
        dedup_key="budget:5", severity="warning",
    )
    # Must NOT have DM'd; it's queued for the digest.
    assert delivered == []
    assert queued_count() == 1
    conn = connect()
    try:
        row = conn.execute(
            "SELECT kind, severity, message, dedup_key, delivered_at "
            "FROM alert_digest_queue"
        ).fetchone()
    finally:
        conn.close()
    assert row["kind"] == "budget"
    assert row["severity"] == "warning"
    assert row["message"] == "hello"
    assert row["dedup_key"] == "budget:5"
    assert row["delivered_at"] is None


# ---------- flush_due_now -------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_flush_due_now_returns_zero_on_empty_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings(), "alert_digest_interval_min", 30)
    delivered: list[str] = []

    async def fake_notifier(msg: str) -> None:
        delivered.append(msg)

    n = await flush_due_now(fake_notifier)
    assert n == 0
    assert delivered == []


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_flush_due_now_skips_rows_inside_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows whose created_at is newer than (now - interval_min) must
    stay queued — they're not yet ready for digest."""
    monkeypatch.setattr(settings(), "alert_digest_interval_min", 30)
    delivered: list[str] = []

    async def fake_notifier(msg: str) -> None:
        delivered.append(msg)

    await route_alert(
        fake_notifier, kind="budget", message="recent",
        dedup_key=None, severity="info",
    )
    # interval_min=30 means rows must be >= 30 min old to flush
    n = await flush_due_now(fake_notifier)
    assert n == 0
    assert queued_count() == 1


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_flush_due_now_with_zero_interval_drains_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`flush_due_now(interval_min=0)` is the manual-flush path used by
    botctl — it should drain the queue regardless of row age."""
    monkeypatch.setattr(settings(), "alert_digest_interval_min", 30)
    delivered: list[str] = []

    async def fake_notifier(msg: str) -> None:
        delivered.append(msg)

    for i in range(3):
        await route_alert(
            fake_notifier, kind="budget", message=f"alert-{i}",
            dedup_key=None, severity="info",
        )
    n = await flush_due_now(fake_notifier, interval_min=0)
    assert n == 3
    assert len(delivered) == 1, "all 3 alerts should batch into 1 DM"
    body = delivered[0]
    assert "alert-0" in body and "alert-1" in body and "alert-2" in body
    assert queued_count() == 0


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_flush_due_now_dedup_collapses_same_key_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """50 dead-letter rows for the same channel collapse into one
    `(50x) ...` line in the digest body."""
    monkeypatch.setattr(settings(), "alert_digest_interval_min", 30)
    delivered: list[str] = []

    async def fake_notifier(msg: str) -> None:
        delivered.append(msg)

    for i in range(50):
        await route_alert(
            fake_notifier, kind="delivery_failure",
            message=f"channel C012 dead-lettered ({i})",
            dedup_key="delivery_failure:C012:not_in_channel",
            severity="error",
        )
    n = await flush_due_now(fake_notifier, interval_min=0)
    assert n == 50
    body = delivered[0]
    assert "(50x)" in body
    # The most recent message text wins.
    assert "channel C012 dead-lettered (49)" in body
    # The collapsed digest body should be one line for the 50 rows
    # (plus the header), not 50.
    assert body.count("\n") <= 2


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_flush_marks_rows_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings(), "alert_digest_interval_min", 30)
    delivered: list[str] = []

    async def fake_notifier(msg: str) -> None:
        delivered.append(msg)

    await route_alert(
        fake_notifier, kind="budget", message="x",
        dedup_key=None, severity="info",
    )
    await flush_due_now(fake_notifier, interval_min=0)
    # After flush: queue is empty (delivered_at set on every flushed row)
    assert queued_count() == 0
    conn = connect()
    try:
        row = conn.execute(
            "SELECT delivered_at FROM alert_digest_queue"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row["delivered_at"] is not None


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_flush_failure_keeps_rows_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the notifier raises, no rows should be marked delivered. Next
    flush retries — alerts must not be silently lost."""
    monkeypatch.setattr(settings(), "alert_digest_interval_min", 30)

    async def boom_notifier(msg: str) -> None:
        raise RuntimeError("DM channel busted")

    queued: list[str] = []

    async def queue_only(msg: str) -> None:
        queued.append(msg)

    await route_alert(
        queue_only, kind="budget", message="x",
        dedup_key=None, severity="warning",
    )
    n = await flush_due_now(boom_notifier, interval_min=0)
    assert n == 0
    # Row stays pending so the next flush retries
    assert queued_count() == 1


# ---------- render_digest -------------------------------------------------


def test_render_digest_severity_prefixes() -> None:
    base = datetime.now(UTC)
    rows = [
        DigestRow(
            id="aq_1", kind="budget", severity="info",
            message="under threshold", dedup_key=None,
            created_at=base - timedelta(minutes=3),
        ),
        DigestRow(
            id="aq_2", kind="recent_failures", severity="error",
            message="3 jobs failed", dedup_key=None,
            created_at=base - timedelta(minutes=2),
        ),
        DigestRow(
            id="aq_3", kind="stuck_consent", severity="warning",
            message="job paused 1h", dedup_key=None,
            created_at=base - timedelta(minutes=1),
        ),
    ]
    body = render_digest(rows)
    assert "Donna alert digest" in body
    assert "3 alert(s)" in body
    assert "ℹ️ under threshold" in body
    assert "❗ 3 jobs failed" in body
    assert "⚠️ job paused 1h" in body


def test_render_digest_oldest_first() -> None:
    """Rendering preserves chronological order so the operator reads
    the timeline naturally top-down."""
    base = datetime.now(UTC)
    rows = [
        DigestRow(
            id="a", kind="x", severity="info",
            message="newest", dedup_key=None,
            created_at=base,
        ),
        DigestRow(
            id="b", kind="x", severity="info",
            message="oldest", dedup_key=None,
            created_at=base - timedelta(hours=1),
        ),
    ]
    body = render_digest(rows)
    oldest_idx = body.find("oldest")
    newest_idx = body.find("newest")
    assert 0 < oldest_idx < newest_idx


def test_render_digest_dedups_by_key() -> None:
    base = datetime.now(UTC)
    rows = [
        DigestRow(
            id="a", kind="x", severity="error",
            message="err 1", dedup_key="grp",
            created_at=base - timedelta(minutes=2),
        ),
        DigestRow(
            id="b", kind="x", severity="error",
            message="err 2", dedup_key="grp",
            created_at=base - timedelta(minutes=1),
        ),
        DigestRow(
            id="c", kind="x", severity="error",
            message="err 3 (latest)", dedup_key="grp",
            created_at=base,
        ),
    ]
    body = render_digest(rows)
    assert "(3x)" in body
    assert "err 3 (latest)" in body
    assert "err 1" not in body and "err 2" not in body


# ---------- queued_count + is_enabled helpers ----------------------------


@pytest.mark.usefixtures("fresh_db")
def test_queued_count_only_undelivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings(), "alert_digest_interval_min", 30)
    # Manually insert a delivered + pending row to verify the filter
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO alert_digest_queue "
            "(id, kind, severity, message, dedup_key) "
            "VALUES ('a', 'k', 'info', 'pending', NULL)",
        )
        conn.execute(
            "INSERT INTO alert_digest_queue "
            "(id, kind, severity, message, dedup_key, delivered_at) "
            "VALUES ('b', 'k', 'info', 'gone', NULL, CURRENT_TIMESTAMP)",
        )
    finally:
        conn.close()
    assert queued_count() == 1


@pytest.mark.usefixtures("fresh_db")
def test_is_enabled_reads_live_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`is_enabled` reads at call time so /donna_alert_settings can
    flip behavior without a process restart."""
    s = settings()
    monkeypatch.setattr(s, "alert_digest_interval_min", 0)
    assert ad_mod.is_enabled() is False
    monkeypatch.setattr(s, "alert_digest_interval_min", 30)
    assert ad_mod.is_enabled() is True
