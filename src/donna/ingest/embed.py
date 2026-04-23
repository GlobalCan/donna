"""Voyage-3 embedding wrapper — direct HTTP, batched for cost.

Previously used the official `voyageai` SDK, which as of 2026-04 caps at
Python <3.14 and hadn't shipped a 3.14-compatible release. The SDK is a
thin wrapper over POST /v1/embeddings; inlining the HTTP call removes the
dep, the Python-version lock, and a layer of opaque retry logic.
"""
from __future__ import annotations

import httpx

from ..config import settings
from ..logging import get_logger
from ..memory import cost as cost_mod
from ..memory.db import connect

log = get_logger(__name__)

# Voyage-3 pricing (per 1M tokens)
VOYAGE_PRICE_PER_MTOK = 0.06
VOYAGE_ENDPOINT = "https://api.voyageai.com/v1/embeddings"

_client: httpx.AsyncClient | None = None


def _hc() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=60.0)
    return _client


async def _embed_batch(texts: list[str], input_type: str) -> tuple[list[list[float]], int]:
    """Single batched call. Returns (embeddings, total_tokens)."""
    s = settings()
    r = await _hc().post(
        VOYAGE_ENDPOINT,
        headers={
            "Authorization": f"Bearer {s.voyage_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "input": texts,
            "model": s.voyage_embed_model,
            "input_type": input_type,
        },
    )
    r.raise_for_status()
    body = r.json()
    data = body.get("data") or []
    # API returns [{"embedding": [...], "index": i}, ...]; preserve order
    data_sorted = sorted(data, key=lambda d: d.get("index", 0))
    embeddings = [d["embedding"] for d in data_sorted]
    total_tokens = int((body.get("usage") or {}).get("total_tokens", 0) or 0)
    return embeddings, total_tokens


async def embed_text(text: str) -> list[float]:
    """One-shot embedding for a query."""
    embs, tokens = await _embed_batch([text], input_type="query")
    _record_cost(tokens)
    return embs[0]


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Batch embed documents for ingestion."""
    out: list[list[float]] = []
    batch_size = 64
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        embs, tokens = await _embed_batch(batch, input_type="document")
        _record_cost(tokens)
        out.extend(embs)
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
