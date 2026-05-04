"""Alert digest — queue-and-batch alerts to fight operator-DM noise.

Codex 2026-05-01 review item #11 ("operator fatigue"): pre-fix every
delivery dead-letter, budget threshold crossed, stuck-job watchdog
trip, and consent timeout fired its own DM. On a slow afternoon those
alerts could pile up to 5+ DMs in 10 minutes, and the operator started
muting the bot to escape the noise — the worst possible outcome for
infrastructure that's actually trying to surface problems.

Fix: opt-in alert digest. When `DONNA_ALERT_DIGEST_INTERVAL_MIN > 0`,
alerts are written to `alert_digest_queue` instead of DM'd immediately.
A background flusher wakes every minute, looks at rows older than the
configured interval, dedupes by `dedup_key`, and posts ONE merged DM.
If nothing is queued, no DM is sent.

Default `interval_min = 0` keeps the immediate-DM behavior so the
v0.7.x soak isn't disrupted; operators opt in via env var or the
`/donna_alert_settings <minutes>` slash command.

Module API:

  - `route_alert(notifier, *, kind, message, dedup_key, severity)`:
    The single entry point alert producers call. If the digest is
    disabled (interval = 0), it DMs immediately via `notifier`. If
    enabled, it enqueues a row and returns; the flusher delivers later.

  - `AlertDigestFlusher.loop(notifier)`: background task that runs
    forever, flushing due rows on a polling cadence.

  - `flush_due_now(notifier)`: for tests + manual `botctl alerts flush`.

Severity is rendered as a per-row prefix in the digest body so the
operator can scan a 10-line digest and spot the urgent ones quickly.

Dedup behavior: when the flusher finds N rows sharing a `dedup_key`
(e.g. 50 dead-letter rows for the same broken channel), it collapses
them into "(N×) <message>" rather than rendering 50 lines. The
in-memory throttle on `_maybe_alert_operator` is preserved as a
defense-in-depth so even if the digest is disabled, we don't post
duplicate DMs within the same hour.
"""
from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..config import settings
from ..logging import get_logger
from ..memory.db import connect, transaction

log = get_logger(__name__)


# Severity → display prefix mapping. Kept short so digest rendering
# doesn't bloat. `info` is the default for non-urgent ops chatter
# (e.g. budget thresholds well under cap); `error` for active
# incidents (channel broken, repeated failures).
SEVERITY_PREFIX: dict[str, str] = {
    "info": "ℹ️",
    "warning": "⚠️",
    "error": "❗",
}


@dataclass
class DigestRow:
    """One queued alert. Mirrors `alert_digest_queue` schema 1:1."""
    id: str
    kind: str
    severity: str
    message: str
    dedup_key: str | None
    created_at: datetime


def _interval_min() -> int:
    """Read interval at call time, not module load. Lets the runtime
    `/donna_alert_settings` command flip behavior without restarting."""
    s = settings()
    return max(0, int(s.alert_digest_interval_min))


def is_enabled() -> bool:
    """Convenience boolean for callers that want to log/branch."""
    return _interval_min() > 0


# ---------- producer-side: route_alert -----------------------------------


async def route_alert(
    notifier: Callable[[str], Awaitable[None]],
    *,
    kind: str,
    message: str,
    dedup_key: str | None = None,
    severity: str = "warning",
) -> bool:
    """The one entry point alert producers should call.

    Returns True if the alert was successfully delivered (or successfully
    enqueued for later delivery), False if both immediate-DM AND enqueue
    paths failed. Callers that maintain an in-memory throttle (e.g.
    `_maybe_alert_operator`'s `_alert_throttle` map) should only update
    the throttle on True so a fully-failed alert is retried on the next
    attempt.

    - kind: short stable label (e.g. 'delivery_failure', 'budget',
      'stuck_consent', 'consent_timeout', 'stuck_running',
      'recent_failures'). Used for filtering / observability only.
    - message: pre-rendered single-line description that will end up
      in the DM verbatim. No further formatting applied.
    - dedup_key: optional. When the digest is enabled and multiple rows
      share a dedup_key, the flusher collapses them into one bulleted
      line prefixed with `(Nx)` instead of N lines. None = always
      individual.
    - severity: 'info' | 'warning' | 'error'. Rendered as a per-row
      prefix in the digest body.

    Behavior:
      - When the digest is disabled (interval = 0), DM immediately via
        `notifier` (legacy v0.7.2 behavior). Returns False on failure
        so callers can leave their throttle map untouched and retry
        later.
      - When enabled, enqueue a row and return True. The flusher
        delivers it later in a merged DM. If enqueue itself fails (DB
        pressure), we fall back to immediate DM so alerts aren't lost
        and pass that fallback's success status back to the caller.
    """
    if not is_enabled():
        try:
            await notifier(message)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "alert.route.notify_failed",
                kind=kind, error=str(e),
            )
            return False
        return True
    try:
        _enqueue(
            kind=kind, severity=severity,
            message=message, dedup_key=dedup_key,
        )
        log.debug(
            "alert.route.queued",
            kind=kind, severity=severity, dedup_key=dedup_key,
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.warning(
            "alert.route.enqueue_failed",
            kind=kind, error=str(e),
        )
        # Fallback: don't lose the alert when the queue is broken.
        try:
            await notifier(message)
            return True
        except Exception as e2:  # noqa: BLE001
            log.warning(
                "alert.route.fallback_notify_failed",
                kind=kind, error=str(e2),
            )
            return False


# ---------- DB ops -------------------------------------------------------


def _enqueue(
    *, kind: str, severity: str, message: str, dedup_key: str | None,
) -> str:
    """Insert one alert row. Returns the new id (`aq_<hex12>`)."""
    aid = f"aq_{uuid.uuid4().hex[:12]}"
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO alert_digest_queue "
                "(id, kind, severity, message, dedup_key) "
                "VALUES (?, ?, ?, ?, ?)",
                (aid, kind, severity, message, dedup_key),
            )
    finally:
        conn.close()
    return aid


