"""Worker runner — pops jobs, runs them, honors MAX_CONCURRENT_JOBS."""
from __future__ import annotations

import asyncio
import socket

from ..agent.loop import JobRenewer, run_job
from ..config import settings
from ..logging import get_logger
from ..memory import brief_runs as brief_runs_mod
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
                # V70-1 (v0.7.3): on claim (job → running), mirror onto
                # brief_runs.status so `botctl brief-runs list` reflects
                # in-flight state instead of perma-'queued'. Same
                # transaction as the claim itself so the two writes are
                # atomic. No-op for non-brief jobs (UPDATE matches 0 rows).
                if job is not None:
                    brief_runs_mod.update_status_by_job_id(
                        conn, job_id=job.id, status="running",
                    )
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
                # Owner-guarded FAILED write (cross-vendor review #11 / Codex
                # GPT-5 RF). Before this fix, a stale worker whose lease was
                # already reclaimed would still write FAILED on its way out,
                # potentially clobbering a recovered/completed job's status.
                # Symmetric to the v0.3.3 #23 owner guard on
                # consent._persist_pending. set_status returns False when the
                # owner mismatches; we just log and move on.
                with transaction(conn):
                    ok = jobs_mod_.set_status(
                        conn, job_id, JobStatus.FAILED,
                        error=str(e), worker_id=self.worker_id,
                    )
                    if ok:
                        # V70-1 (v0.7.3): mirror FAILED onto brief_runs so
                        # the operator panel doesn't lie about a brief that
                        # crashed. No-op for non-brief jobs (0 rows).
                        # Inside the same owner-guarded transaction so a
                        # lease-lost set_status (ok=False) doesn't
                        # accidentally flip brief_runs of the new owner.
                        brief_runs_mod.update_status_by_job_id(
                            conn, job_id=job_id, status="failed",
                        )
                if not ok:
                    log.info(
                        "worker.failed_write_skipped_lease_lost",
                        job_id=job_id, worker_id=self.worker_id,
                    )
            finally:
                conn.close()
        finally:
            self.semaphore.release()

    async def stop(self) -> None:
        self.shutdown.set()
        for t in list(self.active):
            t.cancel()
