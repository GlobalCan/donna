"""Cron scheduler — the only proactive trigger in v1.

Polls the `schedules` table once a minute. For any schedule whose next_run_at
has passed, enqueues a job (same `jobs` table as interactive requests — the
worker processes both identically) and updates next_run_at.
"""
from __future__ import annotations

import asyncio

from croniter import croniter

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
        # Belt-and-suspenders: if a row somehow has a broken cron_expr
        # (data corruption, manual SQL bypassing `insert_schedule`'s
        # validator), `mark_ran` raises inside the transaction. Without
        # this guard the schedule keeps appearing in `due_schedules` every
        # tick forever and every tick emits an exception — noisy log spam
        # for what should be "this schedule is broken, stop retrying."
        # Auto-disable on parse failure with a distinct log line.
        if not croniter.is_valid(sched["cron_expr"]):
            log.error(
                "scheduler.disabling_bad_cron",
                schedule_id=sched["id"],
                cron_expr=sched["cron_expr"],
            )
            conn = connect()
            try:
                with transaction(conn):
                    sched_mod.disable_schedule(conn, sched["id"])
            finally:
                conn.close()
            return

        conn = connect()
        try:
            with transaction(conn):
                mode = JobMode(sched.get("mode", "chat"))
                # Propagate thread_id from the schedule so the worker's
                # finalize/outbox path can deliver the reply back to the
                # Discord channel where /schedule was invoked. NULL is
                # legitimate for CLI-created schedules; the resulting
                # job runs but has no destination — visible only via
                # botctl jobs. Bug fix 2026-04-30 (PR fix/scheduler-thread-
                # id-delivery); pre-fix every scheduled job got
                # thread_id=NULL regardless of origin.
                jid = jobs_mod.insert_job(
                    conn,
                    task=sched["task"],
                    agent_scope=sched.get("agent_scope", "orchestrator"),
                    mode=mode,
                    thread_id=sched.get("thread_id"),
                    # v0.6.3: back-link the job to its schedule so the
                    # Slack adapter resolver can prefer
                    # schedules.target_channel_id over thread.channel_id.
                    # Without this, every scheduled job resolved via the
                    # thread path even when the operator had explicitly
                    # set a different target_channel_id (silent drift).
                    schedule_id=sched["id"],
                )
                sched_mod.mark_ran(conn, schedule_id=sched["id"], cron_expr=sched["cron_expr"])
            log.info(
                "scheduler.fired",
                schedule_id=sched["id"],
                job_id=jid,
                thread_id=sched.get("thread_id"),
            )
        except Exception as e:  # noqa: BLE001
            log.exception("scheduler.fire_failed", schedule_id=sched["id"], error=str(e))
        finally:
            conn.close()

    async def stop(self) -> None:
        self.shutdown.set()
