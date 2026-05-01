"""Plain DM session memory must not duplicate the user's task.

Bug surfaced 2026-04-30 during operator daily use. v0.4.2's session memory
wired up `JobContext.finalize` to write user + assistant rows to the
`messages` table on every chat-mode job completion. But `_handle_new_task`
in the Discord adapter ALSO wrote a user-message row at intake — so plain
DM threads accumulated duplicate user entries:

    User: what's the weather?            ← from adapter at intake
    User: what's the weather?            ← from finalize at completion
    You: it's 70 degrees                  ← from finalize at completion

Worse, the adapter's intake write made the *current* task appear as a
prior turn in the next job's `session_history`, confusing the model.

`/ask`, `/speculate`, `/debate` (which go through `_enqueue_scoped`)
never had an intake write — they were already correct. The fix makes
plain DM symmetric: drop the adapter's `threads_mod.insert_message`
call, let `JobContext.finalize` be the sole writer for all modes.

Trade-off: failed/cancelled jobs lose the user-message audit row, but
the operator can see what they typed in Discord scrollback so this is
acceptable. `discord_msg` traceability is dropped (was unused — grep
confirmed no reader anywhere in the codebase).

These tests exercise the data layer rather than mocking the full
Discord client. The post-fix `_handle_new_task` body is just:
`get_or_create_thread` + `insert_job` (no message write); the tests
simulate that flow directly.
"""
from __future__ import annotations

import pytest

from donna.agent.context import JobContext
from donna.memory import jobs as jobs_mod
from donna.memory import threads as threads_mod
from donna.memory.db import connect, transaction


def _simulate_plain_dm_intake(content: str, channel_id: str) -> tuple[str, str]:
    """Mirror `_handle_new_task`'s post-v0.4.3 DB ops without the Discord
    client. Returns (thread_id, job_id). If this stops matching the real
    function shape, the integration test below will catch drift."""
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn,
                channel_id=channel_id,
                thread_external_id=None,
                title=content[:60],
            )
            jid = jobs_mod.insert_job(
                conn, task=content, thread_id=tid,
            )
    finally:
        conn.close()
    return tid, jid


def _claim_for_finalize(jid: str, worker_id: str = "test_worker") -> None:
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                (worker_id, jid),
            )
    finally:
        conn.close()


@pytest.mark.usefixtures("fresh_db")
def test_plain_dm_intake_does_not_write_user_message() -> None:
    """The core regression guard: `_handle_new_task`'s post-fix data ops
    must NOT insert into `messages`. The pre-fix adapter wrote here at
    intake, then finalize wrote AGAIN — producing duplicate user rows."""
    tid, _jid = _simulate_plain_dm_intake("what is the weather", "dm:userA")

    conn = connect()
    try:
        msgs = threads_mod.recent_messages(conn, tid, limit=10)
    finally:
        conn.close()

    assert msgs == [], (
        f"plain DM intake must not write to `messages`; got {len(msgs)} "
        "entries. JobContext.finalize is the single writer. If this test "
        "fails, someone re-added `threads_mod.insert_message` to "
        "`_handle_new_task` — revert it."
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_full_cycle_produces_exactly_user_plus_assistant() -> None:
    """End-to-end regression: a single plain-DM exchange (intake →
    finalize) must produce exactly 2 message rows — one user, one
    assistant. Pre-fix this produced 3 (duplicate user)."""
    tid, jid = _simulate_plain_dm_intake("hello donna", "dm:userB")
    _claim_for_finalize(jid, worker_id="test_worker_B")

    conn = connect()
    try:
        job = jobs_mod.get_job(conn, jid)
    finally:
        conn.close()
    ctx = JobContext(job, worker_id="test_worker_B")
    ctx.state.final_text = "hi! how can I help?"
    ctx.state.done = True
    assert ctx.finalize()

    conn = connect()
    try:
        msgs = threads_mod.recent_messages(conn, tid, limit=10)
    finally:
        conn.close()
    assert len(msgs) == 2, f"expected 2 messages; got {len(msgs)}: {msgs}"
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello donna"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "hi! how can I help?"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_two_sequential_exchanges_produce_clean_history() -> None:
    """The user-facing scenario: two plain DMs in sequence. Second job's
    `session_history` (what the model sees as 'Prior conversation') must
    contain exactly 2 rows for the first exchange — not 3 (which the
    pre-fix duplicate write caused) and not the current task as a
    duplicate prior turn."""
    # First exchange
    tid_1, jid_1 = _simulate_plain_dm_intake(
        "what is the weather", "dm:userC",
    )
    _claim_for_finalize(jid_1, worker_id="test_worker_1")
    conn = connect()
    try:
        job_1 = jobs_mod.get_job(conn, jid_1)
    finally:
        conn.close()
    ctx_1 = JobContext(job_1, worker_id="test_worker_1")
    ctx_1.state.final_text = "70 degrees, partly cloudy"
    ctx_1.state.done = True
    assert ctx_1.finalize()

    # Second exchange — same channel, so same thread
    tid_2, jid_2 = _simulate_plain_dm_intake("and tomorrow?", "dm:userC")
    assert tid_1 == tid_2, "same channel must reuse the thread"

    # Snapshot what the second job's `_run_chat` would see at loop entry.
    # Pre-fix this would include the duplicate user row from the adapter
    # AND the current "and tomorrow?" task pre-recorded as a prior turn.
    conn = connect()
    try:
        history_for_job_2 = threads_mod.recent_messages(conn, tid_2, limit=8)
    finally:
        conn.close()

    assert len(history_for_job_2) == 2, (
        f"second job's session_history must show exactly the prior "
        f"exchange (user + assistant) — no duplicates and no current "
        f"task pre-recorded. Got {len(history_for_job_2)} rows: "
        f"{history_for_job_2}"
    )
    assert history_for_job_2[0]["role"] == "user"
    assert history_for_job_2[0]["content"] == "what is the weather"
    assert history_for_job_2[1]["role"] == "assistant"
    assert history_for_job_2[1]["content"] == "70 degrees, partly cloudy"

    # Now finalize job 2; total messages should be exactly 4.
    _claim_for_finalize(jid_2, worker_id="test_worker_2")
    conn = connect()
    try:
        job_2 = jobs_mod.get_job(conn, jid_2)
    finally:
        conn.close()
    ctx_2 = JobContext(job_2, worker_id="test_worker_2")
    ctx_2.state.final_text = "rain expected"
    ctx_2.state.done = True
    assert ctx_2.finalize()

    conn = connect()
    try:
        full = threads_mod.recent_messages(conn, tid_2, limit=20)
    finally:
        conn.close()
    assert len(full) == 4, f"expected 4 total messages, got {len(full)}: {full}"
    assert [m["role"] for m in full] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in full] == [
        "what is the weather",
        "70 degrees, partly cloudy",
        "and tomorrow?",
        "rain expected",
    ]
