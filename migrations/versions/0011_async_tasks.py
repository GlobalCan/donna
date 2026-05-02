"""V0.6 #2: async_tasks table — supervised async work queue.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-02

v0.5.2 introduced the first fire-and-forget async path: `JobContext.open`
post-finalize hook spawned `asyncio.create_task(_backfill_safe_summary(...))`
without supervision. v0.5.1 added a second: operator-alert DMs via
`loop.create_task(_maybe_alert_operator(...))`. Codex's 2026-05-01 review
flagged this pattern as "architecturally sloppy — fire-and-forget is
unacceptable in always-on infra." Both calls would simply be lost if the
worker/bot died mid-task: safe_summary stays NULL, alerts go undelivered.

Fix: a single DB-backed work queue with lease/heartbeat semantics
(parallel to the `jobs` table but lighter — these tasks have no agent
loop, no checkpoints, no tool calls). Each row carries a `kind` so
distinct runners (worker for sanitization, bot for delivery alerts)
can claim only the kinds they handle.

Schema highlights:
  - `kind` (TEXT) — discriminator. Runners filter by kind so multi-process
    deployments don't fight over each other's tasks.
  - `payload` (TEXT JSON) — task-specific input. Kept loosely typed; each
    handler validates its own shape.
  - `scheduled_for` — supports delayed enqueue (retry backoff lives here).
  - `locked_until` + `locked_by` — lease semantics. Stale claim recovery
    re-queues tasks whose holder died mid-execution.
  - `attempts` + `last_error` — observability without grepping logs.

Status state machine: pending -> running -> {done | failed | pending again}.
`failed` is terminal; reached after MAX_ATTEMPTS unrecoverable retries or
when a handler explicitly marks a task non-retryable.
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE async_tasks (
            id              TEXT PRIMARY KEY,
            kind            TEXT NOT NULL,
            payload         TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            attempts        INTEGER NOT NULL DEFAULT 0,
            last_error      TEXT,
            scheduled_for   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at      TIMESTAMP,
            finished_at     TIMESTAMP,
            locked_until    TIMESTAMP,
            locked_by       TEXT
        )
    """)
    # Hot path index: pending tasks by (scheduled_for, kind) so claim_one
    # is a fast O(log n) seek-then-filter.
    op.execute(
        "CREATE INDEX ix_async_tasks_pending "
        "ON async_tasks(status, scheduled_for, kind)"
    )
    # Recovery scan index: find running tasks whose lease has expired.
    op.execute(
        "CREATE INDEX ix_async_tasks_locked "
        "ON async_tasks(status, locked_until)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_async_tasks_locked")
    op.execute("DROP INDEX IF EXISTS ix_async_tasks_pending")
    op.execute("DROP TABLE IF EXISTS async_tasks")
