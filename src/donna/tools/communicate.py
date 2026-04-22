"""Communicate tools — ask_user, send_update.

Outbox is persisted via SQLite (tables `outbox_updates`, `outbox_asks`)
so the bot process can drain what the worker process wrote. In-memory
asyncio.Queue objects cannot cross process boundaries; Donna runs bot
and worker as separate processes in both local-dev and docker-compose.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..logging import get_logger
from ..memory import ids as ids_mod
from ..memory.db import connect, transaction
from .registry import tool

log = get_logger(__name__)


# Polling interval when waiting for a user reply to ask_user.
_ASK_POLL_INTERVAL_S = 2.0
# Upper bound for ask_user (matches prior behavior).
_ASK_TIMEOUT_S = 1800.0


@tool(
    scope="communicate", cost="low",
    description=(
        "Send a short progress update to the user's Discord thread. "
        "Rate-limited to 1/5s per job. Use for visible 'I'm working on X' pings "
        "during long jobs."
    ),
)
async def send_update(
    text: str,
    job_id: str | None = None,
    tainted: bool = False,
) -> dict[str, Any]:
    if job_id is None:
        return {"error": "send_update requires job_id context"}
    uid = ids_mod.new_id("upd")
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO outbox_updates (id, job_id, text, tainted) VALUES (?, ?, ?, ?)",
                (uid, job_id, text[:1500], 1 if tainted else 0),
            )
    finally:
        conn.close()
    return {"queued": True, "id": uid}


@tool(
    scope="communicate", cost="low",
    description=(
        "Pause and ask the user a clarifying question in Discord. Blocks the "
        "job until they reply. Use when genuinely ambiguous — do NOT use to "
        "rubber-stamp trivial assumptions."
    ),
)
async def ask_user(question: str, job_id: str | None = None) -> dict[str, Any]:
    if job_id is None:
        return {"error": "ask_user requires job_id context"}
    aid = ids_mod.new_id("ask")
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO outbox_asks (id, job_id, question) VALUES (?, ?, ?)",
                (aid, job_id, question),
            )
    finally:
        conn.close()

    loop = asyncio.get_event_loop()
    deadline = loop.time() + _ASK_TIMEOUT_S
    try:
        while loop.time() < deadline:
            await asyncio.sleep(_ASK_POLL_INTERVAL_S)
            conn = connect()
            try:
                row = conn.execute(
                    "SELECT reply FROM outbox_asks WHERE id = ?", (aid,),
                ).fetchone()
            finally:
                conn.close()
            if row is None:
                # Row was deleted externally — treat as abandon
                return {"reply": None, "timeout": True}
            if row["reply"] is not None:
                return {"reply": row["reply"], "timeout": False}
        return {"reply": None, "timeout": True}
    finally:
        conn = connect()
        try:
            with transaction(conn):
                conn.execute("DELETE FROM outbox_asks WHERE id = ?", (aid,))
        finally:
            conn.close()
