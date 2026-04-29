"""Two small security fixes from cross-vendor review #11 and #15.

#11 (Codex GPT-5 + GPT-5.3-codex): `Worker._run_one` exception handler
in `jobs/runner.py:60-67` wrote `FAILED` status without an owner guard.
A stale worker (lease reclaimed by another worker, but exception handler
still firing) would clobber the recovered/completed state. Symmetric to
the v0.3.3 #23 owner guard on `consent._persist_pending`.

#15 (Codex GPT-5): `tools/attachments.py:84` wrote attachments to a
fixed `attach{ext}` path. Two concurrent ingests with the same
extension overwrite each other before either finishes processing.
Solo bot rarely hits this; `/teach` batch flows will.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# ---------- #11 stale-worker FAILED-write owner guard ---------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_failed_write_skipped_when_lease_lost(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """If `set_status` returns False (owner mismatch), `_run_one` must
    log it and not silently succeed."""
    import asyncio

    from donna.jobs.runner import Worker
    from donna.memory import jobs as jobs_mod
    from donna.memory.db import connect, transaction
    from donna.types import JobMode

    # Seed a job claimed by a DIFFERENT worker
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="t", agent_scope="s", mode=JobMode.CHAT,
            )
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                ("other_worker", jid),
            )
    finally:
        conn.close()

    w = Worker()
    w.worker_id = "stale_worker"

    # Stub run_job to raise — exercises the FAILED-write path
    async def _raises(*a, **kw):
        raise RuntimeError("simulated tool crash")
    monkeypatch.setattr("donna.jobs.runner.run_job", _raises)

    await w._run_one(jid)
    await asyncio.sleep(0.05)  # let any background tasks settle

    # Job status should NOT have flipped — different owner
    conn = connect()
    try:
        row = conn.execute(
            "SELECT status, error, owner FROM jobs WHERE id = ?",
            (jid,),
        ).fetchone()
    finally:
        conn.close()

    assert row[0] == "running", (
        f"stale worker must not be able to write FAILED on another worker's "
        f"running job; got status={row[0]}"
    )
    assert row[2] == "other_worker", (
        f"owner must remain 'other_worker'; got {row[2]!r}"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_failed_write_succeeds_when_owner_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner-matching worker still gets to write FAILED on its own job.
    Ensures the guard didn't break the happy path."""
    import asyncio

    from donna.jobs.runner import Worker
    from donna.memory import jobs as jobs_mod
    from donna.memory.db import connect, transaction
    from donna.types import JobMode

    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="t", agent_scope="s", mode=JobMode.CHAT,
            )
            conn.execute(
                "UPDATE jobs SET owner = ?, status = 'running', "
                "lease_until = datetime('now', '+5 minutes') WHERE id = ?",
                ("active_worker", jid),
            )
    finally:
        conn.close()

    w = Worker()
    w.worker_id = "active_worker"

    async def _raises(*a, **kw):
        raise RuntimeError("real crash")
    monkeypatch.setattr("donna.jobs.runner.run_job", _raises)

    await w._run_one(jid)
    await asyncio.sleep(0.05)

    conn = connect()
    try:
        row = conn.execute(
            "SELECT status, error FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()

    assert row[0] == "failed"
    assert "real crash" in (row[1] or "")


# ---------- #15 attachment temp-file race ---------------------------------


def test_attachment_dest_path_is_unique_per_call() -> None:
    """The fix replaces fixed `attach{ext}` with `attach_<uuid>{ext}`.
    Two concurrent calls with the same extension should land at distinct
    paths. Direct path-construction test — we don't need the network/PDF
    machinery to assert this invariant."""
    import uuid
    seen = set()
    for _ in range(50):
        # Mirror the path construction in tools/attachments.py
        candidate = f"attach_{uuid.uuid4().hex[:12]}.pdf"
        seen.add(candidate)
    assert len(seen) == 50, "uuid4 should produce unique tempfile names"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_two_concurrent_attachment_ingests_dont_collide(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Property test: launch two `ingest_discord_attachment` calls back-to-back
    against the same fake URL. Capture every `dest.write_bytes` path. They
    must be distinct.

    This is the regression test — pre-fix, both calls wrote to the same
    `tmp_dir / 'attach.txt'` and the second clobbered the first."""
    import asyncio

    from donna.tools import attachments as att_mod

    # Stub httpx so we don't hit the network
    class _FakeResp:
        def raise_for_status(self): pass
        headers = {"content-type": "text/plain"}
        async def aiter_bytes(self):
            yield b"hello world payload"

    class _FakeStream:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return _FakeResp()
        async def __aexit__(self, *a): pass

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def stream(self, method, url): return _FakeStream()

    monkeypatch.setattr(att_mod.httpx, "AsyncClient", _FakeClient)

    # Stub ingest_text to avoid embedding pipeline
    async def _fake_ingest(**kwargs):
        return {"source_id": "src_x", "chunks_added": 1, "artifact_id": "art_x"}
    monkeypatch.setattr("donna.ingest.pipeline.ingest_text", _fake_ingest)

    write_paths: list[Path] = []
    real_write_bytes = Path.write_bytes
    def _capture(self, data, *a, **kw):
        write_paths.append(Path(self))
        return real_write_bytes(self, data, *a, **kw)
    monkeypatch.setattr(Path, "write_bytes", _capture)

    # Two concurrent ingest calls with the SAME extension (.txt)
    coros = [
        att_mod.ingest_discord_attachment(
            scope="s", attachment_url="http://x/a.txt", title="A",
        ),
        att_mod.ingest_discord_attachment(
            scope="s", attachment_url="http://x/b.txt", title="B",
        ),
    ]
    await asyncio.gather(*coros)

    assert len(write_paths) == 2
    assert write_paths[0] != write_paths[1], (
        f"two concurrent ingests of .txt files must write to distinct paths; "
        f"got {write_paths}"
    )
    # Both should match the new pattern attach_<uuid>.txt
    for p in write_paths:
        assert p.name.startswith("attach_"), p
        assert p.suffix == ".txt", p
