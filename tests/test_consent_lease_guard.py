"""Consent lease-guard — Codex adversarial scan #8.

`_persist_pending` writes to `pending_consents` + flips `jobs.status` without
checking the caller still owns the job. Failure mode: a stale worker (lease
expired, another worker claimed the job) executes a tool, reaches the consent
check, and inserts a spurious pending row + resets the status of a job the
new owner is actively running.

Fix: pass worker_id through consent.check → _persist_pending, and guard both
writes on `jobs.owner = ?`. On mismatch, skip the writes and return None;
consent.check surfaces ConsentResult(approved=False, reason="lease_lost").
"""
from __future__ import annotations

import pytest

from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction
from donna.security.consent import (
    _persist_pending,
)
from donna.security.consent import (
    check as consent_check,
)
from donna.types import (
    ConfirmationMode,
    JobMode,
    JobStatus,
    ToolEntry,
)


def _entry() -> ToolEntry:
    return ToolEntry(
        name="run_python",
        fn=None,  # type: ignore[arg-type]
        schema={},
        description="",
        scope="exec_code",
        cost="medium",
        confirmation=ConfirmationMode.ALWAYS,
        taints_job=False,
        idempotent=False,
        agents=("*",),
    )


def _seed_owned_job(owner: str) -> str:
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="test", agent_scope="orchestrator", mode=JobMode.CHAT,
            )
        claimed = jobs_mod.claim_next_queued(conn, worker_id=owner)
        assert claimed is not None and claimed.id == jid
    finally:
        conn.close()
    return jid


def _read_job(jid: str) -> dict:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
    finally:
        conn.close()
    return dict(row)


def _pending_count(jid: str) -> int:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM pending_consents WHERE job_id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    return int(row["n"])


# ---------- _persist_pending direct tests -----------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_persist_pending_inserts_when_owner_matches() -> None:
    jid = _seed_owned_job(owner="worker-A")
    pid = _persist_pending(
        job_id=jid, tool_name="run_python", arguments={"code": "x"},
        tainted=False, worker_id="worker-A",
    )
    assert pid is not None
    assert _pending_count(jid) == 1
    assert _read_job(jid)["status"] == JobStatus.PAUSED_AWAITING_CONSENT.value


@pytest.mark.usefixtures("fresh_db")
def test_persist_pending_skips_when_owner_mismatch() -> None:
    """Stale worker (lost lease to worker-B) tries to persist under worker-A's
    identity. Must skip both writes and return None so the caller can bail."""
    jid = _seed_owned_job(owner="worker-B")  # job is owned by B
    pid = _persist_pending(
        job_id=jid, tool_name="run_python", arguments={"code": "x"},
        tainted=False, worker_id="worker-A",  # we pretend to be A
    )
    assert pid is None
    assert _pending_count(jid) == 0, "no spurious consent row for the other owner"
    # jobs.status should still be 'running' — we didn't corrupt state
    assert _read_job(jid)["status"] == JobStatus.RUNNING.value


@pytest.mark.usefixtures("fresh_db")
def test_persist_pending_skips_when_job_missing() -> None:
    pid = _persist_pending(
        job_id="job_nonexistent", tool_name="run_python", arguments={},
        tainted=False, worker_id="worker-A",
    )
    assert pid is None


@pytest.mark.usefixtures("fresh_db")
def test_persist_pending_without_worker_id_still_works() -> None:
    """Backcompat: callers not passing worker_id get the old behavior
    (insert + flip, no ownership check). Used by tests and any legacy path."""
    jid = _seed_owned_job(owner="worker-A")
    pid = _persist_pending(
        job_id=jid, tool_name="run_python", arguments={},
        tainted=False, worker_id=None,
    )
    assert pid is not None
    assert _pending_count(jid) == 1


# ---------- consent.check integration tests ---------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_consent_check_returns_lease_lost_when_stale() -> None:
    """Stale worker calls consent.check for a job now owned elsewhere.
    Result: approved=False, reason='lease_lost', no pending row written."""
    jid = _seed_owned_job(owner="worker-B")

    result = await consent_check(
        job_id=jid, entry=_entry(), arguments={"code": "x"},
        tainted=False, worker_id="worker-A",  # we're the stale worker
    )

    assert result.approved is False
    assert result.reason == "lease_lost"
    assert _pending_count(jid) == 0
