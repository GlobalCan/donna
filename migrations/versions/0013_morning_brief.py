"""V0.7.0: morning brief — schedules.kind + payload_json + brief_runs idempotency.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-02

v0.7.0 ships the first proactive product workflow: a daily morning
briefing that exercises every v0.6 piece (scheduler, channel-target
delivery, async task runner, cost guards, retention).

Codex 2026-05-02 review on the overnight plan:

- Use `schedules` as cron/destination source of truth — don't create
  a parallel brief_configs table with its own cron.
- Discriminate kinds via a single `kind` column + payload_json.
- Add idempotency BEFORE shipping: `brief_runs(schedule_id, fire_key)`
  with a unique key. Two scheduler ticks within the same minute (or
  multiple worker processes that may exist later) must produce
  exactly one delivered brief.
- Brief composition is real long-running agent work (news + search +
  model + synthesis); do NOT run it in AsyncTaskRunner — 60s lease,
  no heartbeat, double-run risk. Use the normal `jobs` table /
  JobContext path. AsyncTaskRunner is fine only as a short fanout.

Schema:

- schedules.kind ('task' default | 'morning_brief'): discriminator for
  Scheduler._fire dispatch. Existing rows stay 'task' (the legacy
  free-form scheduled task semantics).

- schedules.payload_json (TEXT, nullable): kind-specific config.
  For 'morning_brief': {"topics": [...], "tz": "America/New_York",
  "max_topics": 5}.

- brief_runs (NEW table): one row per scheduled-fire attempt.
  - schedule_id (FK -> schedules.id)
  - fire_key (TEXT) — UTC datetime of the intended fire, truncated to
    the minute. Two simultaneous scheduler ticks compute the same
    fire_key, so UNIQUE(schedule_id, fire_key) deduplicates them.
  - job_id (FK -> jobs.id) — the chat-mode job that's executing the
    brief; readable later via botctl.
  - status (queued | running | done | failed) — observability without
    joining jobs.

WIPED: nothing.

PRESERVED: all existing schedule rows get kind='task' via the column
default. Scheduler.\_fire's existing path remains the kind='task'
handler.
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE schedules ADD COLUMN kind TEXT NOT NULL DEFAULT 'task'"
    )
    op.execute("ALTER TABLE schedules ADD COLUMN payload_json TEXT")
    op.execute("CREATE INDEX ix_schedules_kind ON schedules(kind)")

    op.execute("""
        CREATE TABLE brief_runs (
            id            TEXT PRIMARY KEY,
            schedule_id   TEXT NOT NULL REFERENCES schedules(id),
            fire_key      TEXT NOT NULL,
            job_id        TEXT NOT NULL REFERENCES jobs(id),
            status        TEXT NOT NULL DEFAULT 'queued',
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(schedule_id, fire_key)
        )
    """)
    # Lookup hot path: "did we already fire this minute?"
    op.execute(
        "CREATE INDEX ix_brief_runs_lookup "
        "ON brief_runs(schedule_id, fire_key)"
    )
    # Operator visibility: "show me recent brief runs"
    op.execute(
        "CREATE INDEX ix_brief_runs_recent ON brief_runs(created_at DESC)"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Forward-only per docs/SCHEMA_LIFECYCLE.md. Recover from "
        "legacy/v0.6.3 git tag if a downgrade is genuinely needed."
    )
