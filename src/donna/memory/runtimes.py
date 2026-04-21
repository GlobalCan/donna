"""ModelRuntime registry — query helpers.

Pattern A steal #1 from Hermes: vendor abstraction as data, not slogan.
Pricing + provider details live in the `model_runtimes` table. The agent
loop asks for a tier; the registry resolves to provider + model_id + pricing.
Adding OpenAI = `INSERT INTO model_runtimes ...`; no code changes in the
agent loop.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .db import connect


@dataclass(frozen=True)
class Runtime:
    id: str
    provider: str
    model_id: str
    tier: str                 # 'fast' | 'strong' | 'heavy'
    api_base: str | None
    api_key_env: str
    context_limit: int | None
    price_input: float        # $ per 1M input tokens
    price_output: float
    price_cache_read: float
    price_cache_write: float
    active: bool


# Cached per-process; invalidated via clear_cache()
_cache: dict[tuple[str, str], Runtime] = {}   # keyed by (provider, tier)
_by_model: dict[str, Runtime] = {}            # keyed by model_id


def get_by_tier(tier: str, provider: str = "anthropic") -> Runtime | None:
    """Resolve (provider, tier) → Runtime. Preferred model_id for that tier."""
    key = (provider, tier)
    if key in _cache:
        return _cache[key]
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT * FROM model_runtimes
            WHERE provider = ? AND tier = ? AND active = 1
            ORDER BY rowid LIMIT 1
            """,
            (provider, tier),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    rt = _row_to_runtime(row)
    _cache[key] = rt
    _by_model[rt.model_id] = rt
    return rt


def get_by_model_id(model_id: str) -> Runtime | None:
    """Resolve a specific model_id to its Runtime (for cost calculation)."""
    if model_id in _by_model:
        return _by_model[model_id]
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM model_runtimes WHERE model_id = ? AND active = 1",
            (model_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    rt = _row_to_runtime(row)
    _by_model[model_id] = rt
    return rt


def list_runtimes(active_only: bool = True) -> list[Runtime]:
    conn = connect()
    try:
        sql = "SELECT * FROM model_runtimes"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY provider, tier, price_input"
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    return [_row_to_runtime(r) for r in rows]


def add_runtime(
    *,
    id: str,
    provider: str,
    model_id: str,
    tier: str,
    api_key_env: str,
    price_input: float,
    price_output: float,
    price_cache_read: float = 0.0,
    price_cache_write: float = 0.0,
    api_base: str | None = None,
    context_limit: int | None = None,
    active: bool = True,
) -> None:
    """Add a new runtime row (e.g., to enable OpenAI)."""
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO model_runtimes
                (id, provider, model_id, tier, api_base, api_key_env,
                 context_limit, price_input, price_output,
                 price_cache_read, price_cache_write, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (id, provider, model_id, tier, api_base, api_key_env,
             context_limit, price_input, price_output,
             price_cache_read, price_cache_write, 1 if active else 0),
        )
    finally:
        conn.close()
    clear_cache()


def clear_cache() -> None:
    _cache.clear()
    _by_model.clear()


def _row_to_runtime(row: sqlite3.Row) -> Runtime:
    return Runtime(
        id=row["id"],
        provider=row["provider"],
        model_id=row["model_id"],
        tier=row["tier"],
        api_base=row["api_base"],
        api_key_env=row["api_key_env"],
        context_limit=row["context_limit"],
        price_input=float(row["price_input"]),
        price_output=float(row["price_output"]),
        price_cache_read=float(row["price_cache_read"]),
        price_cache_write=float(row["price_cache_write"]),
        active=bool(row["active"]),
    )
