"""Cost ledger primitives."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import ids

# Price per million tokens (as of 2026-04; update when it changes)
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4-6":           {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
}


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
    p = PRICING.get(model, {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75})
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
