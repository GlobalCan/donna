"""Debate payload robustness: empty / None / non-string scope entries drop.

Without this filter, a payload with `scope_a=""` or `scope_b=None` would
slip past the `len(scopes) < 2` guard in `_debate_core` — that guard
counts list length, not semantic validity. The debate would then run
with `retrieve_knowledge(scope="")` returning empty chunks, and the
model would debate without any corpus grounding (low-quality failure
mode that LOOKS like a valid debate).

These tests pin the behavior:
- Empty / whitespace-only / None / non-string scopes are dropped
- If fewer than 2 valid scopes survive filtering, `_debate_core` returns
  the `{"error": ...}` shape that the mode's finalize delivers
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction
from donna.modes import debate as debate_mod
from donna.types import JobMode


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_empty_scopes_are_dropped_before_debate_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def _spy_core(*, ctx, topic, scopes, rounds):
        captured["scopes"] = scopes
        return {"error": "stopping here"}

    monkeypatch.setattr(debate_mod, "_debate_core", _spy_core)

    task = json.dumps({
        "scope_a": "author_twain",
        "scope_b": "",  # empty — must be dropped
        "scope_c": "   ",  # whitespace — must be dropped
        "scope_d": "orchestrator",
        "topic": "x",
        "rounds": 2,
    })

    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task=task, agent_scope="orchestrator", mode=JobMode.DEBATE,
            )
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                ("w1", jid),
            )
            from donna.types import JobState
            state = JobState(
                job_id=jid, agent_scope="orchestrator", mode=JobMode.DEBATE,
            )
            conn.execute(
                "UPDATE jobs SET checkpoint_state = ? WHERE id = ?",
                (json.dumps(state.to_dict()), jid),
            )
    finally:
        conn.close()

    from donna.agent.context import JobContext
    async with JobContext.open(jid, worker_id="w1") as ctx:
        assert ctx is not None
        await debate_mod.run_debate_in_context(ctx)

    assert captured["scopes"] == ["author_twain", "orchestrator"], (
        f"expected filtered scopes, got {captured['scopes']!r}"
    )


@pytest.mark.asyncio
async def test_non_string_scopes_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scopes of wrong type (None, int, list) dropped silently. Json parse
    can produce any of these if the caller is misbehaving."""
    captured: dict = {}

    async def _spy_core(*, ctx, topic, scopes, rounds):
        captured["scopes"] = scopes
        return {"error": "stop"}

    monkeypatch.setattr(debate_mod, "_debate_core", _spy_core)

    ctx = MagicMock()
    ctx.job.task = json.dumps({
        "scope_a": None,
        "scope_b": "author_twain",
        "scope_c": 42,
        "scope_d": ["nope"],
        "topic": "x",
        "rounds": 1,
    })
    ctx.job.agent_scope = "orchestrator"
    ctx.state.done = False

    # Mock the state setters so we can observe without a real JobContext lifecycle
    ctx.state.final_text = None
    ctx.checkpoint_or_raise = MagicMock()

    await debate_mod.run_debate_in_context(ctx)
    assert captured["scopes"] == ["author_twain"]


@pytest.mark.asyncio
async def test_all_invalid_scopes_produces_error_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When every scope is invalid, the survived scope list has 0 entries.
    _debate_core's `len(scopes) < 2` guard catches it and returns the
    error payload, which run_debate_in_context formats and finalize
    delivers. User sees the error, doesn't wait forever for an empty
    debate."""
    ctx = MagicMock()
    ctx.job.task = json.dumps({
        "scope_a": "",
        "scope_b": "   ",
        "topic": "x",
        "rounds": 1,
    })
    ctx.job.agent_scope = "orchestrator"
    ctx.state.done = False
    ctx.state.final_text = None
    ctx.checkpoint_or_raise = MagicMock()

    await debate_mod.run_debate_in_context(ctx)

    # ctx.state.final_text should contain an error message
    assert ctx.state.final_text is not None
    assert "error" in ctx.state.final_text.lower()


@pytest.mark.asyncio
async def test_agent_scope_default_for_scope_a_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If scope_a is missing entirely, payload.get falls back to
    ctx.job.agent_scope — must still be valid."""
    captured: dict = {}

    async def _spy_core(*, ctx, topic, scopes, rounds):
        captured["scopes"] = scopes
        return {"error": "stop"}

    monkeypatch.setattr(debate_mod, "_debate_core", _spy_core)

    ctx = MagicMock()
    ctx.job.task = json.dumps({
        "scope_b": "orchestrator",
        "topic": "x",
        "rounds": 1,
    })
    ctx.job.agent_scope = "author_twain"
    ctx.state.done = False
    ctx.state.final_text = None
    ctx.checkpoint_or_raise = MagicMock()

    await debate_mod.run_debate_in_context(ctx)
    assert captured["scopes"] == ["author_twain", "orchestrator"]
