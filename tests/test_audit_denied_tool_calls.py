"""Cross-vendor review: GPT-5.3-codex RF5 (net-new finding).

When a tool call is rejected (consent denied, tool not registered, or
not in the scope's allowlist), `JobContext._execute_one` returned an
error block to the model but did NOT insert a row into `tool_calls`.
Operators couldn't audit attempted bypasses — adversarial probes were
invisible in `botctl traces` + the watchdog.

Fix: `_audit_rejection` persists a row at each of the three rejection
paths with a status that distinguishes the case:

  - "unknown_tool"     — model called something not in REGISTRY
  - "not_allowlisted"  — tool exists but not in agents set for scope
  - "denied:<reason>"  — consent gate said no (timeout / explicit no /
                          lease_lost)

These tests pin each path against regressions.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from donna.agent.context import JobContext
from donna.memory import tool_calls as tool_calls_mod
from donna.memory.db import connect, transaction
from donna.types import JobMode, JobState


def _ctx_for_audit(scope: str = "any_scope") -> JobContext:
    """Build a JobContext-shaped object for the audit-rejection helper.
    Only `_audit_rejection` is exercised; the rest of JobContext (DB
    plumbing, lease, etc.) isn't touched."""
    state = JobState(job_id="job_audit_test", agent_scope=scope, mode=JobMode.CHAT)
    job = SimpleNamespace(
        id="job_audit_test", agent_scope=scope, task="t",
        mode=JobMode.CHAT, thread_id=None,
    )
    return SimpleNamespace(
        state=state, job=job, worker_id="w_test",
        # The real method is on JobContext, but we duck-type by binding
        # the unbound function to our SimpleNamespace.
        _audit_rejection=JobContext._audit_rejection,
    )


def _seed_job(jid: str = "job_audit_test") -> None:
    """Insert a real jobs row so the FK from tool_calls.job_id resolves."""
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO jobs (id, task, agent_scope, mode, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (jid, "audit_test", "any_scope", "chat", "queued"),
            )
    finally:
        conn.close()


@pytest.mark.usefixtures("fresh_db")
def test_audit_rejection_inserts_unknown_tool_row() -> None:
    _seed_job()
    ctx = _ctx_for_audit()
    ctx._audit_rejection(ctx, "evil_tool", {"x": 1},
                         "unknown_tool", "tool evil_tool not registered")

    conn = connect()
    try:
        rows = tool_calls_mod.tool_calls_for(conn, "job_audit_test")
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["tool_name"] == "evil_tool"
    assert rows[0]["status"] == "unknown_tool"
    assert "not registered" in (rows[0]["error"] or "")


@pytest.mark.usefixtures("fresh_db")
def test_audit_rejection_inserts_not_allowlisted_row() -> None:
    _seed_job()
    ctx = _ctx_for_audit(scope="restricted_scope")
    ctx._audit_rejection(ctx, "exec_py", {"code": "print(1)"},
                         "not_allowlisted",
                         "tool exec_py not allowed for scope restricted_scope")

    conn = connect()
    try:
        rows = tool_calls_mod.tool_calls_for(conn, "job_audit_test")
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["tool_name"] == "exec_py"
    assert rows[0]["status"] == "not_allowlisted"


@pytest.mark.usefixtures("fresh_db")
def test_audit_rejection_inserts_denied_row_with_reason() -> None:
    _seed_job()
    ctx = _ctx_for_audit()
    ctx._audit_rejection(ctx, "save_artifact", {"name": "x"},
                         "denied:user_no", "user declined (user_no)")

    conn = connect()
    try:
        rows = tool_calls_mod.tool_calls_for(conn, "job_audit_test")
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["status"] == "denied:user_no"
    assert "declined" in (rows[0]["error"] or "")


@pytest.mark.usefixtures("fresh_db")
def test_audit_rejection_swallows_db_errors_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Audit logging is best-effort — a DB error must not break the agent
    loop's rejection path. The helper logs and returns."""
    ctx = _ctx_for_audit()

    def _exploding_insert(*a, **kw):
        raise RuntimeError("simulated DB failure")
    monkeypatch.setattr(tool_calls_mod, "insert_tool_call", _exploding_insert)

    # Must not raise
    ctx._audit_rejection(ctx, "anything", {}, "unknown_tool", "not registered")


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_execute_one_audits_unknown_tool_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end through `_execute_one`: a model that calls a tool not
    in REGISTRY should produce an audit row + an error tool_result.
    Pre-fix only the tool_result was returned — no audit."""
    import types

    from donna.agent import context as ctx_mod
    _seed_job()

    state = JobState(job_id="job_audit_test", agent_scope="any_scope",
                     mode=JobMode.CHAT)
    job = SimpleNamespace(
        id="job_audit_test", agent_scope="any_scope", task="t",
        mode=JobMode.CHAT, thread_id=None,
    )
    fake_ctx = SimpleNamespace(
        state=state, job=job, worker_id="w_test",
    )
    # Bind the unbound method to fake_ctx so `self._audit_rejection(...)`
    # inside _execute_one passes self correctly.
    fake_ctx._audit_rejection = types.MethodType(
        ctx_mod.JobContext._audit_rejection, fake_ctx,
    )

    res = await ctx_mod.JobContext._execute_one(
        fake_ctx, {"id": "tu1", "name": "ghost_tool", "input": {}},
    )
    assert res["is_error"] is True
    assert "not registered" in res["content"]

    conn = connect()
    try:
        rows = tool_calls_mod.tool_calls_for(conn, "job_audit_test")
    finally:
        conn.close()
    assert any(r["tool_name"] == "ghost_tool" and r["status"] == "unknown_tool"
               for r in rows), rows
