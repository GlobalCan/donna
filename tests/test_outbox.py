"""Outbox persistence tests — verify SQLite-backed cross-process pattern.

The original in-memory asyncio.Queue outbox was invisible across the
donna.main / donna.worker process boundary. Migration 0005 moved it
into DB tables; these tests exercise that path.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from donna.memory.db import connect, transaction
from donna.types import ConfirmationMode, ToolEntry


# ---------- send_update: INSERTs into outbox_updates -----------------------


@pytest.mark.usefixtures("fresh_db")
def test_send_update_persists_row() -> None:
    """send_update writes to DB, not an in-memory queue."""
    from donna.tools import communicate as comm

    result = asyncio.run(
        comm.send_update(text="hello", job_id="job_test_abc", tainted=False)
    )
    assert result["queued"] is True

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT job_id, text, tainted FROM outbox_updates ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["job_id"] == "job_test_abc"
    assert rows[0]["text"] == "hello"
    assert rows[0]["tainted"] == 0


@pytest.mark.usefixtures("fresh_db")
def test_send_update_truncates_long_text() -> None:
    from donna.tools import communicate as comm

    long_text = "x" * 5000
    asyncio.run(comm.send_update(text=long_text, job_id="job_trim"))
    conn = connect()
    try:
        row = conn.execute("SELECT text FROM outbox_updates").fetchone()
    finally:
        conn.close()
    assert len(row["text"]) == 1500


@pytest.mark.usefixtures("fresh_db")
def test_send_update_without_job_id_errors() -> None:
    from donna.tools import communicate as comm

    result = asyncio.run(comm.send_update(text="no job"))
    assert "error" in result


# ---------- ask_user: INSERTs + polls for reply ----------------------------


@pytest.mark.usefixtures("fresh_db")
def test_ask_user_returns_reply_from_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker's ask_user polls the DB; a simulated bot write satisfies it."""
    from donna.tools import communicate as comm

    # Speed up polling so the test finishes fast.
    monkeypatch.setattr(comm, "_ASK_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(comm, "_ASK_TIMEOUT_S", 5.0)

    async def scenario() -> dict:
        ask_task = asyncio.create_task(
            comm.ask_user(question="what's your name?", job_id="job_ask_1")
        )

        # Wait for the row to appear, then simulate the bot writing a reply.
        for _ in range(50):
            await asyncio.sleep(0.02)
            conn = connect()
            try:
                row = conn.execute(
                    "SELECT id FROM outbox_asks WHERE job_id = ?", ("job_ask_1",),
                ).fetchone()
            finally:
                conn.close()
            if row:
                conn = connect()
                try:
                    with transaction(conn):
                        conn.execute(
                            "UPDATE outbox_asks SET reply = ?, "
                            "replied_at = CURRENT_TIMESTAMP WHERE id = ?",
                            ("Donna", row["id"]),
                        )
                finally:
                    conn.close()
                break

        return await ask_task

    result = asyncio.run(scenario())
    assert result["reply"] == "Donna"
    assert result["timeout"] is False

    # Row cleaned up after success
    conn = connect()
    try:
        row = conn.execute("SELECT id FROM outbox_asks WHERE job_id = ?",
                            ("job_ask_1",)).fetchone()
    finally:
        conn.close()
    assert row is None


@pytest.mark.usefixtures("fresh_db")
def test_ask_user_timeout_cleans_up_row(monkeypatch: pytest.MonkeyPatch) -> None:
    from donna.tools import communicate as comm

    monkeypatch.setattr(comm, "_ASK_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(comm, "_ASK_TIMEOUT_S", 0.3)

    result = asyncio.run(comm.ask_user(question="?", job_id="job_ask_timeout"))
    assert result["timeout"] is True
    assert result["reply"] is None

    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM outbox_asks WHERE job_id = ?", ("job_ask_timeout",),
        ).fetchone()
    finally:
        conn.close()
    assert row is None


# ---------- consent.check: polls pending_consents.approved -----------------


@pytest.mark.usefixtures("fresh_db")
def test_consent_check_returns_on_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bot UPDATEs approved; the worker's poll sees it and returns."""
    from donna.memory import jobs as jobs_mod
    from donna.security import consent as consent_mod

    monkeypatch.setattr(consent_mod, "_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(consent_mod, "_CONSENT_TIMEOUT_S", 5.0)

    # Need a job row (pending_consents.job_id FK)
    conn = connect()
    try:
        with transaction(conn):
            job_id = jobs_mod.insert_job(conn, task="ask-me")
            conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
    finally:
        conn.close()

    async def _noop(**_: object) -> None:  # pragma: no cover
        return None

    entry = ToolEntry(
        name="remember",
        fn=_noop,
        scope="memory_write",
        cost="low",
        description="",
        schema={"name": "remember", "input_schema": {}},
        confirmation=ConfirmationMode.ALWAYS,
        taints_job=False,
        idempotent=True,
        agents=("*",),
    )

    async def scenario() -> consent_mod.ConsentResult:
        check_task = asyncio.create_task(
            consent_mod.check(
                job_id=job_id, entry=entry,
                arguments={"fact": "x"}, tainted=False,
            )
        )

        # Simulate bot approval after the worker persists the pending row.
        for _ in range(50):
            await asyncio.sleep(0.02)
            conn = connect()
            try:
                row = conn.execute(
                    "SELECT id FROM pending_consents WHERE job_id = ?", (job_id,),
                ).fetchone()
            finally:
                conn.close()
            if row:
                conn = connect()
                try:
                    with transaction(conn):
                        conn.execute(
                            "UPDATE pending_consents SET approved = 1, "
                            "decided_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (row["id"],),
                        )
                finally:
                    conn.close()
                break

        return await check_task

    result = asyncio.run(scenario())
    assert result.approved is True
    assert "approved" in result.reason

    # Row cleaned up; job status flipped back to running.
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM pending_consents WHERE job_id = ?", (job_id,),
        ).fetchall()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    finally:
        conn.close()
    assert len(rows) == 0
    assert job_row["status"] == "running"


# ---------- migration 0005 schema shape ------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_outbox_tables_exist() -> None:
    conn = connect()
    try:
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "outbox_updates" in tables
    assert "outbox_asks" in tables


@pytest.mark.usefixtures("fresh_db")
def test_pending_consents_has_new_columns() -> None:
    conn = connect()
    try:
        cols = {
            r["name"] for r in conn.execute(
                "PRAGMA table_info(pending_consents)"
            ).fetchall()
        }
    finally:
        conn.close()
    assert {"approved", "decided_at", "posted_channel_id", "posted_message_id"} <= cols