def _fetch_due(*, cutoff: datetime) -> list[DigestRow]:
    """Return undelivered rows whose `created_at <= cutoff`. Newest
    first by created_at — the digest body will reverse to oldest-first
    so the timeline reads naturally top-down.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, kind, severity, message, dedup_key, created_at "
            "FROM alert_digest_queue "
            "WHERE delivered_at IS NULL AND created_at <= ? "
            "ORDER BY created_at",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_digest(r) for r in rows]


def _row_to_digest(r: sqlite3.Row) -> DigestRow:
    ca = r["created_at"]
    if isinstance(ca, str):
        ca = datetime.fromisoformat(ca)
    if ca.tzinfo is None:
        ca = ca.replace(tzinfo=UTC)
    return DigestRow(
        id=r["id"],
        kind=r["kind"],
        severity=r["severity"],
        message=r["message"],
        dedup_key=r["dedup_key"],
        created_at=ca,
    )


def _mark_delivered(ids: list[str]) -> None:
    """Idempotent — re-marking already-delivered rows is a no-op."""
    if not ids:
        return
    conn = connect()
    try:
        with transaction(conn):
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE alert_digest_queue "
                f"SET delivered_at = CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders}) "
                f"  AND delivered_at IS NULL",
                ids,
            )
    finally:
        conn.close()


def queued_count() -> int:
    """Live count of pending (undelivered) alerts. Used by botctl
    diagnostics + the slash-command status response."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM alert_digest_queue "
            "WHERE delivered_at IS NULL"
        ).fetchone()
    finally:
        conn.close()
    return int(row["n"]) if row else 0


# ---------- flush --------------------------------------------------------


def render_digest(rows: list[DigestRow]) -> str:
    """Render N alert rows into one Slack-friendly DM body.

    - Sort rows by created_at ascending (oldest first).
    - Group by dedup_key: rows sharing a non-null key are folded into
      a single line prefixed with `(Nx)` showing the most recent
      message text. Rows without a dedup_key remain individual.
    - Prefix each line with the severity emoji.
    """
    rows = sorted(rows, key=lambda r: r.created_at)
    by_key: dict[str | None, list[DigestRow]] = {}
    order: list[str | None] = []
    for r in rows:
        bucket = r.dedup_key  # None counts as its own bucket per row
        if bucket is None:
            # Use a unique sentinel so each None-key row stays standalone
            bucket = f"__none__{r.id}"
        if bucket not in by_key:
            by_key[bucket] = []
            order.append(bucket)
        by_key[bucket].append(r)

    lines: list[str] = [
        f"📬 *Donna alert digest* — {len(rows)} alert(s) since last check"
    ]
    for bucket in order:
        group = by_key[bucket]
        sev_marker = SEVERITY_PREFIX.get(group[-1].severity, "•")
        latest_msg = group[-1].message
        if len(group) > 1:
            # Show the count and the most recent occurrence text.
            lines.append(
                f"{sev_marker} ({len(group)}x) {latest_msg}"
            )
        else:
            lines.append(f"{sev_marker} {latest_msg}")
    return "\n".join(lines)


async def flush_due_now(
    notifier: Callable[[str], Awaitable[None]],
    *,
    interval_min: int | None = None,
) -> int:
    """Flush every queued alert older than the digest interval into one
    DM. Returns the count of rows delivered (0 if nothing was due).

    If `interval_min` is None, reads the live setting. Pass an explicit
    value in tests to force a flush regardless of clock state.
    """
    eff_interval = (
        _interval_min() if interval_min is None else int(interval_min)
    )
    # interval_min == 0 means "digest disabled", but flush_due_now is
    # also called manually via botctl. In that case, treat it as "flush
    # everything currently queued."
    if eff_interval <= 0:
        cutoff = datetime.now(UTC)
    else:
        cutoff = datetime.now(UTC) - timedelta(minutes=eff_interval)
    rows = _fetch_due(cutoff=cutoff)
    if not rows:
        return 0
    body = render_digest(rows)
    try:
        await notifier(body)
    except Exception as e:  # noqa: BLE001
        log.warning("alert.flush.notify_failed", error=str(e))
        # Don't mark as delivered — the next flush retries.
        return 0
    _mark_delivered([r.id for r in rows])
    log.info(
        "alert.flush.delivered",
        count=len(rows), interval_min=eff_interval,
    )
    return len(rows)


class AlertDigestFlusher:
    """Long-running task: flush queued alerts on a polling cadence.

    The polling loop runs every `poll_seconds` (default 60). On each
    tick it calls `flush_due_now(notifier)` — which is a no-op when
    nothing is currently due. This means:

    - Digest interval = 5 min: alerts may be delivered 5–6 min after
      they're queued (poll lag).
    - Digest interval = 30 min (recommended): same logic. The first
      alert in a quiet period waits ~30 min; bursty alerts within the
      same window batch into one DM.
    """

    def __init__(self, notifier: Callable[[str], Awaitable[None]]):
        self.notifier = notifier

    async def loop(self, *, poll_seconds: int = 60) -> None:
        while True:
            try:
                if is_enabled():
                    await flush_due_now(self.notifier)
            except Exception as e:  # noqa: BLE001
                log.exception("alert.flush.tick_failed", error=str(e))
            await asyncio.sleep(poll_seconds)
