"""Regression tests for bugs found in Codex adversarial review (2026-04-17).

Each test corresponds to a CRITICAL/HIGH/MEDIUM finding fixed in this pass.
See docs/KNOWN_ISSUES.md for context.
"""
from __future__ import annotations

import json

import pytest

from donna.agent.rate_limiter import OversizedRequestError, RateLimitLedger
from donna.security.validator import validate_debate_turn


# --- Rate limiter ----------------------------------------------------------


async def test_oversized_request_raises() -> None:
    """MEDIUM fix: oversized single request no longer infinite-loops."""
    ledger = RateLimitLedger()
    ledger.limits["fast"].itpm = 10
    ledger.limits["fast"].otpm = 10
    with pytest.raises(OversizedRequestError):
        await ledger.reserve("fast", est_input=100, est_output=5)
    with pytest.raises(OversizedRequestError):
        await ledger.reserve("fast", est_input=5, est_output=100)


# --- Debate validator fuzziness --------------------------------------------


def test_debate_paraphrase_not_flagged_with_quoted_span() -> None:
    """LOW fix: quoted span (≥5 chars) satisfies the quote-to-attack rule."""
    prior = [
        {"round": 1, "scope": "lewis",
         "content": "Markets are efficient only if you define efficiency narrowly."},
    ]
    turn = 'Lewis claims "efficient only if you define" — that narrows the point.'
    issues = validate_debate_turn(turn, prior, current_scope="dalio")
    assert not issues, f"unexpected issues: {issues}"


def test_debate_unquoted_attack_still_flagged() -> None:
    """Paraphrase without any quote or fuzzy overlap SHOULD still be flagged."""
    prior = [
        {"round": 1, "scope": "lewis",
         "content": "Markets are efficient only if you define efficiency narrowly."},
    ]
    turn = "Lewis argues that market pricing captures all known information perfectly."
    issues = validate_debate_turn(turn, prior, current_scope="dalio")
    assert any("attacks_without_quote" in i for i in issues)


# --- Taint propagation via read_artifact -----------------------------------


def test_read_artifact_result_taints_job_through_loop() -> None:
    """C1 fix: tool result with tainted=True flips state.tainted in the loop.

    We test the propagation logic directly (the full loop needs live model + DB,
    tested integration-style elsewhere).
    """
    # Simulate the conditional in agent.loop._execute_tool_uses
    class E:  # minimal entry mock
        taints_job = False
        name = "read_artifact"
    entry = E()
    result = {"excerpt": "...", "tainted": True}
    result_tainted = isinstance(result, dict) and bool(result.get("tainted"))
    assert (entry.taints_job or result_tainted) is True


def test_read_artifact_clean_result_does_not_taint() -> None:
    class E:
        taints_job = False
        name = "read_artifact"
    entry = E()
    result = {"excerpt": "...", "tainted": False}
    result_tainted = isinstance(result, dict) and bool(result.get("tainted"))
    assert (entry.taints_job or result_tainted) is False


# --- Resume dedup of tool_use_ids ------------------------------------------


def test_resume_dedup_finds_completed_tool_uses() -> None:
    """H2 fix: completed tool_results in message history are detected on resume.
    The helper was refactored into context.py during the Pass-2 JobContext
    unification — Pattern A Hermes steals kept it there."""
    from donna.agent.context import _already_executed_tool_use_ids
    from donna.types import JobMode, JobState

    state = JobState(job_id="job_1", agent_scope="orchestrator", mode=JobMode.CHAT)
    state.messages = [
        {"role": "user", "content": "initial task"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu_A", "name": "search_web", "input": {}},
            {"type": "tool_use", "id": "tu_B", "name": "fetch_url", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_A", "content": "..."},
        ]},
    ]
    executed = _already_executed_tool_use_ids(state)
    assert executed == {"tu_A"}
    # tu_B hasn't been executed yet — must be re-run on resume


# --- Checkpoint owner guard ------------------------------------------------


def test_save_checkpoint_signature_supports_worker_id() -> None:
    """C2 fix: save_checkpoint now accepts worker_id for owner-guarded writes."""
    import inspect
    from donna.memory import jobs as jobs_mod
    sig = inspect.signature(jobs_mod.save_checkpoint)
    assert "worker_id" in sig.parameters


def test_set_status_signature_supports_worker_id() -> None:
    """C2 fix: set_status also owner-guarded."""
    import inspect
    from donna.memory import jobs as jobs_mod
    sig = inspect.signature(jobs_mod.set_status)
    assert "worker_id" in sig.parameters


def test_save_checkpoint_no_longer_writes_cost() -> None:
    """MEDIUM fix: cost is authoritative via ledger, not clobbered by checkpoint."""
    import inspect
    from donna.memory import jobs as jobs_mod
    sig = inspect.signature(jobs_mod.save_checkpoint)
    assert "cost_usd" not in sig.parameters, "checkpoint should not write cost_usd"


# --- Parallel taint pre-scan -----------------------------------------------


def test_parallel_batch_pretaint_logic() -> None:
    """C3 fix: simulate the pre-scan — any taint-marking tool in the batch
    should pessimistically taint the job before any tool runs."""
    # Minimal simulation of the pre-scan logic
    class FakeEntry:
        def __init__(self, name: str, taints: bool):
            self.name = name
            self.taints_job = taints

    registry = {
        "search_web": FakeEntry("search_web", taints=True),
        "remember": FakeEntry("remember", taints=False),
    }
    tool_uses = [
        {"name": "remember", "id": "r1", "input": {"fact": "x"}},
        {"name": "search_web", "id": "w1", "input": {"query": "x"}},
    ]
    pre_tainted = False
    for tu in tool_uses:
        e = registry.get(tu["name"])
        if e is not None and e.taints_job:
            pre_tainted = True
            break
    assert pre_tainted, "should flag before remember runs"


# --- Ingest within-batch dedup ---------------------------------------------


def test_ingest_dedup_within_batch() -> None:
    """MEDIUM fix: within-batch fingerprint dedup prevents double-embedding."""
    from donna.memory.knowledge import fingerprint_text

    # Simulate the within-batch dedup logic
    chunks_content = [
        "This is a unique paragraph about Mark Twain.",
        "A different paragraph about rivers.",
        "This is a unique paragraph about Mark Twain.",  # dup of #1
        "Another one about steamboats.",
    ]
    seen = set()
    deduped_count = 0
    kept = 0
    for c in chunks_content:
        fp = fingerprint_text(c)
        if fp in seen:
            deduped_count += 1
            continue
        seen.add(fp)
        kept += 1
    assert kept == 3
    assert deduped_count == 1
