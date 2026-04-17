"""Retrieval diversity — max 2/work, max 3/source_type."""
from __future__ import annotations

from donna.modes.retrieval import _apply_diversity
from donna.types import Chunk


def _c(id_: str, work: str, typ: str) -> Chunk:
    return Chunk(
        id=id_, source_id="s", agent_scope="x", work_id=work,
        publication_date=None, source_type=typ, content="c",
        score=1.0, chunk_index=0, is_style_anchor=False, source_title=None,
    )


def test_diversity_caps_per_work() -> None:
    pool = [
        (_c("a1", "work1", "book"), 1.0),
        (_c("a2", "work1", "book"), 0.9),
        (_c("a3", "work1", "book"), 0.8),  # over 2/work cap
        (_c("a4", "work2", "book"), 0.7),
    ]
    out = _apply_diversity(pool, max_per_work=2, max_per_source_type=5)
    ids = [c.id for c, _ in out]
    assert ids == ["a1", "a2", "a4"]


def test_diversity_caps_per_source_type() -> None:
    pool = [
        (_c("a1", "w1", "book"), 1.0),
        (_c("a2", "w2", "book"), 0.9),
        (_c("a3", "w3", "book"), 0.85),
        (_c("a4", "w4", "book"), 0.8),   # over 3/type cap
        (_c("a5", "w5", "article"), 0.7),
    ]
    out = _apply_diversity(pool, max_per_work=2, max_per_source_type=3)
    ids = [c.id for c, _ in out]
    assert ids == ["a1", "a2", "a3", "a5"]
