"""Cost ledger correctness + concurrency invariants.

Donna's cost accounting lives in `memory.cost`:

- `record_llm_usage` — INSERT a row into cost_ledger + UPDATE jobs.cost_usd
- `record_flat_cost` — same shape, for non-LLM costs (embeddings, etc.)
- `spend_today` — SUM across cost_ledger since midnight UTC

Under concurrent jobs running LLM calls simultaneously, the key concern
is double-counting or missed increments on `jobs.cost_usd`. SQLite's
single-writer serialization under WAL makes the read-modify-write atomic
at the statement level, but pinning this invariant in a test means a
future refactor (e.g., switch to Postgres, multi-writer pool) won't
silently regress accounting accuracy.

Also covers:
- Fallback pricing when `model_runtimes` has no row for a model
- `record_llm_usage(job_id=None)` for system-level usage (no job attribution)
- Cost math: price-per-million × tokens, summed across token types
- `spend_today` aggregates across `llm` and flat-cost rows equally
"""
from __future__ import annotations

import asyncio

import pytest

from donna.memory import cost as cost_mod
from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction


def _make_job() -> str:
    conn = connect()
    try:
        with transaction(conn):
            return jobs_mod.insert_job(conn, task="cost test")
    finally:
        conn.close()


def _job_cost(jid: str) -> float:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT cost_usd FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    return float(row["cost_usd"])


def _record(jid: str, *, inp: int = 0, out: int = 0, model: str = "claude-sonnet-4-5") -> float:
    conn = connect()
    try:
        return cost_mod.record_llm_usage(
            conn, job_id=jid, model=model,
            input_tokens=inp, output_tokens=out,
        )
    finally:
        conn.close()


# ---------- basic math ------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_record_llm_usage_computes_cost_from_per_million_pricing() -> None:
    """Cost math: 1_000_000 input tokens at $3/M = $3.00 exactly. Tokens of
    each type are summed via their pricing factor."""
    jid = _make_job()

    # Fallback pricing: input=3.0, output=15.0 per million
    cost = _record(jid, inp=1_000_000, out=0, model="unknown-model-forces-fallback")
    assert abs(cost - 3.00) < 1e-9, cost

    cost2 = _record(jid, inp=0, out=100_000, model="unknown-model-forces-fallback")
    assert abs(cost2 - 1.50) < 1e-9, cost2

    total = _job_cost(jid)
    assert abs(total - 4.50) < 1e-9


@pytest.mark.usefixtures("fresh_db")
def test_record_llm_usage_rolls_up_onto_jobs_row() -> None:
    jid = _make_job()
    assert _job_cost(jid) == 0.0

    _record(jid, inp=1000, out=500)
    first_total = _job_cost(jid)
    assert first_total > 0

    _record(jid, inp=2000, out=0)
    second_total = _job_cost(jid)
    assert second_total > first_total


@pytest.mark.usefixtures("fresh_db")
def test_record_llm_usage_with_no_job_id_is_safe() -> None:
    """System-level Haiku calls (e.g., the sanitize dual-call, some
    internal ingest operations) don't have a user job to attribute cost
    to. The ledger row still lands; the UPDATE jobs step is skipped."""
    conn = connect()
    try:
        cost = cost_mod.record_llm_usage(
            conn, job_id=None, model="claude-haiku-4-5",
            input_tokens=100, output_tokens=50,
        )
    finally:
        conn.close()
    assert cost > 0

    conn = connect()
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM cost_ledger WHERE job_id IS NULL"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert count == 1


