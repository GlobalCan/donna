"""Hybrid retrieval with diversity + recency awareness.

Combines semantic (Voyage embeddings) + keyword (FTS5) via reciprocal rank
fusion, then applies diversity constraints and temporal boosts.
"""
from __future__ import annotations

import re
from typing import Any

from ..ingest.embed import embed_text
from ..memory import knowledge as kn
from ..memory.db import connect
from ..types import Chunk


async def retrieve_knowledge(
    *,
    scope: str,
    query: str,
    top_k: int = 8,
    style_anchors_only: bool = False,
    max_tokens: int = 4000,
) -> dict[str, Any]:
    """Return top-K chunks under constraints. Returns:
       {"chunks": [Chunk...], "refusal": str | None}
    """
    conn = connect()
    try:
        # Embed query
        try:
            q_emb = await embed_text(query)
        except Exception:
            q_emb = None

        semantic: list[tuple[Chunk, float]] = []
        if q_emb:
            semantic = kn.semantic_search(
                conn, agent_scope=scope, query_embedding=q_emb, limit=40,
            )
        keyword = kn.keyword_search(conn, agent_scope=scope, query=query, limit=40)
    finally:
        conn.close()

    # Merge via reciprocal rank fusion
    pool = _rrf_merge(semantic, keyword)
    if not pool:
        return {
            "chunks": [],
            "refusal": f"no relevant chunks for scope '{scope}'",
        }

    # Style-anchor filtering
    if style_anchors_only:
        pool = [(c, s) for c, s in pool if c.is_style_anchor]

    # Temporal intent
    intent = _infer_temporal_intent(query)
    pool = _apply_temporal_prior(pool, intent)

    # Diversity: cap by work_id (2) and source_type (3)
    diverse = _apply_diversity(pool, max_per_work=2, max_per_source_type=3)

    # Token budget cap
    chosen: list[Chunk] = []
    total_chars = 0
    for c, _ in diverse:
        if total_chars + len(c.content) > max_tokens * 4:
            break
        chosen.append(c)
        total_chars += len(c.content)
        if len(chosen) >= top_k:
            break

    refusal = None
    if not chosen:
        refusal = f"no relevant chunks for scope '{scope}' after filtering"

    return {"chunks": chosen, "refusal": refusal, "intent": intent}


# ---------- helpers --------------------------------------------------------


def _rrf_merge(
    a: list[tuple[Chunk, float]], b: list[tuple[Chunk, float]], *, k: int = 60,
) -> list[tuple[Chunk, float]]:
    scores: dict[str, float] = {}
    by_id: dict[str, Chunk] = {}
    for rank, (c, _) in enumerate(a, start=1):
        scores[c.id] = scores.get(c.id, 0.0) + 1.0 / (k + rank)
        by_id[c.id] = c
    for rank, (c, _) in enumerate(b, start=1):
        scores[c.id] = scores.get(c.id, 0.0) + 1.0 / (k + rank)
        by_id[c.id] = c
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(by_id[cid], sc) for cid, sc in ranked]


def _infer_temporal_intent(q: str) -> str:
    ql = q.lower()
    if re.search(r"\b(latest|recent|current|today|this (week|month|year)|202[4-9])\b", ql):
        return "recent"
    if re.search(r"\b(change|changed|evolve|evolved|over time|history|origin)\b", ql):
        return "evolution"
    return "neutral"


def _apply_temporal_prior(
    pool: list[tuple[Chunk, float]], intent: str,
) -> list[tuple[Chunk, float]]:
    if intent == "neutral":
        return pool
    if intent == "recent":
        # Codex audit fix: scale the recency boost to be proportional to the
        # actual fusion scores in this pool. Otherwise a trivial linear-in-year
        # bump (which could easily equal 0.04+ for a 2024 chunk) outweighs RRF
        # scores on the order of 1/(60+rank) and the whole retrieval collapses
        # to "most recent thing" regardless of semantic relevance.
        if not pool:
            return pool
        max_score = max(s for _, s in pool)
        # Normalize: max boost is 25% of the top score
        def boost(ch: Chunk) -> float:
            if not ch.publication_date:
                return 0.0
            try:
                year = int(ch.publication_date[:4])
            except ValueError:
                return 0.0
            # Saturating: 1980 → 0, 2025 → 1.0
            rel = max(0.0, min(1.0, (year - 1980) / 45.0))
            return rel * max_score * 0.25
        return sorted(
            [(c, s + boost(c)) for c, s in pool],
            key=lambda x: x[1],
            reverse=True,
        )
    if intent == "evolution":
        # Force era diversity: pick alternating across date bands
        by_era: dict[str, list[tuple[Chunk, float]]] = {}
        for c, s in pool:
            era = (c.publication_date or "unknown")[:3] + "0s"
            by_era.setdefault(era, []).append((c, s))
        interleaved: list[tuple[Chunk, float]] = []
        while any(by_era.values()):
            for era, items in list(by_era.items()):
                if items:
                    interleaved.append(items.pop(0))
                else:
                    del by_era[era]
        return interleaved
    return pool


def _apply_diversity(
    pool: list[tuple[Chunk, float]], *, max_per_work: int, max_per_source_type: int,
) -> list[tuple[Chunk, float]]:
    work_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    out: list[tuple[Chunk, float]] = []
    for c, s in pool:
        w = c.work_id or "__none__"
        t = c.source_type or "other"
        if work_counts.get(w, 0) >= max_per_work:
            continue
        if type_counts.get(t, 0) >= max_per_source_type:
            continue
        work_counts[w] = work_counts.get(w, 0) + 1
        type_counts[t] = type_counts.get(t, 0) + 1
        out.append((c, s))
    return out
