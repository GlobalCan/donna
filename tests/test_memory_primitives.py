"""DB primitives smoke test — run migrations, insert/fetch a job + fact."""
from __future__ import annotations

import pytest

from donna.memory import facts as facts_mod
from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction
from donna.types import JobMode, JobStatus


@pytest.mark.usefixtures("fresh_db")
def test_job_lifecycle() -> None:
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="test task", agent_scope="orchestrator", mode=JobMode.CHAT,
            )
        j = jobs_mod.get_job(conn, jid)
        assert j is not None
        assert j.status == JobStatus.QUEUED
        assert j.task == "test task"

        claimed = jobs_mod.claim_next_queued(conn, worker_id="worker-test")
        assert claimed is not None
        assert claimed.id == jid
        assert claimed.status == JobStatus.RUNNING

        renewed = jobs_mod.renew_lease(conn, jid, "worker-test")
        assert renewed is True
    finally:
        conn.close()


@pytest.mark.usefixtures("fresh_db")
def test_fact_fts_search() -> None:
    conn = connect()
    try:
        with transaction(conn):
            facts_mod.insert_fact(
                conn,
                fact="Tesla stock ticker is TSLA",
                tags="finance,ticker",
                agent_scope=None,
            )
            facts_mod.insert_fact(
                conn,
                fact="User prefers DCF over comps for valuation",
                tags="user,finance",
            )
        hits = facts_mod.search_facts_fts(conn, "Tesla", limit=5)
        assert len(hits) >= 1
        assert any("TSLA" in h["fact"] for h in hits)
    finally:
        conn.close()
