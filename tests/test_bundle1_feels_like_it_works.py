"""Bundle 1 — "Donna feels like she works" — production-issue fixes
(2026-04-30) reported by the solo operator after live use:

1. (Discord-only) mobile readability: 1900-char chunks were wall-of-text
   on phone; lowered to 1400 + added `_normalize_for_mobile`. v0.5.0
   migrated to Slack which uses Block Kit's own rendering and doesn't
   need the per-platform mobile tweak — those tests are retired.
2. Session memory: every `/ask` was a fresh job; the agent had no
   recall of its last reply. Wire `messages` table writes into
   `JobContext.finalize` and `recent_messages` reads into chat-mode
   prompt composition. (`agent/context.py`, `agent/loop.py`,
   `agent/compose.py`)
3. Scheduler discoverability: the slash commands existed but the
   operator didn't know. `/schedule` now reports next-fire time, and
   `/schedules` shows last-fired plus an actionable empty-state hint.
   (`adapter/slack_ux.py` — was `adapter/discord_ux.py` pre-v0.5.0.)
4. `send_update` policy spec drift: `docs/PLAN.md` mandated per-call
   consent on tainted updates; the code never enforced it. Updated PLAN
   to reflect the audit-flag-only design. (Docs only — no test needed.)
"""
from __future__ import annotations

import pytest

# ---------- 2. session memory ---------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_finalize_writes_user_and_assistant_messages_when_thread() -> None:
    """JobContext.finalize must persist the user task + assistant final_text
    to `messages` so the next job in the same Discord thread can recall."""
    from donna.agent.context import JobContext
    from donna.memory import jobs as jobs_mod
    from donna.memory import threads as threads_mod
    from donna.memory.db import connect, transaction
    from donna.types import JobMode

    # Seed thread + job
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="dm:user1", thread_external_id=None,
            )
            jid = jobs_mod.insert_job(
                conn, task="what is the weather", agent_scope="any",
                mode=JobMode.CHAT, thread_id=tid,
            )
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                ("test_worker", jid),
            )
    finally:
        conn.close()

    # Build a JobContext that's ready to finalize
    _conn = connect()
    try:
        job = jobs_mod.get_job(_conn, jid)
    finally:
        _conn.close()
    ctx = JobContext(job, worker_id="test_worker")
    ctx.state.final_text = "70 degrees, partly cloudy"
    ctx.state.done = True

    ok = ctx.finalize()
    assert ok

    conn = connect()
    try:
        msgs = threads_mod.recent_messages(conn, tid, limit=10)
    finally:
        conn.close()
    assert len(msgs) == 2, f"expected 2 messages (user + assistant); got {msgs}"
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "what is the weather"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "70 degrees, partly cloudy"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_finalize_writes_tainted_job_with_flag() -> None:
    """v0.4.4 (2026-04-30): tainted jobs now DO write to `messages`,
    flagged with `tainted=1`. compose_system renders tainted rows in
    a separate XML-delimited block with explicit untrusted-source
    warnings — preserving the trust boundary at the prompt layer
    while keeping session memory functional for daily use (almost
    every web-tool DM is tainted).

    Pre-v0.4.4 this test asserted `msgs == []` for tainted jobs;
    that design killed memory in practice."""
    from donna.agent.context import JobContext
    from donna.memory import jobs as jobs_mod
    from donna.memory import threads as threads_mod
    from donna.memory.db import connect, transaction
    from donna.types import JobMode

    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="dm:user1", thread_external_id=None,
            )
            jid = jobs_mod.insert_job(
                conn, task="fetch evil.com", agent_scope="any",
                mode=JobMode.CHAT, thread_id=tid,
            )
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                ("test_worker", jid),
            )
    finally:
        conn.close()

    _conn = connect()
    try:
        job = jobs_mod.get_job(_conn, jid)
    finally:
        _conn.close()
    ctx = JobContext(job, worker_id="test_worker")
    ctx.state.final_text = "the page said something interesting"
    ctx.state.tainted = True
    ctx.state.done = True

    assert ctx.finalize()

    conn = connect()
    try:
        msgs = threads_mod.recent_messages(conn, tid, limit=10)
    finally:
        conn.close()
    assert len(msgs) == 2, (
        f"tainted job must write user + assistant to messages; got "
        f"{len(msgs)} entries: {msgs}"
    )
    assert all(m["tainted"] for m in msgs), (
        f"both rows must carry tainted=True; got {msgs}"
    )
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_finalize_skips_message_write_without_thread() -> None:
    """Jobs queued via CLI / botctl have thread_id = None. No place to
    persist session messages, so just skip cleanly."""
    from donna.agent.context import JobContext
    from donna.memory import jobs as jobs_mod
    from donna.memory.db import connect, transaction
    from donna.types import JobMode

    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="cli task", agent_scope="any", mode=JobMode.CHAT,
                thread_id=None,
            )
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                ("test_worker", jid),
            )
    finally:
        conn.close()

    _conn = connect()
    try:
        job = jobs_mod.get_job(_conn, jid)
    finally:
        _conn.close()
    ctx = JobContext(job, worker_id="test_worker")
    ctx.state.final_text = "done"
    ctx.state.done = True

    # Must not raise even with thread_id=None
    ok = ctx.finalize()
    assert ok


