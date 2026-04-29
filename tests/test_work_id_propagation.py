"""Cross-vendor review #6 (Codex GPT-5): default ingests gave the source
row a surrogate `work_id` (the artifact ID) but chunk rows got the raw
caller value (None when not supplied). Result: chunks across unrelated
default ingests all carried `work_id = NULL`, and the diversity grouping
in `modes/retrieval.py::_apply_diversity` collapsed them under a single
'__none__' bucket. Mixed-corpus retrieval silently lost diversity.

Fix: resolve `work_id` once at the top of `ingest_text` and use the same
value for both the source and every chunk.

These tests pin:

1. Default ingest (caller passes no work_id) populates `chunks.work_id`
   with the same surrogate as `knowledge_sources.work_id`.
2. Explicit caller work_id flows through to both rows unchanged.
3. Two consecutive default ingests produce DISTINCT chunk work_ids
   (the bug's main symptom: they used to all share NULL).
4. The retrieval diversity grouping spreads results across multiple
   default-ingested sources.
"""
from __future__ import annotations

import pytest

from donna.ingest.pipeline import ingest_text
from donna.memory.db import connect


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_default_ingest_propagates_surrogate_work_id_to_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Stub embeddings so we don't need Voyage in tests
    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]
    monkeypatch.setattr(
        "donna.ingest.pipeline.embed_documents", _fake_embed,
    )

    res = await ingest_text(
        scope="work_id_test",
        source_type="article",
        title="No work_id supplied",
        content="Some unique chunk content body for the work id test.\n\n"
                "A second paragraph of unique content.\n\n"
                "Third paragraph distinguishes work id propagation.",
        copyright_status="public_domain",
    )
    assert res.get("chunks_added", 0) >= 1, res

    conn = connect()
    try:
        src_row = conn.execute(
            "SELECT work_id FROM knowledge_sources WHERE id = ?",
            (res["source_id"],),
        ).fetchone()
        chunk_rows = conn.execute(
            "SELECT work_id FROM knowledge_chunks WHERE source_id = ?",
            (res["source_id"],),
        ).fetchall()
    finally:
        conn.close()

    assert src_row is not None, "source row should exist"
    src_work_id = src_row[0]
    assert src_work_id, "source.work_id should NOT be empty after fix"
    assert all(r[0] == src_work_id for r in chunk_rows), (
        f"every chunk should share the source's surrogate work_id "
        f"{src_work_id!r}; got {[r[0] for r in chunk_rows]}"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_explicit_work_id_flows_to_both_source_and_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]
    monkeypatch.setattr(
        "donna.ingest.pipeline.embed_documents", _fake_embed,
    )

    res = await ingest_text(
        scope="work_id_test",
        source_type="article",
        title="Explicit work_id",
        content="paragraph one with explicit work id.\n\n"
                "paragraph two of the same work id case.",
        copyright_status="public_domain",
        work_id="caller_supplied_work",
    )
    conn = connect()
    try:
        src = conn.execute(
            "SELECT work_id FROM knowledge_sources WHERE id = ?",
            (res["source_id"],),
        ).fetchone()
        chunks = conn.execute(
            "SELECT work_id FROM knowledge_chunks WHERE source_id = ?",
            (res["source_id"],),
        ).fetchall()
    finally:
        conn.close()
    assert src[0] == "caller_supplied_work"
    assert all(r[0] == "caller_supplied_work" for r in chunks), [r[0] for r in chunks]


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_two_default_ingests_have_distinct_chunk_work_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-fix: both ingests' chunks all carried work_id=NULL, collapsing
    into a single diversity bucket. After fix: each ingest's chunks share
    a surrogate (its own artifact id), and the two surrogates are
    distinct."""
    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]
    monkeypatch.setattr(
        "donna.ingest.pipeline.embed_documents", _fake_embed,
    )

    a = await ingest_text(
        scope="diversity_test",
        source_type="article",
        title="First source",
        content="alpha bravo charlie content body one.\n\nalpha bravo two.",
        copyright_status="public_domain",
    )
    b = await ingest_text(
        scope="diversity_test",
        source_type="article",
        title="Second source",
        content="delta echo foxtrot content body one.\n\ndelta echo two.",
        copyright_status="public_domain",
    )
    conn = connect()
    try:
        a_chunks = conn.execute(
            "SELECT work_id FROM knowledge_chunks WHERE source_id = ?",
            (a["source_id"],),
        ).fetchall()
        b_chunks = conn.execute(
            "SELECT work_id FROM knowledge_chunks WHERE source_id = ?",
            (b["source_id"],),
        ).fetchall()
    finally:
        conn.close()

    a_works = {r[0] for r in a_chunks}
    b_works = {r[0] for r in b_chunks}
    assert len(a_works) == 1 and len(b_works) == 1, (
        f"each source's chunks should share one work_id; a={a_works}, b={b_works}"
    )
    assert a_works.isdisjoint(b_works), (
        f"two default ingests must produce DISTINCT work_ids; both = {a_works}"
    )
    assert all(w for w in (a_works | b_works)), "no NULL work_ids"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_retrieval_diversity_no_longer_collapses_default_ingests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: ingest two default-work_id sources, retrieve, confirm
    chunks from both surface (diversity cap is max_per_work=2; if work_id
    was NULL for both, the cap would silently kick in and drop one).

    Easier assertion: after retrieval, the chunks should reference >1
    distinct source_id. Pre-fix this test still passed (diversity caps
    chunks-per-work, but with all NULL the cap keeps 2 of any source);
    the post-fix guarantee is stronger — both sources represented when
    each has multiple matching chunks."""
    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]
    monkeypatch.setattr(
        "donna.ingest.pipeline.embed_documents", _fake_embed,
    )

    await ingest_text(
        scope="div_e2e",
        source_type="article",
        title="Source one",
        content="payload alpha one.\n\npayload alpha two.\n\npayload alpha three.",
        copyright_status="public_domain",
    )
    await ingest_text(
        scope="div_e2e",
        source_type="article",
        title="Source two",
        content="payload bravo one.\n\npayload bravo two.\n\npayload bravo three.",
        copyright_status="public_domain",
    )

    from donna.modes.retrieval import retrieve_knowledge
    out = await retrieve_knowledge(scope="div_e2e", query="payload", top_k=8)
    chunks = out.get("chunks") or []
    distinct_sources = {c.source_id for c in chunks}
    assert len(chunks) >= 2, f"expected ≥2 chunks; got {len(chunks)}"
    assert len(distinct_sources) >= 2, (
        f"diversity grouping must spread across both default-ingested sources; "
        f"got chunks from {distinct_sources}"
    )
    distinct_works = {c.work_id for c in chunks}
    assert len(distinct_works) >= 2, (
        f"chunks must carry distinct work_ids post-fix; got {distinct_works}"
    )
