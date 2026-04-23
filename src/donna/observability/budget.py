"""Budget watcher — sends Discord DM when daily spend crosses thresholds."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..config import settings
from ..logging import get_logger
from ..memory import cost as cost_mod
from ..memory.db import connect

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
                try:
                    await self.notifier(msg)
                except Exception as e:
                    log.warning("budget.notify_failed", error=str(e))

    async def loop(self, interval_seconds: int = 60) -> None:
        while True:
            try:
                await self.tick()
            except Exception as e:
                log.exception("budget.tick_failed", error=str(e))
            await asyncio.sleep(interval_seconds)
