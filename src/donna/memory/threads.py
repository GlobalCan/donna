"""Thread + message primitives.

v0.5.0 migration: column names are platform-agnostic.

  threads.channel_id         — Slack channel ID (C0...) for the DM/channel
  threads.thread_external_id — Slack thread parent `thread_ts` when in
                               a thread reply; None for top-level DM/channel
  messages.external_msg_id   — Slack message `ts` (string)
  messages.tainted           — taint flag (v0.4.4)

Slack `ts` values are strings ("1234567890.123456"), unlike Discord's
integer message IDs. Migration 0008 changed the affected outbox/consent
columns from INTEGER to TEXT to match.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from . import ids


def get_or_create_thread(
    conn: sqlite3.Connection,
    *,
    channel_id: str | None,
    thread_external_id: str | None,
    title: str | None = None,
) -> str:
    """Find an existing thread for this (channel_id, thread_external_id)
    pair, or create one.

    Slack `thread_ts` is only unique within a channel/conversation, so
    the lookup keys on the pair when thread_external_id is present.
    For plain DM (no thread_ts), match on channel_id alone with
    thread_external_id IS NULL.
    """
    if thread_external_id:
        row = conn.execute(
            "SELECT id FROM threads "
            "WHERE channel_id = ? AND thread_external_id = ?",
            (channel_id, thread_external_id),
        ).fetchone()
        if row:
            _touch(conn, row["id"])
            return row["id"]
    if channel_id:
        row = conn.execute(
            "SELECT id FROM threads WHERE channel_id = ? "
            "AND thread_external_id IS NULL",
            (channel_id,),
        ).fetchone()
        if row:
            _touch(conn, row["id"])
            return row["id"]
    tid = ids.thread_id()
    conn.execute(
        "INSERT INTO threads (id, channel_id, thread_external_id, title) "
        "VALUES (?, ?, ?, ?)",
        (tid, channel_id, thread_external_id, title),
    )
    return tid


def _touch(conn: sqlite3.Connection, thread_id: str) -> None:
    conn.execute(
        "UPDATE threads SET last_active_at = ? WHERE id = ?",
        (datetime.now(UTC), thread_id),
    )


def insert_message(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    role: str,
    content: str,
    external_msg_id: str | None = None,
    tainted: bool = False,
    safe_summary: str | None = None,
) -> str:
    """Insert a message row.

    `tainted` flags rows whose content was produced (or might have been
    influenced) by an untrusted source. v0.4.4: rows are rendered with
    an explicit untrusted-source wrapper. v0.5.2 (V50-8): tainted rows
    grow a `safe_summary` field — a sanitized paraphrase that reaches
    the model unwrapped. Decouples audit (raw `content`) from prompt
    rendering (laundered `safe_summary`).

    `safe_summary` is typically NULL at insert time and backfilled
    asynchronously via `update_safe_summary` after `JobContext.finalize`.
    Callers writing pre-sanitized content can pass it directly to skip
    the backfill round-trip.

    `external_msg_id` is the Slack message `ts` (string), kept for
    audit-trail / cross-reference.
    """
    mid = ids.message_id()
    conn.execute(
        "INSERT INTO messages "
        "(id, thread_id, role, content, external_msg_id, tainted, "
        "safe_summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            mid, thread_id, role, content, external_msg_id,
            1 if tainted else 0, safe_summary,
        ),
    )
    return mid


def update_safe_summary(
    conn: sqlite3.Connection, *, message_id: str, summary: str,
) -> bool:
    """Backfill `safe_summary` for an existing message row.

    Idempotency: only updates when safe_summary is currently NULL, so
    racing backfill attempts (e.g. retried tasks) don't overwrite each
    other. Returns True when the UPDATE actually ran (1 row affected).
    """
    cur = conn.execute(
        "UPDATE messages SET safe_summary = ? "
        "WHERE id = ? AND safe_summary IS NULL",
        (summary, message_id),
    )
    return cur.rowcount > 0


def recent_messages(
    conn: sqlite3.Connection, thread_id: str, limit: int = 20,
) -> list[dict]:
    """Return up to `limit` most-recent messages in chronological order.

    Each dict carries `tainted: bool` and `safe_summary: str | None`.
    `compose_system` renders tainted rows with safe_summary present as
    plain continuity context; tainted rows with safe_summary NULL fall
    back to the v0.4.4 wrapped-raw render.
    """
    rows = conn.execute(
        "SELECT role, content, created_at, tainted, safe_summary "
        "FROM messages "
        "WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
        (thread_id, limit),
    ).fetchall()
    out: list[dict] = []
    for r in reversed(list(rows)):
        d = dict(r)
        d["tainted"] = bool(d.get("tainted"))
        out.append(d)
    return out


# ---------- Tier override (powers /model command) ------------------------


def set_model_tier_override(
    conn: sqlite3.Connection, *, thread_id: str, tier: str | None,
) -> None:
    """Set (or clear with tier=None) the model tier override for a thread."""
    conn.execute(
        "UPDATE threads SET model_tier_override = ? WHERE id = ?",
        (tier, thread_id),
    )


def get_model_tier_override(
    conn: sqlite3.Connection, *, thread_id: str,
) -> str | None:
    row = conn.execute(
        "SELECT model_tier_override FROM threads WHERE id = ?", (thread_id,),
    ).fetchone()
    return row["model_tier_override"] if row else None


def find_by_channel(
    conn: sqlite3.Connection, *, channel_id: str,
) -> str | None:
    """Return the thread_id whose channel_id matches.

    Used by /model to bind a tier override to a Slack channel without
    needing to walk the thread/parent_ts dimension.
    """
    row = conn.execute(
        """
        SELECT id FROM threads
        WHERE channel_id = ?
        ORDER BY last_active_at DESC LIMIT 1
        """,
        (channel_id,),
    ).fetchone()
    return row["id"] if row else None
