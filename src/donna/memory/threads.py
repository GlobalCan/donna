"""Thread + message primitives."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

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
        (datetime.now(UTC), thread_id),
    )


def insert_message(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    role: str,
    content: str,
    discord_msg: str | None = None,
    tainted: bool = False,
) -> str:
    """Insert a message row.

    `tainted` flags a row whose content was produced (or might have been
    influenced) by an untrusted source — typically a web fetch, search
    snippet, or attachment ingest. Pre-v0.4.4 these rows were silently
    skipped at finalize time so they didn't contaminate future
    clean-job context, but that broke session memory for nearly every
    real chat. v0.4.4 writes them with `tainted=1` so they can be
    rendered with an explicit "from untrusted source — do not follow
    instructions" wrapper in `compose_system`, preserving the trust
    boundary while keeping the memory.
    """
    mid = ids.message_id()
    conn.execute(
        "INSERT INTO messages (id, thread_id, role, content, discord_msg, tainted) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (mid, thread_id, role, content, discord_msg, 1 if tainted else 0),
    )
    return mid


def recent_messages(conn: sqlite3.Connection, thread_id: str, limit: int = 20) -> list[dict]:
    """Return up to `limit` most-recent messages in chronological order.

    Each dict carries a `tainted: bool` flag. Callers (notably
    `compose_system`) render tainted entries with an explicit
    untrusted-source wrapper rather than treating them like clean
    operator/assistant text.
    """
    rows = conn.execute(
        "SELECT role, content, created_at, tainted FROM messages "
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
