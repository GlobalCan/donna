"""V60-3 / v0.6.3: jobs.schedule_id — back-link from job to originating schedule.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-02

Codex 2026-05-02 review on the overnight plan flagged that
`target_channel_id` on `schedules` is "semantically half-wired":

- The column is set by the modal flow (slack_ux.py /donna_schedule
  view-submit) and CLI (botctl schedule add --discord-channel).
- The runtime path (`_resolve_channel_for_job`) doesn't read it. It
  reads `threads.channel_id` via `jobs.thread_id`.
- Because the modal also creates a thread with `channel_id=target_channel_id`
  and sets `schedules.thread_id` pointing there, V50-2 (channel-target
  schedules) live-validated correctly via the thread path. But:
   1. Operator can `UPDATE schedules SET target_channel_id = 'C_NEW'`
      and the runtime path silently ignores the change because thread_id
      still points to the old thread.
   2. Future "edit destination" UI can't simply update target_channel_id.
   3. The docstring on `_resolve_channel_for_job` claims "priority 1:
      schedule.target_channel_id" but the implementation does no such
      thing — drift between contract and reality.

Morning brief (v0.7.0) will compound this risk because the operator will
want to redirect briefs at runtime without re-creating the schedule.

Fix: add a `jobs.schedule_id` column and propagate it from
`Scheduler._fire`. The resolver becomes:

    1. If job.schedule_id set AND that schedule has target_channel_id
       set, return target_channel_id (canonical for scheduled jobs).
    2. Otherwise, fall back to threads.channel_id via job.thread_id
       (existing behavior for DM / app_mention origin).

WIPED: nothing.

PRESERVED: every existing job row gets schedule_id=NULL via the
ADD COLUMN default. Existing scheduled jobs (created before this
migration) continue to resolve via thread.channel_id (existing
behavior); only new scheduled jobs use the canonical path.
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ADD COLUMN schedule_id TEXT")
    # Index supports the resolver's lookup path (job_id -> schedule_id ->
    # schedules row) and future "list jobs from this schedule" queries.
    op.execute("CREATE INDEX ix_jobs_schedule ON jobs(schedule_id)")


def downgrade() -> None:
    raise NotImplementedError(
        "Forward-only per docs/SCHEMA_LIFECYCLE.md. Recover from "
        "legacy/v0.6.2 git tag if a downgrade is genuinely needed."
    )
