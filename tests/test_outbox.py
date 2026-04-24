"""Outbox persistence tests — verify SQLite-backed cross-process pattern.

The original in-memory asyncio.Queue outbox was invisible across the
donna.main / donna.worker process boundary. Migration 0005 moved it
into DB tables; these tests exercise that path.
"""
from __future__ import annotations

import asyncio

import pytest

from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction
from donna.types import ConfirmationMode, ToolEntry


def _make_job(task: str = "t") -> str:
    """Insert a minimal job row; outbox tables FK to jobs(id)."""
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(conn, task=task)
    finally:
        conn.close()
    return jid


# ---------- send_update: INSERTs into outbox_updates -----------------------


@pytest.mark.usefixtures("fresh_db")
def test_send_update_persists_row() -> None:
    """send_update writes to DB, not an in-memory queue."""
    from donna.tools import communicate as comm

    jid = _make_job()
    result = asyncio.run(
        comm.send_update(text="hello", job_id=jid, tainted=False)
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
    assert rows[0]["job_id"] == jid
    assert rows[0]["text"] == "hello"
    assert rows[0]["tainted"] == 0


@pytest.mark.usefixtures("fresh_db")
def test_send_update_truncates_long_text() -> None:
    from donna.tools import communicate as comm

    jid = _make_job()
    long_text = "x" * 5000
    asyncio.run(comm.send_update(text=long_text, job_id=jid))
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

    jid = _make_job()

    async def scenario() -> dict:
        ask_task = asyncio.create_task(
            comm.ask_user(question="what's your name?", job_id=jid)
        )

        # Wait for the row to appear, then simulate the bot writing a reply.
        for _ in range(50):
            await asyncio.sleep(0.02)
            conn = connect()
            try:
                row = conn.execute(
                    "SELECT id FROM outbox_asks WHERE job_id = ?", (jid,),
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
                            (jid,)).fetchone()
    finally:
        conn.close()
    assert row is None


@pytest.mark.usefixtures("fresh_db")
def test_ask_user_timeout_cleans_up_row(monkeypatch: pytest.MonkeyPatch) -> None:
    from donna.tools import communicate as comm

    monkeypatch.setattr(comm, "_ASK_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(comm, "_ASK_TIMEOUT_S", 0.3)

    jid = _make_job()
    result = asyncio.run(comm.ask_user(question="?", job_id=jid))
    assert result["timeout"] is True
    assert result["reply"] is None

    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM outbox_asks WHERE job_id = ?", (jid,),
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


# ---------- every mode's final_text reaches the outbox via finalize() -------
#
# Originally only chat mode wrote to outbox_updates — via a manual
# `_enqueue_final_text` helper called at the end of `_run_chat`. Commit c623ab1
# explicitly deferred the same fix for grounded / speculative / debate "until
# their smoke tests surface it." These tests surface it and lock in the
# unified fix: delivery lives inside `JobContext.finalize()`, so every mode
# that sets `final_text` + `done=True` and lets the context manager finalize
# delivers to Discord without each mode remembering to do it.


def _claim_job(jid: str, worker_id: str) -> None:
    """Flip a queued job to running with this worker as owner so
    save_checkpoint / set_status owner-guards pass."""
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') "
                "WHERE id = ?",
                (worker_id, jid),
            )
    finally:
        conn.close()


def _make_ctx(jid: str, worker_id: str = "test-worker"):
    from donna.agent.context import JobContext
    from donna.memory import jobs as jobs_mod_local
    _claim_job(jid, worker_id)
    conn = connect()
    try:
        job = jobs_mod_local.get_job(conn, jid)
    finally:
        conn.close()
    return JobContext(job, worker_id=worker_id)


@pytest.mark.usefixtures("fresh_db")
def test_finalize_writes_final_text_to_outbox() -> None:
    """The unified finalize() writes final_text to outbox_updates atomically
    with the DONE status flip. Chat mode's old `_enqueue_final_text` helper
    was replaced by this method so every mode delivers by contract."""
    jid = _make_job()
    ctx = _make_ctx(jid)
    ctx.state.final_text = "Mark Twain summary here."
    ctx.state.tainted = True
    ctx.state.done = True

    assert ctx.finalize() is True

    conn = connect()
    try:
        row = conn.execute(
            "SELECT text, tainted FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["text"] == "Mark Twain summary here."
    assert row["tainted"] == 1
    # DONE status and outbox write must be atomic within the same transaction
    assert job_row["status"] == "done"


@pytest.mark.usefixtures("fresh_db")
def test_finalize_skips_empty_final_text() -> None:
    """Whitespace-only final_text is a no-op for outbox; DONE still flips."""
    jid = _make_job()
    ctx = _make_ctx(jid)
    ctx.state.final_text = "   "
    ctx.state.tainted = False
    ctx.state.done = True

    assert ctx.finalize() is True

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchall()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert len(rows) == 0
    # No text to deliver, but the job still completes
    assert job_row["status"] == "done"


@pytest.mark.usefixtures("fresh_db")
def test_finalize_truncates_long_final_text() -> None:
    """Matches send_update's 1500-char cap so Discord's 2000-char limit
    is never blown by a runaway end_turn answer."""
    jid = _make_job()
    ctx = _make_ctx(jid)
    ctx.state.final_text = "y" * 5000
    ctx.state.done = True

    assert ctx.finalize() is True

    conn = connect()
    try:
        row = conn.execute(
            "SELECT text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert len(row["text"]) == 1500


@pytest.mark.usefixtures("fresh_db")
def test_finalize_returns_false_on_lost_lease_and_does_not_deliver() -> None:
    """If another worker has taken the lease, finalize returns False without
    writing to outbox or flipping status. Prevents double-delivery on retry
    (a latent chat-mode bug before this refactor)."""
    jid = _make_job()
    worker_a = "worker-a"
    worker_b = "worker-b"
    ctx = _make_ctx(jid, worker_id=worker_a)
    ctx.state.final_text = "Would deliver if lease still held."
    ctx.state.done = True

    # Simulate another worker stealing the lease between _make_ctx and finalize.
    conn = connect()
    try:
        with transaction(conn):
            conn.execute("UPDATE jobs SET owner = ? WHERE id = ?", (worker_b, jid))
    finally:
        conn.close()

    assert ctx.finalize() is False

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchall()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert len(rows) == 0
    assert job_row["status"] == "running"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_grounded_refusal_delivers_to_outbox() -> None:
    """Grounded mode's no-corpus refusal sets final_text + done=True. Before
    the finalize() unification this text was orphaned — no outbox row, no
    Discord delivery. Now it lands in outbox via the shared finalize path."""
    from donna.agent.context import JobContext
    from donna.modes.grounded import run_grounded
    from donna.types import JobMode
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="what does Twain say about civilization?",
                agent_scope="author_twain_empty_corpus",
                mode=JobMode.GROUNDED,
            )
    finally:
        conn.close()
    _claim_job(jid, "test-worker")

    async with JobContext.open(jid, worker_id="test-worker") as ctx:
        assert ctx is not None
        await run_grounded(ctx)

    conn = connect()
    try:
        row = conn.execute(
            "SELECT text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert "refused" in row["text"].lower() or "don't have" in row["text"].lower()
    assert job_row["status"] == "done"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_speculative_refusal_delivers_to_outbox() -> None:
    """Speculative mode's 'speculation disabled' refusal sets final_text +
    done=True. Same delivery regression class as grounded — fixed by unified
    finalize()."""
    from donna.agent.context import JobContext
    from donna.modes.speculative import run_speculative
    from donna.types import JobMode
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="what would Taleb think about AI coding?",
                agent_scope="author_taleb_no_permission",
                mode=JobMode.SPECULATIVE,
            )
    finally:
        conn.close()
    _claim_job(jid, "test-worker")

    async with JobContext.open(jid, worker_id="test-worker") as ctx:
        assert ctx is not None
        await run_speculative(ctx)

    conn = connect()
    try:
        row = conn.execute(
            "SELECT text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert "speculati" in row["text"].lower()
    assert job_row["status"] == "done"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_debate_delivers_final_text_to_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_debate_in_context sets final_text from _format_debate(result). Before
    unified finalize(), that text was orphaned. We stub _debate_core so the test
    doesn't need live Anthropic/retrieval; the assertion is the delivery path,
    not the debate content."""
    import json as _json

    from donna.agent.context import JobContext
    from donna.modes import debate as debate_mod
    from donna.types import JobMode

    async def _fake_debate_core(*, ctx, topic, scopes, rounds):
        return {"error": "stubbed debate for delivery-path test"}

    monkeypatch.setattr(debate_mod, "_debate_core", _fake_debate_core)

    task_payload = _json.dumps({
        "scope_a": "author_twain",
        "scope_b": "orchestrator",
        "topic": "civilization",
        "rounds": 1,
    })
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task=task_payload,
                agent_scope="orchestrator",
                mode=JobMode.DEBATE,
            )
    finally:
        conn.close()
    _claim_job(jid, "test-worker")

    async with JobContext.open(jid, worker_id="test-worker") as ctx:
        assert ctx is not None
        await debate_mod.run_debate_in_context(ctx)

    conn = connect()
    try:
        row = conn.execute(
            "SELECT text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert "stubbed" in row["text"] or "error" in row["text"].lower()
    assert job_row["status"] == "done"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_cancelled_job_does_not_deliver_to_outbox() -> None:
    """JobCancelled bypasses finalize() by design — cancelled jobs must not
    post anything to Discord. Regression guard for the unified delivery
    path: prior hand-placed _enqueue_final_text in _run_chat also never
    ran on cancel; the new finalize-based path preserves that."""
    from donna.agent.context import JobCancelled, JobContext
    from donna.memory import jobs as jobs_mod_local
    from donna.types import JobStatus

    jid = _make_job()

    async with JobContext.open(jid, worker_id="test-worker") as ctx:
        assert ctx is not None
        ctx.state.final_text = "This answer must NOT be delivered."
        # Simulate operator /cancel mid-run: flip status, then raise.
        conn = connect()
        try:
            with transaction(conn):
                jobs_mod.set_status(conn, jid, JobStatus.CANCELLED)
        finally:
            conn.close()
        raise JobCancelled(jid)

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchall()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    _ = jobs_mod_local  # keep import alive for readability
    assert len(rows) == 0
    assert job_row["status"] == "cancelled"


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
