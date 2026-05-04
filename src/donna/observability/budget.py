"""Budget watcher — alerts the operator when daily spend crosses thresholds.

v0.7.3 (Codex #11): alerts now route through `alert_digest.route_alert`
so they participate in the opt-in digest. Default behavior unchanged
(immediate DM) when `DONNA_ALERT_DIGEST_INTERVAL_MIN = 0`.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..config import settings
from ..logging import get_logger
from ..memory import cost as cost_mod
from ..memory.db import connect
from . import alert_digest

log = get_logger(__name__)


class BudgetWatcher:
    def __init__(self, notifier: Callable[[str], Awaitable[None]]):
        self.notifier = notifier
        self._crossed: set[float] = set()

    async def tick(self) -> None:
        conn = connect()
        try:
            spend = cost_mod.spend_today(conn)
        finally:
            conn.close()
        for threshold in sorted(settings().budget_thresholds):
            if spend >= threshold and threshold not in self._crossed:
                self._crossed.add(threshold)
                msg = f"💰 Daily spend crossed ${threshold:.2f} — current: ${spend:.2f}"
                log.info("budget.alert", threshold=threshold, spend=spend)
                # `dedup_key` is per-threshold so two ticks crossing the
                # same threshold within one digest window collapse into
                # one digest line — defense-in-depth on top of the
                # in-memory _crossed set.
                await alert_digest.route_alert(
                    self.notifier,
                    kind="budget",
                    message=msg,
                    severity="warning",
                    dedup_key=f"budget:{threshold}",
                )

    async def loop(self, interval_seconds: int = 60) -> None:
        while True:
            try:
                await self.tick()
            except Exception as e:
                log.exception("budget.tick_failed", error=str(e))
            await asyncio.sleep(interval_seconds)
