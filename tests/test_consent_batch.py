"""Consent batching — v0.7.3 / Track A.3 / Codex #11 (operator fatigue).

When the agent emits 2+ fresh consent-required tools in one model turn,
the batch path collapses N prompts into one merged Block Kit prompt with
Approve-All / Decline-All / Show-Details actions.

These tests cover:

- Schema shape (pending_consents.batch_id, consent_batches table)
- create_batch owner-guard (matches _persist_pending semantics)
- resolve_batch cascade to all linked pending rows
- expand_batch unlinks rows so the legacy single-tool drain takes over
- JobContext.tool_step pre-scan: 0/1 fresh consent → no batch; 2+ → batch
- Once_per_job grant skips a tool from the batch
- NEVER-mode tools never participate in the batch
- backwards-compat: legacy single-tool consent path unchanged
"""
from __future__ import annotations

import pytest

from donna.memory import jobs as jobs_mod
from donna.memory import permissions as perm_mod
from donna.memory.db import connect, transaction
from donna.security.consent_batch import (
    BATCH_APPROVED_INDIVIDUAL,
    create_batch,
    expand_batch,
    get_batch,
    list_unposted_batches,
    load_batch_members,
    mark_batch_posted,
    resolve_batch,
)
from donna.types import (
    ConfirmationMode,
    JobMode,
    JobStatus,
    ToolEntry,
)


def _entry(
    name: str = "fake_tool",
    *,
    confirmation: ConfirmationMode = ConfirmationMode.ALWAYS,
    taints_job: bool = False,
) -> ToolEntry:
    return ToolEntry(
        name=name,
        fn=None,  # type: ignore[arg-type]
        schema={},
        description="",
        scope="write",
        cost="low",
        confirmation=confirmation,
        taints_job=taints_job,
        idempotent=False,
        agents=("*",),
    )


def _seed_owned_job(owner: str = "worker-A") -> str:
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="t", agent_scope="orchestrator",
                mode=JobMode.CHAT,
            )
        claimed = jobs_mod.claim_next_queued(conn, worker_id=owner)
        assert claimed is not None and claimed.id == jid
    finally:
        conn.close()
    return jid


def _read_job(jid: str) -> dict:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row)


def _pending_rows(jid: str) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM pending_consents WHERE job_id = ? "
            "ORDER BY created_at, id",
            (jid,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ---------- schema --------------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_pending_consents_has_batch_id_column() -> None:
    """0014 must have added the batch_id column to pending_consents."""
    conn = connect()
    try:
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(pending_consents)"
        ).fetchall()}
    finally:
        conn.close()
    assert "batch_id" in cols, (
        "0014 should add batch_id to pending_consents"
    )


@pytest.mark.usefixtures("fresh_db")
def test_consent_batches_table_exists() -> None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'consent_batches'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "0014 should create consent_batches table"


# ---------- create_batch --------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_create_batch_inserts_one_batch_and_n_pendings() -> None:
    jid = _seed_owned_job(owner="worker-A")
    members = [
        (_entry("fake_save_a"), {"path": "a.txt"}),
        (_entry("fake_save_b"), {"path": "b.txt"}),
        (_entry("fake_teach"), {"fact": "the sky is blue"}),
    ]
    result = create_batch(
        job_id=jid, worker_id="worker-A", members=members,
        job_tainted=False,
    )
    assert result is not None
    batch_id, pending_ids = result
    assert batch_id.startswith("cb_")
    assert len(pending_ids) == 3
    assert all(p.startswith("pend_") for p in pending_ids)

    rows = _pending_rows(jid)
    assert len(rows) == 3
    for row in rows:
        assert row["batch_id"] == batch_id
        assert row["approved"] is None

    # Job gets paused awaiting consent — same as the per-tool path.
    assert (
        _read_job(jid)["status"]
        == JobStatus.PAUSED_AWAITING_CONSENT.value
    )