@pytest.mark.usefixtures("fresh_db")
def test_compose_system_includes_session_history_when_provided() -> None:
    """compose_system accepts a `session_history` kwarg and renders it
    in the volatile block as 'Prior conversation in this thread'."""
    from donna.agent.compose import compose_system
    from donna.types import JobMode

    history = [
        {"role": "user", "content": "what's the weather"},
        {"role": "assistant", "content": "70 partly cloudy"},
        {"role": "user", "content": "and tomorrow"},
        {"role": "assistant", "content": "rain forecast"},
    ]
    blocks = compose_system(
        scope="any", task="follow up question", mode=JobMode.CHAT,
        session_history=history,
    )
    # Combine all volatile + task blocks into a single string for assertion
    full = "\n".join(b.get("text", "") for b in blocks)
    assert "Prior conversation in this thread" in full
    assert "what's the weather" in full
    assert "70 partly cloudy" in full
    assert "rain forecast" in full


@pytest.mark.usefixtures("fresh_db")
def test_compose_system_omits_session_block_when_empty() -> None:
    """No history → no 'Prior conversation' header at all. Avoids prompt
    bloat on first-message threads."""
    from donna.agent.compose import compose_system
    from donna.types import JobMode

    blocks = compose_system(
        scope="any", task="first question", mode=JobMode.CHAT,
        session_history=[],
    )
    full = "\n".join(b.get("text", "") for b in blocks)
    assert "Prior conversation in this thread" not in full


@pytest.mark.usefixtures("fresh_db")
def test_compose_system_caps_history_at_8_messages() -> None:
    """Even if 30 prior messages exist, only the last 8 (4 turns) get
    injected. Prevents prompt bloat on long-running threads."""
    from donna.agent.compose import compose_system
    from donna.types import JobMode

    history = [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": f"message {i}"}
        for i in range(30)
    ]
    blocks = compose_system(
        scope="any", task="t", mode=JobMode.CHAT, session_history=history,
    )
    full = "\n".join(b.get("text", "") for b in blocks)
    # Last 8 should appear
    for i in range(22, 30):
        assert f"message {i}" in full, f"recent message {i} should be present"
    # Earlier ones should NOT
    for i in range(0, 22):
        assert f"message {i}\n" not in full, (
            f"older message {i} should be excluded"
        )


# ---------- 3. scheduler discoverability ----------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_schedules_listing_shape_includes_last_run_at() -> None:
    """`list_schedules` returns the columns the new `/schedules` rendering
    needs: id, cron_expr, next_run_at, last_run_at, task. No new code —
    pin the pre-existing return shape so the slash-command formatter
    can rely on it."""
    from donna.memory import schedules as sched_mod
    from donna.memory.db import connect, transaction

    conn = connect()
    try:
        with transaction(conn):
            sched_mod.insert_schedule(
                conn, cron_expr="0 13 * * *",
                task="daily AI news brief",
            )
        items = sched_mod.list_schedules(conn)
    finally:
        conn.close()

    assert len(items) == 1
    s = items[0]
    for key in ("id", "cron_expr", "next_run_at", "last_run_at", "task"):
        assert key in s, f"list_schedules missing key {key!r}: {s.keys()}"
    assert s["last_run_at"] is None  # never fired yet
    assert s["cron_expr"] == "0 13 * * *"


@pytest.mark.usefixtures("fresh_db")
def test_invalid_cron_raises_value_error() -> None:
    """The /schedule slash command catches ValueError and returns a
    user-friendly error. Pin that insert_schedule raises rather than
    silently storing a bad cron."""
    from donna.memory import schedules as sched_mod
    from donna.memory.db import connect, transaction

    conn = connect()
    try:
        with transaction(conn), pytest.raises(ValueError, match="(?i)invalid cron"):
            sched_mod.insert_schedule(
                conn, cron_expr="not a cron", task="x",
            )
    finally:
        conn.close()
