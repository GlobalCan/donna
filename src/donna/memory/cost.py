"""Cost ledger primitives.

Pricing no longer lives in this file. The ModelRuntime registry
(see memory/runtimes.py) is the source of truth. Hardcoded fallback kept
only for the case where the runtimes table hasn't been populated yet.
"""
from __future__ import annotations

import sqlite3

from . import ids

# Fallback only — used if `model_runtimes` has no row for the model.
# Kept minimal; real pricing is in the table.
_FALLBACK_PRICING = {
    "input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75,
}


def _pricing_for(model: str) -> dict[str, float]:
    """Look up per-million-token pricing for a given model_id via the runtimes
    table. Falls back to a generic sonnet-like shape if not found."""
    try:
        from . import runtimes as rt_mod
        rt = rt_mod.get_by_model_id(model)
        if rt is not None:
            return {
                "input": rt.price_input,
                "output": rt.price_output,
                "cache_read": rt.price_cache_read,
                "cache_write": rt.price_cache_write,
            }
    except Exception:
        pass
    return _FALLBACK_PRICING


def record_llm_usage(
    conn: sqlite3.Connection,
    *,
    job_id: str | None,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Returns cost_usd."""
    p = _pricing_for(model)
    cost = (
        input_tokens * p["input"]
        + output_tokens * p["output"]
        + cache_read_tokens * p["cache_read"]
        + cache_write_tokens * p["cache_write"]
    ) / 1_000_000

    conn.execute(
        """
        INSERT INTO cost_ledger
            (id, job_id, model, input_tokens, output_tokens,
             cache_read_tokens, cache_write_tokens, cost_usd, kind)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'llm')
        """,
        (ids.cost_id(), job_id, model, input_tokens, output_tokens,
         cache_read_tokens, cache_write_tokens, cost),
    )
    if job_id:
        conn.execute(
            "UPDATE jobs SET cost_usd = cost_usd + ? WHERE id = ?",
            (cost, job_id),
        )
    return cost


def record_flat_cost(
    conn: sqlite3.Connection, *, job_id: str | None, kind: str, cost_usd: float, model: str = ""
) -> None:
    conn.execute(
        "INSERT INTO cost_ledger (id, job_id, model, kind, cost_usd) VALUES (?, ?, ?, ?, ?)",
        (ids.cost_id(), job_id, model, kind, cost_usd),
    )
    if job_id:
        conn.execute(
            "UPDATE jobs SET cost_usd = cost_usd + ? WHERE id = ?",
            (cost_usd, job_id),
        )


def spend_today(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(cost_usd), 0.0) AS total
        FROM cost_ledger
        WHERE created_at >= date('now', 'start of day')
        """
    ).fetchone()
    return float(row["total"])


def spend_this_week(conn: sqlite3.Connection) -> float:
    """Total spend over the last 7 calendar days (rolling).

    Used by v0.6 #7 cost runaway guards. Rolling rather than calendar-
    aligned so a Sunday spike doesn't reset on Monday morning.
    """
    row = conn.execute(
        """
        SELECT COALESCE(SUM(cost_usd), 0.0) AS total
        FROM cost_ledger
        WHERE created_at >= datetime('now', '-7 days')
        """
    ).fetchone()
    return float(row["total"])