@pytest.mark.usefixtures("fresh_db")
def test_create_batch_requires_at_least_two_members() -> None:
    """Single-member batches don't earn the batch path's overhead;
    callers should fall back to the legacy single-tool consent.check."""
    jid = _seed_owned_job()
    with pytest.raises(ValueError, match=">= 2"):
        create_batch(
            job_id=jid, worker_id="worker-A",
            members=[(_entry(), {})],
            job_tainted=False,
        )


@pytest.mark.usefixtures("fresh_db")
def test_create_batch_owner_guard_blocks_stale_worker() -> None:
    """Stale worker (lost lease) calling create_batch must NOT poison
    state — same semantic as the per-tool _persist_pending guard."""
    jid = _seed_owned_job(owner="worker-B")
    members = [
        (_entry("fake_save_a"), {"i": 1}),
        (_entry("fake_save_b"), {"i": 2}),
    ]
    result = create_batch(
        job_id=jid, worker_id="worker-A",  # stale!
        members=members, job_tainted=False,
    )
    assert result is None, "stale worker must not create a batch"
    assert _pending_rows(jid) == []
    # And the job must still be 'running' — we didn't corrupt state.
    assert _read_job(jid)["status"] == JobStatus.RUNNING.value


@pytest.mark.usefixtures("fresh_db")
def test_create_batch_taint_propagates_to_batch_row() -> None:
    """Batch is tainted if the job is tainted at batch-creation time
    (matches the per-tool render's icon choice)."""
    jid = _seed_owned_job()
    result = create_batch(
        job_id=jid, worker_id="worker-A",
        members=[
            (_entry("fake_save_a"), {"i": 1}),
            (_entry("fake_save_b"), {"i": 2}),
        ],
        job_tainted=True,
    )
    assert result is not None
    batch_id, _ = result
    batch = get_batch(batch_id)
    assert batch is not None
    assert batch["tainted"] == 1


# ---------- resolve_batch -------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_resolve_batch_approves_all_linked_rows() -> None:
    jid = _seed_owned_job()
    result = create_batch(
        job_id=jid, worker_id="worker-A",
        members=[
            (_entry("fake_a"), {"i": 1}),
            (_entry("fake_b"), {"i": 2}),
        ],
        job_tainted=False,
    )
    assert result is not None
    batch_id, pending_ids = result

    assert resolve_batch(batch_id=batch_id, approved=1) is True
    rows = _pending_rows(jid)
    assert all(r["approved"] == 1 for r in rows)
    assert all(r["decided_at"] is not None for r in rows)


@pytest.mark.usefixtures("fresh_db")
def test_resolve_batch_idempotent_on_double_click() -> None:
    """A double-click resolves once; the second call is a no-op."""
    jid = _seed_owned_job()
    result = create_batch(
        job_id=jid, worker_id="worker-A",
        members=[
            (_entry(), {"i": 1}),
            (_entry(), {"i": 2}),
        ],
        job_tainted=False,
    )
    assert result is not None
    batch_id, _ = result
    assert resolve_batch(batch_id=batch_id, approved=1) is True
    assert resolve_batch(batch_id=batch_id, approved=0) is False


@pytest.mark.usefixtures("fresh_db")
def test_resolve_batch_declines_cascade_to_all_rows() -> None:
    jid = _seed_owned_job()
    result = create_batch(
        job_id=jid, worker_id="worker-A",
        members=[
            (_entry(), {"i": 1}),
            (_entry(), {"i": 2}),
            (_entry(), {"i": 3}),
        ],
        job_tainted=False,
    )
    assert result is not None
    batch_id, _ = result
    assert resolve_batch(batch_id=batch_id, approved=0) is True
    rows = _pending_rows(jid)
    assert all(r["approved"] == 0 for r in rows)


@pytest.mark.usefixtures("fresh_db")
def test_resolve_batch_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="0 or 1"):
        resolve_batch(batch_id="cb_ignored", approved=99)


