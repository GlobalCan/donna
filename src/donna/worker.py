"""Donna — worker process entry point.

Runs the job runner (lease/heartbeat/checkpoint) and cron scheduler in one
asyncio loop. Bot and worker processes share /data/donna.db but have distinct
DB ownership responsibilities (see memory/db.py docs).
"""
from __future__ import annotations

import asyncio
import signal
import sys

from .config import settings
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

    async def _graceful_shutdown() -> None:
        await worker.stop()
        await scheduler.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(_graceful_shutdown()))
        except NotImplementedError:
            # Windows: signal handlers via add_signal_handler aren't supported
            pass

    await asyncio.gather(worker.run(), scheduler.run())


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
