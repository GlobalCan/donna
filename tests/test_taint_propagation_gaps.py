"""Taint-propagation completeness — Codex adversarial scan #6.

Two bugs fixed:

1. `recall` returned `{"results": [{..., tainted: True}, ...]}` with the taint
   flag nested inside each result. `JobContext._execute_one` only checked
   `result.get("tainted")` at the top level, so a tainted fact retrieved via
   `recall` did NOT propagate onto the job. The model could then `remember`
   or `run_python` without the usual tainted-job escalation.

2. `TAINT_ESCALATED_TOOLS` was missing `teach` and `propose_heuristic`. A
   tainted job could silently write to the corpus or propose a reasoning
   rule without the "always confirm" gate firing.
"""
from __future__ import annotations

import pytest

from donna.memory import facts as facts_mod
from donna.memory.db import connect, transaction
from donna.security.taint import TAINT_ESCALATED_TOOLS, effective_confirmation
from donna.tools import memory as memory_tool
from donna.types import ConfirmationMode, ToolEntry

# ---------- Rule 2.1 — recall surfaces top-level taint ---------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_recall_exposes_top_level_tainted_when_any_match_is_tainted() -> None:
    conn = connect()
    try:
        with transaction(conn):
            facts_mod.insert_fact(
                conn, fact="Clean fact about espresso", tags="beverage",
                agent_scope="orchestrator", tainted=False,
            )
            facts_mod.insert_fact(
                conn, fact="Tainted fact about espresso from a fetched page",
                tags="beverage",
                agent_scope="orchestrator", tainted=True,
            )
    finally:
        conn.close()

    out = await memory_tool.recall(query="espresso", agent_scope="orchestrator")
    # Both matched (implicit AND on "espresso") — the tainted one surfaces the flag
    assert out["count"] >= 1
    assert out.get("tainted") is True, (
        "recall must set top-level tainted=True when any result is tainted "
        "so JobContext._execute_one propagates taint onto the job"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_recall_does_not_taint_when_all_results_clean() -> None:
    conn = connect()
    try:
        with transaction(conn):
            facts_mod.insert_fact(
                conn, fact="Clean fact about coffee", tags="beverage",
                agent_scope="orchestrator", tainted=False,
            )
    finally:
        conn.close()

    out = await memory_tool.recall(query="coffee", agent_scope="orchestrator")
    assert out["count"] == 1
    assert out.get("tainted") is False


# ---------- Rule 3 — escalated-tools set includes durable writes -----------


def _entry(name: str, confirmation: ConfirmationMode) -> ToolEntry:
    return ToolEntry(
        name=name,
        fn=None,  # type: ignore[arg-type]
        schema={},
        description="",
        scope="write_knowledge",
        cost="medium",
        confirmation=confirmation,
        taints_job=False,
        idempotent=True,
        agents=("*",),
    )


def test_teach_is_in_taint_escalated_tools() -> None:
    assert "teach" in TAINT_ESCALATED_TOOLS


def test_propose_heuristic_is_in_taint_escalated_tools() -> None:
    assert "propose_heuristic" in TAINT_ESCALATED_TOOLS


def test_teach_escalates_to_always_when_job_tainted() -> None:
    entry = _entry("teach", ConfirmationMode.ONCE_PER_JOB)
    assert effective_confirmation(entry, job_tainted=True) == ConfirmationMode.ALWAYS
    assert effective_confirmation(entry, job_tainted=False) == ConfirmationMode.ONCE_PER_JOB


def test_propose_heuristic_escalates_to_always_when_job_tainted() -> None:
    entry = _entry("propose_heuristic", ConfirmationMode.NEVER)
    # `never` normally → must escalate to `always` under taint
    assert effective_confirmation(entry, job_tainted=True) == ConfirmationMode.ALWAYS
    assert effective_confirmation(entry, job_tainted=False) == ConfirmationMode.NEVER
