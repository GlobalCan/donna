"""Async-task runner — the supervisor for `async_tasks` queue rows.

Each runner instance polls the DB for pending tasks of a configured set
of kinds, dispatches each to its registered handler, and records the
outcome with retry semantics. Distinct from `Worker` (in `jobs/runner.py`)
which runs the full agent loop on `jobs` rows; this is much lighter.

Usage:

    runner = AsyncTaskRunner(
        worker_id="bot-async",
        kinds=["operator_alert"],
        handlers={"operator_alert": _handle_operator_alert},
    )
    await runner.run()  # forever loop

Failure modes handled:

  - Handler raises -> fail() the task; `attempts < max` re-queues with
    backoff; otherwise marks 'failed' permanently. Crashes the runner
    only if the DB write itself fails.
  - Runner dies mid-task -> next runner's `recover_stale` (called before
    each claim_one) re-queues stuck rows.
  - Concurrent runners on the same kind set -> claim_one's atomic UPDATE
    is race-safe; only one runner gets each row.
  - Handler is missing for a claimed kind -> log + immediately fail.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from ..logging import get_logger
from ..memory import async_tasks as at_mod
from ..memory.db import connect, transaction

log = get_logger(__name__)


# A handler receives the deserialized payload dict and returns when done.
# Raise on failure — the runner records and retries per policy.
HandlerFn = Callable[[dict], Awaitable[None]]


class AsyncTaskRunner:
    """Polls async_tasks for the configured kinds and dispatches to
    registered handlers. Run one of these per process that needs to
    consume tasks of certain kinds (e.g. bot for operator_alert,
    worker for safe_summary_backfill).
    """

    # How often to poll for work when idle. 1s feels instant for the
    # human-perceived async paths (alert DMs, sanitizer backfill) without
    # spinning hot.
    POLL_INTERVAL_S = 1.0
    # Lease window — long enough for the slowest expected handler run
    # (Haiku sanitize on a 4000-char tainted reply: typically ~3-5s).
    # Stale recovery picks up anything that exceeds this.
    LEASE_SECONDS = 60
    # Max retries before a task is dead-lettered to status='failed'.
    MAX_ATTEMPTS = 3
    # Linear backoff base for retries (seconds * attempt count).
    RETRY_BACKOFF_S = 60

    def __init__(
        self,
        *,
        worker_id: str,
        kinds: list[str],
        handlers: dict[str, HandlerFn],
    ) -> None:
        if not kinds:
            raise ValueError("AsyncTaskRunner needs at least one kind")
        # Sanity: every kind must have a handler. Mismatch is a wiring
        # bug, not a runtime condition.
        missing = [k for k in kinds if k not in handlers]
        if missing:
            raise ValueError(
                f"AsyncTaskRunner kinds {missing} have no registered handler"
            )
        self.worker_id = worker_id
        self.kinds = list(kinds)
        self.handlers = dict(handlers)

    async def run(self) -> None:
        """Main poll loop. Cancel via task.cancel()."""
        log.info(
            "async_runner.start",
            worker_id=self.worker_id, kinds=self.kinds,
        )
        try:
            while True:
                await self._tick()
                await asyncio.sleep(self.POLL_INTERVAL_S)
        except asyncio.CancelledError:
            log.info("async_runner.cancelled", worker_id=self.worker_id)
            raise

    async def _tick(self) -> None:
        """One poll cycle: recover stale, claim one, dispatch."""
        # Recover stale leases first so a crashed runner's work re-enters
        # the queue. Cheap UPDATE; runs on every tick.
        try:
            conn = connect()
            try:
                with transaction(conn):
                    recovered = at_mod.recover_stale(
                        conn, worker_id=self.worker_id,
                    )
                if recovered:
                    log.info(
                        "async_runner.recovered_stale",
                        worker_id=self.worker_id, count=recovered,
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "async_runner.recover_failed",
                worker_id=self.worker_id, error=str(e),
            )

        # Claim one task. Empty result = nothing due; sleep then retry.
        try:
            conn = connect()
            try:
                with transaction(conn):
                    row = at_mod.claim_one(
                        conn,
                        worker_id=self.worker_id,
                        kinds=self.kinds,
                        lease_seconds=self.LEASE_SECONDS,
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "async_runner.claim_failed",
                worker_id=self.worker_id, error=str(e),
            )
            return
        if row is None:
            return

        await self._dispatch(row)

    async def _dispatch(self, row) -> None:
        task_id = row["id"]
        kind = row["kind"]
        handler = self.handlers.get(kind)
        if handler is None:
            # Shouldn't happen — we validated at construction. Defensive
            # only for edge cases like in-flight kind reconfiguration.
            log.error(
                "async_runner.no_handler",
                task_id=task_id, kind=kind, worker_id=self.worker_id,
            )
            await self._fail(
                task_id, f"no handler registered for kind={kind!r}",
            )
            return
        try:
            payload = json.loads(row["payload"])
        except json.JSONDecodeError as e:
            log.error(
                "async_runner.bad_payload",
                task_id=task_id, kind=kind, error=str(e),
            )
            await self._fail(task_id, f"payload not valid JSON: {e}")
            return

        try:
            await handler(payload)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "async_runner.handler_failed",
                task_id=task_id, kind=kind, error=str(e),
                attempts=row["attempts"],
            )
            await self._fail(task_id, str(e))
            return

        await self._complete(task_id)

    async def _complete(self, task_id: str) -> None:
        try:
            conn = connect()
            try:
                with transaction(conn):
                    at_mod.complete(
                        conn, task_id=task_id, worker_id=self.worker_id,
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "async_runner.complete_persist_failed",
                task_id=task_id, worker_id=self.worker_id, error=str(e),
            )

    async def _fail(self, task_id: str, error_msg: str) -> None:
        try:
            conn = connect()
            try:
                with transaction(conn):
                    at_mod.fail(
                        conn,
                        task_id=task_id,
                        worker_id=self.worker_id,
                        error_msg=error_msg,
                        max_attempts=self.MAX_ATTEMPTS,
                        retry_backoff_s=self.RETRY_BACKOFF_S,
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "async_runner.fail_persist_failed",
                task_id=task_id, worker_id=self.worker_id, error=str(e),
            )
