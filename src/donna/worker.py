"""Donna — worker process entry point.

Runs the job runner (lease/heartbeat/checkpoint) and cron scheduler in one
asyncio loop. Bot and worker processes share /data/donna.db but have distinct
DB ownership responsibilities (see memory/db.py docs).
"""
from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from .agent.context import handle_safe_summary_backfill
from .config import settings
from .jobs.async_runner import AsyncTaskRunner
from .jobs.runner import Worker
from .jobs.scheduler import Scheduler
from .logging import configure_logging, get_logger
from .observability import otel
from .tools import register_all_v1_tools


async def _run() -> None:
    configure_logging()
    log = get_logger("donna.worker")
    s = settings()
    if not s.anthropic_api_key:
        log.error("config.missing ANTHROPIC_API_KEY")
        sys.exit(2)

    register_all_v1_tools()
    otel.initialize_tracing()

    worker = Worker()
    scheduler = Scheduler()
    # v0.6 #2: supervised async runner. Worker handles background tasks
    # spawned by job finalize hooks (currently safe_summary backfill;
    # future: morning brief composition, web monitor diff, etc.). Each
    # row in `async_tasks` is durably persisted, leased, and retried —
    # replacing v0.5.2's fire-and-forget asyncio.create_task pattern.
    async_runner = AsyncTaskRunner(
        worker_id="worker-async",
        kinds=["safe_summary_backfill"],
        handlers={
            "safe_summary_backfill": handle_safe_summary_backfill,
        },
    )

    async def _graceful_shutdown() -> None:
        await worker.stop()
        await scheduler.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Windows: signal handlers via add_signal_handler aren't supported
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(_graceful_shutdown()))

    await asyncio.gather(worker.run(), scheduler.run(), async_runner.run())


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
