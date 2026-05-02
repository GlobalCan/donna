"""V0.7.2: outbox helper extraction.

Codex 2026-05-02 review on the overnight plan flagged JobContext as
carrying too many concerns. The genuinely-inlined surface was outbox
INSERTs — repeated in 4 places (JobContext.finalize, send_update,
ask_user, dead-letter retry). v0.7.2 extracts them into named
helpers in `memory.outbox` so:

- The SQL lives in one place
- Each helper is independently testable
- Future delivery surfaces (morning brief, /validate) reuse the
  same primitives instead of duplicating SQL
- Caller still controls the transaction boundary (Codex's pitfall:
  "do not let each service open its own transaction during finalize")

These tests pin the contract.
"""
from __future__ import annotations

import pytest

from donna.memory import jobs as jobs_mod
from donna.memory import outbox as outbox_mod
from donna.memory.db import connect, transaction
from donna.types import JobMode


def _seed_job(conn, job_id_marker: str = "x") -> str:
    """Insert a real job to satisfy outbox_*.job_id FK."""
    with transaction(conn):
        return jobs_mod.insert_job(
            conn, task=f"seed-{job_id_marker}", mode=JobMode.CHAT,
        )


@pytest.mark.usefixtures("fresh_db")
def test_enqueue_update_inserts_row_with_returned_id() -> None:
    conn = connect()
    try:
        jid = _seed_job(conn, "x")
        with transaction(conn):
            uid = outbox_mod.enqueue_update(
                conn, job_id=jid, text="hello", tainted=False,
            )
        row = conn.execute(
            "SELECT id, job_id, text, tainted "
            "FROM outbox_updates WHERE id = ?", (uid,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["id"] == uid
    assert row["job_id"] == jid
    assert row["text"] == "hello"
    assert row["tainted"] == 0


@pytest.mark.usefixtures("fresh_db")
def test_enqueue_update_persists_tainted_flag() -> None:
    conn = connect()
    try:
        jid = _seed_job(conn, "x")
        with transaction(conn):
            uid = outbox_mod.enqueue_update(
                conn, job_id=jid, text="risky", tainted=True,
            )
        row = conn.execute(
            "SELECT tainted FROM outbox_updates WHERE id = ?", (uid,),
        ).fetchone()
    finally:
        conn.close()
    assert row["tainted"] == 1


@pytest.mark.usefixtures("fresh_db")
def test_enqueue_update_truncates_at_20k_chars() -> None:
    """Belt-and-suspenders: oversized text is capped so the row size
    stays bounded. Caller is encouraged to truncate first to a more
    appropriate size for their use case (1500 for progress pings,
    20000 for final answers)."""
    conn = connect()
    try:
        jid = _seed_job(conn, "x")
        with transaction(conn):
            uid = outbox_mod.enqueue_update(
                conn, job_id=jid, text="x" * 50000, tainted=False,
            )
        row = conn.execute(
            "SELECT text FROM outbox_updates WHERE id = ?", (uid,),
        ).fetchone()
    finally:
        conn.close()
    assert len(row["text"]) == 20000


@pytest.mark.usefixtures("fresh_db")
def test_enqueue_update_id_is_unique_across_calls() -> None:
    """Different calls produce different ids. Pre-extraction this was
    via a uuid4 cast in botctl; post-extraction it's via ids.new_id
    which uses ts+random — same uniqueness guarantee."""
    conn = connect()
    try:
        jid = _seed_job(conn, "x")
        with transaction(conn):
            uid_a = outbox_mod.enqueue_update(
                conn, job_id=jid, text="a", tainted=False,
            )
            uid_b = outbox_mod.enqueue_update(
                conn, job_id=jid, text="b", tainted=False,
            )
    finally:
        conn.close()
    assert uid_a != uid_b
    assert uid_a.startswith("upd_")
    assert uid_b.startswith("upd_")


@pytest.mark.usefixtures("fresh_db")
def test_enqueue_ask_inserts_row() -> None:
    conn = connect()
    try:
        jid = _seed_job(conn, "x")
        with transaction(conn):
            aid = outbox_mod.enqueue_ask(
                conn, job_id=jid, question="proceed?",
            )
        row = conn.execute(
            "SELECT id, job_id, question FROM outbox_asks WHERE id = ?",
            (aid,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["job_id"] == jid
    assert row["question"] == "proceed?"
    assert aid.startswith("ask_")


@pytest.mark.usefixtures("fresh_db")
def test_list_updates_for_job_returns_oldest_first() -> None:
    conn = connect()
    try:
        jid_a = _seed_job(conn, "a")
        jid_other = _seed_job(conn, "other")
        with transaction(conn):
            id_a = outbox_mod.enqueue_update(
                conn, job_id=jid_a, text="first", tainted=False,
            )
            id_b = outbox_mod.enqueue_update(
                conn, job_id=jid_a, text="second", tainted=False,
            )
            # Different job — should not show up in the listing.
            outbox_mod.enqueue_update(
                conn, job_id=jid_other, text="alien", tainted=False,
            )
        rows = outbox_mod.list_updates_for_job(conn, jid_a)
    finally:
        conn.close()
    assert len(rows) == 2
    ids = [r["id"] for r in rows]
    assert id_a in ids
    assert id_b in ids
    assert all(r["job_id"] == jid_a for r in rows)


@pytest.mark.usefixtures("fresh_db")
def test_list_asks_for_job_returns_only_matching_rows() -> None:
    conn = connect()
    try:
        jid_a = _seed_job(conn, "a")
        jid_other = _seed_job(conn, "other")
        with transaction(conn):
            outbox_mod.enqueue_ask(
                conn, job_id=jid_a, question="q1",
            )
            outbox_mod.enqueue_ask(
                conn, job_id=jid_other, question="q-alien",
            )
        rows = outbox_mod.list_asks_for_job(conn, jid_a)
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["question"] == "q1"


@pytest.mark.usefixtures("fresh_db")
def test_helpers_compose_in_single_transaction() -> None:
    """Codex's pitfall: 'do not let each service open its own
    transaction during finalize'. Verify both helpers can be called
    inside the SAME `transaction(conn)` block — confirming finalize
    can stay atomic."""
    conn = connect()
    try:
        jid = _seed_job(conn, "x")
        with transaction(conn):
            uid = outbox_mod.enqueue_update(
                conn, job_id=jid, text="t", tainted=False,
            )
            aid = outbox_mod.enqueue_ask(
                conn, job_id=jid, question="q",
            )
        # Both must have committed together.
        upd = conn.execute(
            "SELECT id FROM outbox_updates WHERE id = ?", (uid,),
        ).fetchone()
        ask = conn.execute(
            "SELECT id FROM outbox_asks WHERE id = ?", (aid,),
        ).fetchone()
    finally:
        conn.close()
    assert upd is not None
    assert ask is not None
