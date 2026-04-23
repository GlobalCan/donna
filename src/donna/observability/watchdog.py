"""Ops watchdog — DMs on stuck jobs and unresolved pending consents.

Codex review #13 fix: Phoenix is a debugger, not an ops story. This adds
lightweight active monitoring so you find out *before* you notice the bot
has been silently stuck for hours.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from ..logging import get_logger
from ..memory.db import connect

log = get_logger(__name__)


class Watchdog:
    def __init__(self, notifier: Callable[[str], Awaitable[None]]):
        self.notifier = notifier
        # dedupe: one alert per (kind, id) per 12h
        self._already_alerted: dict[tuple[str, str], datetime] = {}

    async def tick(self) -> None:
        await self._check_stuck_consent()
        await self._check_stuck_running()
        await self._check_recent_failures()

    async def loop(self, interval_seconds: int = 300) -> None:
        """Run forever, ticking every 5 min."""
        while True:
            try:
                await self.tick()
            except Exception as e:  # noqa: BLE001
                log.exception("watchdog.tick_failed", error=str(e))
            await asyncio.sleep(interval_seconds)

    # -- checks -----------------------------------------------------------

    async def _check_stuck_consent(self) -> None:
        """A job in PAUSED_AWAITING_CONSENT for > 1 hour likely needs a nudge."""
        cutoff = datetime.now(UTC) - timedelta(hours=1)
        conn = connect()
        try:
            rows = conn.execute(
                """
                SELECT id, task, created_at FROM jobs
                WHERE status = 'paused_awaiting_consent' AND started_at < ?
                """,
                (cutoff,),
            ).fetchall()
        finally:
            conn.close()
        for r in rows:
            await self._alert_once(
                "stuck_consent", r["id"],
                f"⏳ Job `{r['id'][:18]}…` has been waiting for consent >1h. "
                f"Task: {(r['task'] or '')[:120]}"
            )

    async def _check_stuck_running(self) -> None:
        """A job in RUNNING for > 30 min may be wedged."""
        cutoff = datetime.now(UTC) - timedelta(minutes=30)
        conn = connect()
        try:
            rows = conn.execute(
                """
                SELECT id, task, started_at FROM jobs
                WHERE status = 'running' AND started_at < ?
                """,
                (cutoff,),
            ).fetchall()
        finally:
            conn.close()
        for r in rows:
            await self._alert_once(
                "stuck_running", r["id"],
                f"🔄 Job `{r['id'][:18]}…` has been running >30m. "
                f"Task: {(r['task'] or '')[:120]}. Check Phoenix or `botctl job <id>`."
            )

    async def _check_recent_failures(self) -> None:
        """3+ failures in the last hour → alert."""
        cutoff = datetime.now(UTC) - timedelta(hours=1)
        conn = connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE status = 'failed' AND finished_at > ?",
                (cutoff,),
            ).fetchone()
        finally:
            conn.close()
        n = row["n"]
        if n >= 3:
            await self._alert_once(
                "recent_failures", f"hour_{datetime.now(UTC).hour}",
                f"❗ {n} jobs have failed in the last hour. "
                "Run `botctl jobs --since 1h` to investigate.",
            )

    # -- helpers ----------------------------------------------------------

    async def _alert_once(self, kind: str, id_: str, message: str) -> None:
        key = (kind, id_)
        last = self._already_alerted.get(key)
        now = datetime.now(UTC)
        if last and now - last < timedelta(hours=12):
            return
        self._already_alerted[key] = now
        try:
            await self.notifier(message)
            log.info("watchdog.alerted", kind=kind, id=id_)
        except Exception as e:  # noqa: BLE001
            log.warning("watchdog.notify_failed", kind=kind, id=id_, error=str(e))
