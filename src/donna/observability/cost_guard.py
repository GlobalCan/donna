"""V0.6 #7: cost runaway guards.

Codex 2026-05-01: "Proactive jobs plus sanitizer plus retrieval can
quietly multiply spend." The existing budget watcher (observability/
budget.py) sends DM alerts when daily spend crosses configurable
thresholds. That's a soft signal — alert fires, spend keeps going.

This module adds HARD caps on top:

  - Daily cap: total spend in the current calendar day
  - Weekly cap: rolling 7-day total

When either is exceeded, `is_intake_blocked()` returns True. Bot intake
checks this before creating new jobs and refuses (with a polite DM
reply) when blocked. Existing in-flight jobs are not interrupted —
that would be confusing and would orphan partially-paid work.

Setting the env caps to 0 disables enforcement (returns False
unconditionally), making this an opt-in safety net — soft alerts still
fire from BudgetWatcher.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import settings
from ..memory import cost as cost_mod
from ..memory.db import connect


@dataclass(frozen=True)
class CostStatus:
    daily_spend: float
    daily_cap: float
    weekly_spend: float
    weekly_cap: float

    @property
    def daily_blocked(self) -> bool:
        return self.daily_cap > 0 and self.daily_spend >= self.daily_cap

    @property
    def weekly_blocked(self) -> bool:
        return self.weekly_cap > 0 and self.weekly_spend >= self.weekly_cap

    @property
    def blocked(self) -> bool:
        return self.daily_blocked or self.weekly_blocked

    def reason(self) -> str:
        """Human-readable explanation for the operator-facing message."""
        if self.daily_blocked and self.weekly_blocked:
            return (
                f"daily spend ${self.daily_spend:.2f} >= cap "
                f"${self.daily_cap:.2f} AND weekly spend "
                f"${self.weekly_spend:.2f} >= cap ${self.weekly_cap:.2f}"
            )
        if self.daily_blocked:
            return (
                f"daily spend ${self.daily_spend:.2f} >= cap "
                f"${self.daily_cap:.2f}"
            )
        if self.weekly_blocked:
            return (
                f"7-day rolling spend ${self.weekly_spend:.2f} >= cap "
                f"${self.weekly_cap:.2f}"
            )
        return ""


def current_status() -> CostStatus:
    """Read fresh spend totals + caps from settings."""
    s = settings()
    conn = connect()
    try:
        daily = cost_mod.spend_today(conn)
        weekly = cost_mod.spend_this_week(conn)
    finally:
        conn.close()
    return CostStatus(
        daily_spend=daily,
        daily_cap=float(s.daily_hard_cap_usd),
        weekly_spend=weekly,
        weekly_cap=float(s.weekly_hard_cap_usd),
    )


def is_intake_blocked() -> bool:
    """Quick yes/no for hot-path intake checks. Looks up fresh status."""
    return current_status().blocked
