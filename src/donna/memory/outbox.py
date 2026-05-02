"""Outbox helpers (v0.7.2) — durable cross-process delivery queue.

Codex 2026-05-02 review on the overnight plan flagged JobContext as
carrying too many concerns: lifecycle, outbox writes, tool dispatch,
session memory. The lifecycle layer is already in `memory.jobs`; the
session memory writes are already in `memory.threads.insert_message`.
The genuinely-inlined surface is the outbox INSERTs — repeated in 4
places (JobContext.finalize, tools/communicate.py send_update +
ask_user, botctl dead-letter retry).

This module consolidates those into named helpers:

- `enqueue_update(conn, *, job_id, text, tainted)` — assistant output
  destined for delivery via the Slack adapter drainer.
- `enqueue_ask(conn, *, job_id, question)` — consent prompt awaiting
  ✅/❌ from the operator.

Pure SQL helpers; caller wraps in `transaction(conn)` so they can be
composed atomically (e.g., JobContext.finalize writes outbox + messages
+ DONE flip in one transaction).

Codex's pitfall: "Do not let each service open its own transaction
during finalize." This module does NOT open transactions; it expects
the caller's transaction to be already open.

Reads (drainer polling) stay in `slack_adapter.py` because they're
intertwined with rate-limit cool-down + retry-after logic that's
adapter-specific.
"""
from __future__ import annotations

import sqlite3

from . import ids

_UPDATE_TEXT_CAP = 20000


def enqueue_update(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    text: str,
    tainted: bool,
) -> str:
    """Insert a row into outbox_updates. Returns the new row id.

    `text` is truncated at 20000 chars to keep the row size bounded —
    the Slack adapter's drainer chunks long messages into multi-part
    deliveries from this column. Pre-truncation in the caller is fine;
    this is belt-and-suspenders.

    Caller must wrap in `transaction(conn)` if multi-statement
    atomicity matters (it does for JobContext.finalize).
    """
    rid = ids.new_id("upd")
    conn.execute(
        "INSERT INTO outbox_updates (id, job_id, text, tainted) "
        "VALUES (?, ?, ?, ?)",
        (rid, job_id, text[:_UPDATE_TEXT_CAP], 1 if tainted else 0),
    )
    return rid


def enqueue_ask(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    question: str,
) -> str:
    """Insert a row into outbox_asks. Returns the new ask id.

    The id flows back to the bot's consent / ask handler so the
    operator's reply can be matched to this question. Caller wraps in
    transaction.
    """
    aid = ids.new_id("ask")
    conn.execute(
        "INSERT INTO outbox_asks (id, job_id, question) VALUES (?, ?, ?)",
        (aid, job_id, question),
    )
    return aid


def list_updates_for_job(
    conn: sqlite3.Connection, job_id: str,
) -> list[dict]:
    """Read-back helper for ops/observability. Returns all
    outbox_updates rows for a given job, oldest first. Used by tests
    + future botctl introspection."""
    rows = conn.execute(
        "SELECT id, job_id, text, tainted, created_at "
        "FROM outbox_updates WHERE job_id = ? "
        "ORDER BY created_at ASC, id ASC",
        (job_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_asks_for_job(
    conn: sqlite3.Connection, job_id: str,
) -> list[dict]:
    """Same shape, for outbox_asks."""
    rows = conn.execute(
        "SELECT id, job_id, question, posted_message_id, posted_channel_id "
        "FROM outbox_asks WHERE job_id = ?",
        (job_id,),
    ).fetchall()
    return [dict(r) for r in rows]
