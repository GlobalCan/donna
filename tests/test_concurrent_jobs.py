"""Concurrent JobContext safety.

Donna's worker has `MAX_CONCURRENT_JOBS` configurable (default 3 in code,
single-worker + single-concurrent in prod today). These tests exercise
what COULD go wrong if the setting were raised:

- Two JobContexts for different jobs, same process, overlap in time
- Each has its own lease, heartbeat, checkpoint path
- Outbox inserts from both must not collide (PK is unique ids_mod.new_id)
- finalize is owner-guarded per-job; one's lease loss doesn't affect the other
- Taint stays scoped to its own job — no cross-pollination via shared state

These are STRUCTURAL guards. Full concurrency stress testing is separate
and would require instrumented SQLite to probe serialization anomalies
under WAL. For solo-operator single-worker usage these invariants are
sufficient — if the user ever bumps MAX_CONCURRENT_JOBS, the suite
already covers the primary race conditions.
"""
from __future__ import annotations

import asyncio

import pytest

from donna.agent.context import JobContext
from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction
from donna.types import JobMode, JobStatus


def _queue_and_claim(task: str, worker_id: str) -> str:
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task=task, agent_scope="orchestrator", mode=JobMode.CHAT,
            )
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                (worker_id, jid),
            )
    finally:
        conn.close()
    return jid


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_two_concurrent_jobs_finalize_independently() -> None:
    """Two JobContexts for different jobs, running concurrently in the same
    event loop, must each deliver their own final_text to outbox. No
    cross-pollination, no missed delivery."""
    jid_a = _queue_and_claim("job a task", "w1")
    jid_b = _queue_and_claim("job b task", "w2")

    async def _drive(jid: str, worker_id: str, answer: str) -> None:
        async with JobContext.open(jid, worker_id=worker_id) as ctx:
            assert ctx is not None
            ctx.state.final_text = answer
            ctx.state.done = True

    await asyncio.gather(
        _drive(jid_a, "w1", "answer A"),
        _drive(jid_b, "w2", "answer B"),
    )

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT job_id, text FROM outbox_updates ORDER BY created_at"
        ).fetchall()
        statuses = {
            r["id"]: r["status"] for r in conn.execute(
                "SELECT id, status FROM jobs WHERE id IN (?, ?)", (jid_a, jid_b),
            ).fetchall()
        }
    finally:
        conn.close()

    assert len(rows) == 2
    delivered = {r["job_id"]: r["text"] for r in rows}
    assert delivered[jid_a] == "answer A"
    assert delivered[jid_b] == "answer B"
    assert statuses[jid_a] == JobStatus.DONE.value
    assert statuses[jid_b] == JobStatus.DONE.value


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_job_a_taint_does_not_leak_into_job_b() -> None:
    """Taint is a per-job state flag. Two concurrent jobs running against
    the same process must NOT share taint — JobState is per-JobContext.
    Regression guard against any accidental module-level taint tracking."""
    jid_clean = _queue_and_claim("clean job", "w1")
    jid_tainted = _queue_and_claim("tainted job", "w2")

    # Prime tainted state by seeding the checkpoint_state
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE jobs SET tainted = 1, taint_source_tool = 'fetch_url' WHERE id = ?",
                (jid_tainted,),
            )
    finally:
        conn.close()

    async def _drive_clean() -> bool:
        async with JobContext.open(jid_clean, worker_id="w1") as ctx:
            assert ctx is not None
            # Give the tainted job time to interleave
            await asyncio.sleep(0.01)
            tainted_flag = ctx.state.tainted
            ctx.state.final_text = "clean answer"
            ctx.state.done = True
            return tainted_flag

    async def _drive_tainted() -> bool:
        async with JobContext.open(jid_tainted, worker_id="w2") as ctx:
            assert ctx is not None
            await asyncio.sleep(0.01)
            tainted_flag = ctx.state.tainted
            ctx.state.final_text = "tainted answer"
            ctx.state.done = True
            return tainted_flag

    clean_taint, tainted_taint = await asyncio.gather(
        _drive_clean(), _drive_tainted(),
    )

    assert clean_taint is False, "clean job's tainted flag was contaminated"
    assert tainted_taint is True, "tainted job's flag was lost"

    # Verify the outbox rows surface the taint flag correctly per-job
    conn = connect()
    try:
        rows = {
            r["job_id"]: bool(r["tainted"]) for r in conn.execute(
                "SELECT job_id, tainted FROM outbox_updates",
            ).fetchall()
        }
    finally:
        conn.close()
    assert rows[jid_clean] is False
    assert rows[jid_tainted] is True


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_outbox_inserts_from_concurrent_jobs_get_unique_ids() -> None:
    """outbox_updates.id is the PK; ids_mod.new_id uses a timestamp +
    random tail. Ten concurrent finalize calls must not produce PK
    collisions. Catches anything that would use e.g. time.time_ns() only
    (which could collide on fast hardware)."""
    N = 10
    jids = [_queue_and_claim(f"job {i}", f"w{i}") for i in range(N)]

    async def _drive(jid: str, worker_id: str, answer: str) -> None:
        async with JobContext.open(jid, worker_id=worker_id) as ctx:
            assert ctx is not None
            ctx.state.final_text = answer
            ctx.state.done = True

    await asyncio.gather(*[
        _drive(jid, f"w{i}", f"answer {i}") for i, jid in enumerate(jids)
    ])

    conn = connect()
    try:
        rows = conn.execute("SELECT id, job_id FROM outbox_updates").fetchall()
    finally:
        conn.close()
    ids = [r["id"] for r in rows]
    assert len(ids) == N
    assert len(set(ids)) == N, "outbox ids must be unique across concurrent jobs"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_stale_worker_finalize_does_not_corrupt_active_worker_job() -> None:
    """Scenario: worker A has a job, lease expires, worker B claims it.
    Worker A (slow / hung) eventually tries to finalize. Owner-guard must
    reject worker A's writes without affecting worker B's state."""
    jid = _queue_and_claim("racy job", "worker_A")

    # Build two contexts for the same job (worker_A is stale, worker_B stole)
    conn = connect()
    try:
        job_a = jobs_mod.get_job(conn, jid)
    finally:
        conn.close()
    ctx_a = JobContext(job_a, worker_id="worker_A")
    ctx_a.state.final_text = "A's stale answer"
    ctx_a.state.done = True

    # Worker B steals
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE jobs SET owner = 'worker_B' WHERE id = ?", (jid,),
            )
        job_b = jobs_mod.get_job(conn, jid)
    finally:
        conn.close()
    ctx_b = JobContext(job_b, worker_id="worker_B")
    ctx_b.state.final_text = "B's real answer"
    ctx_b.state.done = True

    # Worker A attempts finalize — must return False, no outbox row
    a_result = ctx_a.finalize()
    assert a_result is False

    # Worker B finalizes successfully, only B's answer reaches the outbox
    b_result = ctx_b.finalize()
    assert b_result is True

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchall()
        job = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["text"] == "B's real answer"
    assert job["status"] == JobStatus.DONE.value


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_each_concurrent_context_has_its_own_heartbeat_task() -> None:
    """Heartbeat tasks are instance-level (ctx.hb_task), created in
    JobContext.open. Two concurrent contexts must have independent
    heartbeats — no shared task object, no leak across job boundaries."""
    jid_a = _queue_and_claim("hb test a", "w1")
    jid_b = _queue_and_claim("hb test b", "w2")

    hb_tasks: list = []

    async def _drive(jid: str, worker_id: str) -> None:
        async with JobContext.open(jid, worker_id=worker_id) as ctx:
            assert ctx is not None
            hb_tasks.append(ctx.hb_task)
            ctx.state.final_text = "ok"
            ctx.state.done = True

    await asyncio.gather(
        _drive(jid_a, "w1"),
        _drive(jid_b, "w2"),
    )
    assert len(hb_tasks) == 2
    assert hb_tasks[0] is not hb_tasks[1], "heartbeat tasks must be distinct instances"
    # Both tasks have completed cleanly on context exit
    for t in hb_tasks:
        assert t.done()
