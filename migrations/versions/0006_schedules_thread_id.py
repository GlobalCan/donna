"""schedules.thread_id — record the Discord destination so scheduler-fired
jobs can deliver back to where the schedule was created.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-30

Bug surfaced 2026-04-30 during the first live scheduler smoke test
(docs/SCHEDULER_SMOKE_TEST.md). The scheduler ticked, fired jobs, the
worker ran them to status=done — but no Discord message ever arrived.

Root cause: `Scheduler._fire` calls `insert_job` without `thread_id`,
because `schedules` has no column to remember which Discord
channel/thread spawned the schedule. With `thread_id=NULL`,
`_resolve_channel_for_job` in the adapter returns None and
`_post_update` returns False, so the outbox row sits forever and the
operator sees nothing.

Fix: add a nullable `thread_id` column to schedules. `/schedule` (Discord
slash) populates it from the interaction's channel via
`get_or_create_thread`. `botctl schedule add` (CLI) leaves it NULL by
default — CLI-created schedules fire but don't deliver to Discord
(visible only via `botctl jobs`); operators who want delivery from CLI
can pass `--discord-channel <id>`.

The column is nullable so pre-existing schedule rows survive the
migration unchanged. They'll continue to fire-without-delivery until
manually recreated via `/schedule`. For the operator's current
production state at v0.4.2 the only existing schedule is the
smoke-test `* * * * *` which gets disabled anyway.
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable + no FK enforcement so the migration is forward-only safe
    # even if a schedule's source thread later gets pruned. (Threads are
    # never deleted in v1, but the FK would force ON DELETE behaviour we
    # haven't designed yet.)
    op.execute("ALTER TABLE schedules ADD COLUMN thread_id TEXT")
    op.execute("CREATE INDEX ix_schedules_thread ON schedules(thread_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_schedules_thread")
    op.execute("ALTER TABLE schedules DROP COLUMN thread_id")