# ---------- concurrency ---------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_concurrent_record_llm_usage_sums_correctly() -> None:
    """Ten concurrent LLM-usage records on the same job must sum to
    exactly 10× one record's cost — no double-count, no missed increment.

    SQLite's WAL single-writer guarantee should make this race-free at
    the statement level. Pinning it here so a future switch to a
    multi-writer backend (Postgres, etc.) doesn't silently regress
    cost accuracy."""
    jid = _make_job()

    async def _one() -> None:
        # Each call records an identical 1000 input / 500 output. We run
        # under asyncio but each call opens its own connection so the
        # serialization contract gets a real workout.
        await asyncio.to_thread(_record, jid, inp=1000, out=500)

    N = 10
    await asyncio.gather(*[_one() for _ in range(N)])

    # Ledger has exactly N rows
    conn = connect()
    try:
        ledger_count = conn.execute(
            "SELECT COUNT(*) AS n FROM cost_ledger WHERE job_id = ?", (jid,),
        ).fetchone()["n"]
        ledger_sum = conn.execute(
            "SELECT SUM(cost_usd) AS s FROM cost_ledger WHERE job_id = ?", (jid,),
        ).fetchone()["s"]
    finally:
        conn.close()
    assert ledger_count == N

    # jobs.cost_usd equals the ledger sum, not stale (no missed increments)
    job_total = _job_cost(jid)
    assert abs(job_total - ledger_sum) < 1e-9, (
        f"jobs.cost_usd={job_total} diverges from ledger sum={ledger_sum} — "
        f"concurrent UPDATE missed an increment"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_concurrent_records_across_different_jobs_do_not_cross() -> None:
    """Two concurrent streams, different jobs. Each job's total must
    reflect only its own records. Regression guard against any query
    that would accidentally use a wrong job_id under concurrency."""
    jid_a = _make_job()
    jid_b = _make_job()

    async def _stream(jid: str, n: int) -> None:
        for _ in range(n):
            await asyncio.to_thread(_record, jid, inp=1000, out=500)

    await asyncio.gather(_stream(jid_a, 5), _stream(jid_b, 7))

    conn = connect()
    try:
        count_a = conn.execute(
            "SELECT COUNT(*) AS n FROM cost_ledger WHERE job_id = ?", (jid_a,),
        ).fetchone()["n"]
        count_b = conn.execute(
            "SELECT COUNT(*) AS n FROM cost_ledger WHERE job_id = ?", (jid_b,),
        ).fetchone()["n"]
    finally:
        conn.close()
    assert count_a == 5
    assert count_b == 7

    # jobs.cost_usd for each should match the N-records expectation
    # (A and B record the same unit cost per call)
    per_call = _job_cost(jid_a) / 5
    assert abs(_job_cost(jid_b) - 7 * per_call) < 1e-9


# ---------- spend_today ---------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_spend_today_sums_across_kinds() -> None:
    """`spend_today` aggregates LLM usage AND flat costs. A daily alert
    threshold needs both or it'll underreport."""
    jid = _make_job()
    _record(jid, inp=1_000_000, out=0, model="unknown-fallback")  # $3.00

    conn = connect()
    try:
        cost_mod.record_flat_cost(
            conn, job_id=jid, kind="embedding", cost_usd=0.25,
            model="voyage-3",
        )
    finally:
        conn.close()

    conn = connect()
    try:
        total = cost_mod.spend_today(conn)
    finally:
        conn.close()
    assert abs(total - 3.25) < 1e-9


@pytest.mark.usefixtures("fresh_db")
def test_spend_today_empty_returns_zero() -> None:
    conn = connect()
    try:
        total = cost_mod.spend_today(conn)
    finally:
        conn.close()
    assert total == 0.0


# ---------- record_flat_cost --------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_record_flat_cost_updates_jobs_total() -> None:
    jid = _make_job()
    conn = connect()
    try:
        cost_mod.record_flat_cost(
            conn, job_id=jid, kind="embedding", cost_usd=0.42,
            model="voyage-3",
        )
    finally:
        conn.close()
    assert abs(_job_cost(jid) - 0.42) < 1e-9


@pytest.mark.usefixtures("fresh_db")
def test_record_flat_cost_no_job_id_is_safe() -> None:
    conn = connect()
    try:
        cost_mod.record_flat_cost(
            conn, job_id=None, kind="embedding", cost_usd=0.10,
            model="voyage-3",
        )
        row = conn.execute(
            "SELECT kind, cost_usd FROM cost_ledger WHERE job_id IS NULL",
        ).fetchone()
    finally:
        conn.close()
    assert row["kind"] == "embedding"
    assert abs(float(row["cost_usd"]) - 0.10) < 1e-9
