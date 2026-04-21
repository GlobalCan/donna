"""Thread + message primitives."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import ids


def get_or_create_thread(
    conn: sqlite3.Connection, *, discord_channel: str | None, discord_thread: str | None, title: str | None = None
) -> str:
    if discord_thread:
        row = conn.execute(
            "SELECT id FROM threads WHERE discord_thread = ?", (discord_thread,)
        ).fetchone()
        if row:
            _touch(conn, row["id"])
            return row["id"]
    if discord_channel:
        row = conn.execute(
            "SELECT id FROM threads WHERE discord_channel = ? AND discord_thread IS NULL",
            (discord_channel,),
        ).fetchone()
        if row:
            _touch(conn, row["id"])
            return row["id"]
    tid = ids.thread_id()
    conn.execute(
        "INSERT INTO threads (id, discord_channel, discord_thread, title) VALUES (?, ?, ?, ?)",
        (tid, discord_channel, discord_thread, title),
    )
    return tid


def _touch(conn: sqlite3.Connection, thread_id: str) -> None:
    conn.execute(
        "UPDATE threads SET last_active_at = ? WHERE id = ?",
        (datetime.now(timezone.utc), thread_id),
    )


def insert_message(
    conn: sqlite3.Connection, *, thread_id: str, role: str, content: str, discord_msg: str | None = None
) -> str:
    mid = ids.message_id()
    conn.execute(
        "INSERT INTO messages (id, thread_id, role, content, discord_msg) VALUES (?, ?, ?, ?, ?)",
        (mid, thread_id, role, content, discord_msg),
    )
    return mid


def recent_messages(conn: sqlite3.Connection, thread_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content, created_at FROM messages WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
        (thread_id, limit),
    ).fetchall()
    return list(reversed([dict(r) for r in rows]))


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


def find_by_discord_channel(
    conn: sqlite3.Connection, *, channel_id: str,
) -> str | None:
    """Return the thread_id whose discord_channel (or discord_thread) matches."""
    row = conn.execute(
        """
        SELECT id FROM threads
        WHERE discord_channel = ? OR discord_thread = ?
        ORDER BY last_active_at DESC LIMIT 1
        """,
        (channel_id, channel_id),
    ).fetchone()
    return row["id"] if row else None