# ---------- expand_batch --------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_expand_batch_unlinks_rows_for_legacy_drain() -> None:
    """expand_batch flips approved=2 (sentinel) and clears batch_id from
    every linked pending row, so the legacy per-tool drainer takes over."""
    jid = _seed_owned_job()
    result = create_batch(
        job_id=jid, worker_id="worker-A",
        members=[
            (_entry(), {"i": 1}),
            (_entry(), {"i": 2}),
        ],
        job_tainted=False,
    )
    assert result is not None
    batch_id, _ = result

    assert expand_batch(batch_id=batch_id) is True
    batch = get_batch(batch_id)
    assert batch is not None
    assert batch["approved"] == BATCH_APPROVED_INDIVIDUAL

    # All member rows must have batch_id cleared and remain undecided.
    rows = _pending_rows(jid)
    for r in rows:
        assert r["batch_id"] is None
        assert r["approved"] is None


@pytest.mark.usefixtures("fresh_db")
def test_expand_batch_idempotent() -> None:
    jid = _seed_owned_job()
    result = create_batch(
        job_id=jid, worker_id="worker-A",
        members=[(_entry(), {"i": 1}), (_entry(), {"i": 2})],
        job_tainted=False,
    )
    assert result is not None
    batch_id, _ = result
    assert expand_batch(batch_id=batch_id) is True
    assert expand_batch(batch_id=batch_id) is False


# ---------- list_unposted_batches / load_batch_members --------------------


@pytest.mark.usefixtures("fresh_db")
def test_list_unposted_batches_returns_only_pending() -> None:
    """Batches that are decided OR posted should be filtered out so the
    drainer doesn't re-post them."""
    jid = _seed_owned_job()
    result = create_batch(
        job_id=jid, worker_id="worker-A",
        members=[(_entry(), {"i": 1}), (_entry(), {"i": 2})],
        job_tainted=False,
    )
    assert result is not None
    batch_id_1, _ = result

    # Second batch will be posted; should not appear in the unposted list.
    jid2 = _seed_owned_job(owner="worker-A2")
    result2 = create_batch(
        job_id=jid2, worker_id="worker-A2",
        members=[(_entry(), {"i": 1}), (_entry(), {"i": 2})],
        job_tainted=False,
    )
    assert result2 is not None
    batch_id_2, _ = result2
    mark_batch_posted(
        batch_id=batch_id_2, channel_id="C123", message_id="msg.001",
    )

    unposted = list_unposted_batches()
    ids = {b["id"] for b in unposted}
    assert batch_id_1 in ids
    assert batch_id_2 not in ids


@pytest.mark.usefixtures("fresh_db")
def test_load_batch_members_returns_rows_in_insertion_order() -> None:
    jid = _seed_owned_job()
    result = create_batch(
        job_id=jid, worker_id="worker-A",
        members=[
            (_entry("a"), {"i": 1}),
            (_entry("b"), {"i": 2}),
            (_entry("c"), {"i": 3}),
        ],
        job_tainted=False,
    )
    assert result is not None
    batch_id, _ = result
    members = load_batch_members(batch_id)
    assert [m["tool_name"] for m in members] == ["a", "b", "c"]


# ---------- JobContext.tool_step pre-scan -------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_tool_step_no_batch_for_single_consent_tool() -> None:
    """Single consent-required tool in the batch must NOT create a
    consent_batches row — backwards-compatible legacy path only."""
    from donna.tools.registry import REGISTRY

    REGISTRY["only_one"] = _entry("only_one")
    REGISTRY["free_lunch"] = _entry(
        "free_lunch", confirmation=ConfirmationMode.NEVER,
    )
    try:
        jid = _seed_owned_job()
        from donna.agent.context import JobContext
        from donna.memory.jobs import get_job

        conn = connect()
        try:
            job = get_job(conn, jid)
        finally:
            conn.close()
        assert job is not None
        ctx = JobContext(job, worker_id="worker-A")
        # Two fresh tools but only one needs consent → no batch
        prebatch = ctx._maybe_create_batch([
            {"id": "tu1", "name": "only_one", "input": {}},
            {"id": "tu2", "name": "free_lunch", "input": {}},
        ])
        assert prebatch == {}, (
            "single-consent batches must not create a consent_batches row"
        )
        # Confirm no batch row exists.
        conn = connect()
        try:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM consent_batches"
            ).fetchone()["n"]
        finally:
            conn.close()
        assert n == 0
    finally:
        REGISTRY.pop("only_one", None)
        REGISTRY.pop("free_lunch", None)


