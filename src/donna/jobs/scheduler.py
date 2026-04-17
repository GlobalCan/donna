"""Cron scheduler — the only proactive trigger in v1.

Polls the `schedules` table once a minute. For any schedule whose next_run_at
has passed, enqueues a job (same `jobs` table as interactive requests — the
worker processes both identically) and updates next_run_at.
"""
from __future__ import annotations

import asyncio

from ..logging import get_logger
from ..memory import jobs as jobs_mod
from ..memory import schedules as sched_mod
from ..memory.db import connect, transaction
from ..types import JobMode

log = get_logger(__name__)


class Scheduler:
    def __init__(self) -> None:
        self.shutdown = asyncio.Event()

    async def run(self) -> None:
        log.info("scheduler.start")
        while not self.shutdown.is_set():
            try:
                await self._tick()
            except Exception as e:  # noqa: BLE001
                log.exception("scheduler.tick_failed", error=str(e))
            await asyncio.sleep(60)

    async def _tick(self) -> None:
        conn = connect()
        try:
            due = sched_mod.due_schedules(conn)
        finally:
            conn.close()
        for s in due:
            await self._fire(s)

    async def _fire(self, sched: dict) -> None:
        conn = connect()
        try:
            with transaction(conn):
                mode = JobMode(sched.get("mode", "chat"))
                jid = jobs_mod.insert_job(
                    conn,
                    task=sched["task"],
                    agent_scope=sched.get("agent_scope", "orchestrator"),
                    mode=mode,
                )
                sched_mod.mark_ran(conn, schedule_id=sched["id"], cron_expr=sched["cron_expr"])
            log.info("scheduler.fired", schedule_id=sched["id"], job_id=jid)
        except Exception as e:  # noqa: BLE001
            log.exception("scheduler.fire_failed", schedule_id=sched["id"], error=str(e))
        finally:
            conn.close()

    async def stop(self) -> None:
        self.shutdown.set()
