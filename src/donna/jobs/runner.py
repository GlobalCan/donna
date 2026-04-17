"""Worker runner — pops jobs, runs them, honors MAX_CONCURRENT_JOBS."""
from __future__ import annotations

import asyncio
import socket

from ..agent.loop import JobRenewer, run_job
from ..config import settings
from ..logging import get_logger
from ..memory import jobs as jobs_mod
from ..memory.db import connect, transaction

log = get_logger(__name__)


class Worker:
    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}-{id(self)}"
        self.semaphore = asyncio.Semaphore(settings().max_concurrent_jobs)
        self.active: set[asyncio.Task] = set()
        self.shutdown = asyncio.Event()

    async def run(self) -> None:
        log.info("worker.start", worker_id=self.worker_id,
                 max_concurrent=settings().max_concurrent_jobs)
        while not self.shutdown.is_set():
            try:
                await self._tick()
            except Exception as e:  # noqa: BLE001
                log.exception("worker.tick_failed", error=str(e))
                await asyncio.sleep(5)

    async def _tick(self) -> None:
        # Only claim if capacity available
        if self.semaphore.locked():
            await asyncio.sleep(0.5)
            return

        conn = connect()
        try:
            with transaction(conn):
                job = jobs_mod.claim_next_queued(conn, worker_id=self.worker_id)
        finally:
            conn.close()

        if job is None:
            await asyncio.sleep(1.0)
            return

        log.info("worker.claimed", job_id=job.id, scope=job.agent_scope, mode=job.mode.value)
        await self.semaphore.acquire()
        task = asyncio.create_task(self._run_one(job.id))
        self.active.add(task)
        task.add_done_callback(self.active.discard)

    async def _run_one(self, job_id: str) -> None:
        renewer = JobRenewer(job_id, self.worker_id)
        try:
            await run_job(job_id, self.worker_id, renewer=renewer)
        except Exception as e:  # noqa: BLE001
            log.exception("worker.job_failed", job_id=job_id, error=str(e))
            conn = connect()
            try:
                from ..memory import jobs as jobs_mod_
                from ..types import JobStatus
                jobs_mod_.set_status(conn, job_id, JobStatus.FAILED, error=str(e))
            finally:
                conn.close()
        finally:
            self.semaphore.release()

    async def stop(self) -> None:
        self.shutdown.set()
        for t in list(self.active):
            t.cancel()