@pytest.mark.usefixtures("fresh_db")
def test_tool_step_creates_batch_for_two_plus_consent_tools() -> None:
    """When ≥2 fresh tools each need a fresh consent prompt, a batch row
    is created and the per-tool pending rows are linked to it."""
    from donna.agent.context import JobContext
    from donna.memory.jobs import get_job
    from donna.tools.registry import REGISTRY

    REGISTRY["fake_save"] = _entry("fake_save")
    REGISTRY["fake_teach"] = _entry("fake_teach")
    try:
        jid = _seed_owned_job()
        conn = connect()
        try:
            job = get_job(conn, jid)
        finally:
            conn.close()
        assert job is not None
        ctx = JobContext(job, worker_id="worker-A")
        prebatch = ctx._maybe_create_batch([
            {"id": "tu1", "name": "fake_save", "input": {"path": "a"}},
            {"id": "tu2", "name": "fake_teach", "input": {"fact": "x"}},
        ])
        assert set(prebatch.keys()) == {"tu1", "tu2"}
        # Confirm one batch + two linked pending rows.
        conn = connect()
        try:
            n_batches = conn.execute(
                "SELECT COUNT(*) AS n FROM consent_batches"
            ).fetchone()["n"]
            n_linked = conn.execute(
                "SELECT COUNT(*) AS n FROM pending_consents "
                "WHERE batch_id IS NOT NULL"
            ).fetchone()["n"]
        finally:
            conn.close()
        assert n_batches == 1
        assert n_linked == 2
    finally:
        REGISTRY.pop("fake_save", None)
        REGISTRY.pop("fake_teach", None)


@pytest.mark.usefixtures("fresh_db")
def test_tool_step_skips_once_per_job_with_existing_grant() -> None:
    """A ONCE_PER_JOB tool that already has a job-scope grant must not
    enter the batch (the grant satisfies the consent requirement)."""
    from donna.agent.context import JobContext
    from donna.memory.jobs import get_job
    from donna.tools.registry import REGISTRY

    REGISTRY["fake_granted"] = _entry(
        "fake_granted", confirmation=ConfirmationMode.ONCE_PER_JOB,
    )
    REGISTRY["fake_save"] = _entry("fake_save")
    REGISTRY["fake_teach"] = _entry("fake_teach")
    try:
        jid = _seed_owned_job()
        # Pre-existing grant for fake_granted
        conn = connect()
        try:
            with transaction(conn):
                perm_mod.insert_grant(
                    conn, job_id=jid, tool_name="fake_granted", scope="job",
                )
            job = get_job(conn, jid)
        finally:
            conn.close()
        assert job is not None
        ctx = JobContext(job, worker_id="worker-A")
        prebatch = ctx._maybe_create_batch([
            {"id": "tu0", "name": "fake_granted", "input": {}},  # skipped
            {"id": "tu1", "name": "fake_save", "input": {}},
            {"id": "tu2", "name": "fake_teach", "input": {}},
        ])
        # Only the two ALWAYS tools should be batched.
        assert set(prebatch.keys()) == {"tu1", "tu2"}
    finally:
        REGISTRY.pop("fake_granted", None)
        REGISTRY.pop("fake_save", None)
        REGISTRY.pop("fake_teach", None)


# ---------- backwards compat ----------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_legacy_single_tool_consent_unchanged() -> None:
    """Smoke: the original consent.check path still inserts one
    pending_consents row with batch_id=NULL and polls it. Codex
    backwards-compat constraint."""
    from donna.security.consent import _persist_pending

    jid = _seed_owned_job()
    pid = _persist_pending(
        job_id=jid, tool_name="only_one", arguments={"x": 1},
        tainted=False, worker_id="worker-A",
    )
    assert pid is not None
    rows = _pending_rows(jid)
    assert len(rows) == 1
    assert rows[0]["batch_id"] is None
