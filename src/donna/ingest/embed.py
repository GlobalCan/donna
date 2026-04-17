"""Voyage-3 embedding wrapper — batched for cost."""
from __future__ import annotations

from typing import Any

import voyageai

from ..config import settings
from ..logging import get_logger
from ..memory import cost as cost_mod
from ..memory.db import connect

log = get_logger(__name__)

_client: voyageai.AsyncClient | None = None

# Voyage-3 pricing (per 1M tokens)
VOYAGE_PRICE_PER_MTOK = 0.06


def _vc() -> voyageai.AsyncClient:
    global _client
    if _client is None:
        _client = voyageai.AsyncClient(api_key=settings().voyage_api_key)
    return _client


async def embed_text(text: str) -> list[float]:
    """One-shot embedding for a query."""
    s = settings()
    resp = await _vc().embed([text], model=s.voyage_embed_model, input_type="query")
    _record_cost(getattr(resp, "total_tokens", 0) or 0)
    return resp.embeddings[0]


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Batch embed documents for ingestion."""
    s = settings()
    out: list[list[float]] = []
    batch_size = 64
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = await _vc().embed(batch, model=s.voyage_embed_model, input_type="document")
        _record_cost(getattr(resp, "total_tokens", 0) or 0)
        out.extend(resp.embeddings)
    return out


def _record_cost(tokens: int) -> None:
    if not tokens:
        return
    cost = tokens * VOYAGE_PRICE_PER_MTOK / 1_000_000
    conn = connect()
    try:
        cost_mod.record_flat_cost(
            conn, job_id=None, kind="embed", cost_usd=cost, model="voyage-3",
        )
    finally:
        conn.close()
