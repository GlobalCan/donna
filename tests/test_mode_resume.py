"""Mode resume short-circuit tests.

Adversarial probe: a worker running a non-chat mode (grounded / speculative /
debate) can crash AFTER checkpointing `state.done=True` + `state.final_text`
but BEFORE `finalize()` runs. The next worker reclaims the expired lease
and re-enters `JobContext.open` with `done=True` already in `state`.

Before this guard, the mode handlers had no done-check at entry — they'd
blow ~$0.05–$1.50 of LLM spend redoing retrieval + generation, potentially
producing a different answer than what the first worker had composed. Then
finalize would overwrite final_text with the new answer and deliver it.

After the guard: `if ctx.state.done: return` at each mode entry. Context
manager still finalizes on exit, delivering the pre-existing final_text
verbatim. No LLM call on resume.

Chat mode has the same guard implicitly via its `while not ctx.state.done`
loop condition. These tests pin the same behavior for grounded / speculative /
debate.
"""
from __future__ import annotations

import json

import pytest

from donna.agent.context import JobContext
from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction
from donna.types import JobMode, JobState, JobStatus


def _queue_job(mode: JobMode, task: str = "t", scope: str = "author_twain") -> str:
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(conn, task=task, agent_scope=scope, mode=mode)
    finally:
        conn.close()
    return jid


def _claim_and_set_done(
    jid: str, worker_id: str, final_text: str, mode: JobMode, scope: str,
) -> None:
    """Simulate the crash-between-checkpoint-and-finalize state:
    - Job is RUNNING, owned by this worker, lease valid
    - checkpoint_state has done=True + the final_text the model produced
    - Status has NOT flipped to DONE (finalize never ran)."""
    state = JobState(
        job_id=jid, agent_scope=scope, mode=mode,
        final_text=final_text, done=True,
    )
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes'), "
                "checkpoint_state = ? WHERE id = ?",
                (worker_id, json.dumps(state.to_dict()), jid),
            )
    finally:
        conn.close()


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_grounded_resume_short_circuits_without_calling_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_grounded on a resumed job with done=True must skip retrieve +
    model_step. Verified by asserting both were never called."""
    from donna.modes import grounded as grounded_mod

    retrieve_calls: list = []
    model_calls: list = []

    async def _fake_retrieve(*args, **kwargs):
        retrieve_calls.append(kwargs)
        return {"chunks": []}

    async def _fake_model_step(*args, **kwargs):
        model_calls.append(kwargs)
        raise AssertionError("model_step must not run on resume")

    monkeypatch.setattr(grounded_mod, "retrieve_knowledge", _fake_retrieve)
    monkeypatch.setattr(JobContext, "model_step", _fake_model_step)

    jid = _queue_job(JobMode.GROUNDED)
    prior_answer = "The answer the prior worker produced before crashing."
    _claim_and_set_done(jid, "test-worker", prior_answer,
                        JobMode.GROUNDED, "author_twain")

    async with JobContext.open(jid, worker_id="test-worker") as ctx:
        assert ctx is not None
        await grounded_mod.run_grounded(ctx)

    assert retrieve_calls == [], "retrieve_knowledge must not run on resume"
    assert model_calls == [], "model_step must not run on resume"

    # Finalize still delivered the pre-existing final_text
    conn = connect()
    try:
        outbox = conn.execute(
            "SELECT text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert outbox is not None
    assert outbox["text"] == prior_answer
    assert job_row["status"] == JobStatus.DONE.value


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_speculative_resume_short_circuits_without_calling_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from donna.modes import speculative as speculative_mod

    retrieve_calls: list = []

    async def _fake_retrieve(*args, **kwargs):
        retrieve_calls.append(kwargs)
        return {"chunks": []}

    async def _fake_model_step(*args, **kwargs):
        raise AssertionError("model_step must not run on resume")

    monkeypatch.setattr(speculative_mod, "retrieve_knowledge", _fake_retrieve)
    monkeypatch.setattr(JobContext, "model_step", _fake_model_step)

    jid = _queue_job(JobMode.SPECULATIVE)
    prior_answer = "🔮 SPECULATIVE — speculation the prior worker generated."
    _claim_and_set_done(jid, "test-worker", prior_answer,
                        JobMode.SPECULATIVE, "author_twain")

    async with JobContext.open(jid, worker_id="test-worker") as ctx:
        assert ctx is not None
        await speculative_mod.run_speculative(ctx)

    assert retrieve_calls == []

    conn = connect()
    try:
        outbox = conn.execute(
            "SELECT text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert outbox is not None
    assert outbox["text"][:len(prior_answer)] == prior_answer[:1500]
    assert job_row["status"] == JobStatus.DONE.value


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_debate_resume_short_circuits_without_rerunning_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Debate is the most expensive mode to re-run — N scopes × M rounds LLM
    calls + a summary call. Resume short-circuit is especially important here."""
    from donna.modes import debate as debate_mod

    core_calls: list = []

    async def _fake_debate_core(**kwargs):
        core_calls.append(kwargs)
        raise AssertionError("_debate_core must not run on resume")

    monkeypatch.setattr(debate_mod, "_debate_core", _fake_debate_core)

    payload = json.dumps({
        "scope_a": "author_twain", "scope_b": "orchestrator",
        "topic": "civilization", "rounds": 3,
    })
    jid = _queue_job(JobMode.DEBATE, task=payload, scope="orchestrator")
    prior_answer = "**Debate: author_twain vs orchestrator on civilization**\n\n...prior transcript..."
    _claim_and_set_done(jid, "test-worker", prior_answer,
                        JobMode.DEBATE, "orchestrator")

    async with JobContext.open(jid, worker_id="test-worker") as ctx:
        assert ctx is not None
        await debate_mod.run_debate_in_context(ctx)

    assert core_calls == [], "_debate_core must not run on resume"

    conn = connect()
    try:
        outbox = conn.execute(
            "SELECT text FROM outbox_updates WHERE job_id = ?", (jid,),
        ).fetchone()
        job_row = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert outbox is not None
    assert "Debate: author_twain vs orchestrator" in outbox["text"]
    assert job_row["status"] == JobStatus.DONE.value
