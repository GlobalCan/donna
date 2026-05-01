"""V50-1: dead-letter table + retry tracking for Slack outbox drainer.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-01

Bug surfaced in v0.5.0 live smoke (2026-05-01). The Slack adapter's outbox
drainer treats every chat.postMessage failure as transient: leaves the row,
retries every ~1.5s. For terminal Slack errors (not_in_channel,
channel_not_found, is_archived, account_inactive, invalid_auth, token_revoked,
etc.) this is an infinite retry storm. Operator hit it during smoke when a
stale outbox row referenced a channel where Donna wasn't a member; thousands
of identical errors at 1.5s intervals before manual SQL DELETE.

Fix: classify Slack errors into transient / terminal / unknown and route:
  - transient -> leave row, retry next poll, bump attempt_count
  - terminal  -> delete row, log WARN, throttled DM to operator
  - unknown   -> move to outbox_dead_letter, log WARN, throttled DM to operator

This migration adds:
  1. outbox_dead_letter table (capture + provenance + diagnostic state)
  2. outbox_updates.attempt_count + last_error + last_attempt_at columns
     so transient retries are visible while the row is still alive
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Dead-letter table for terminal/unknown delivery failures.
    op.execute("""
        CREATE TABLE outbox_dead_letter (
            id                  TEXT PRIMARY KEY,
            source_table        TEXT NOT NULL,
            source_id           TEXT NOT NULL,
            job_id              TEXT,
            channel_id          TEXT,
            thread_ts           TEXT,
            payload             TEXT,
            tainted             INTEGER NOT NULL DEFAULT 0,
            error_code          TEXT NOT NULL,
            error_class         TEXT NOT NULL,
            attempt_count       INTEGER NOT NULL DEFAULT 1,
            first_attempt_at    TIMESTAMP,
            last_attempt_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            moved_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX ix_outbox_dl_source "
        "ON outbox_dead_letter(source_table, source_id)"
    )
    op.execute("CREATE INDEX ix_outbox_dl_job ON outbox_dead_letter(job_id)")
    op.execute("CREATE INDEX ix_outbox_dl_moved ON outbox_dead_letter(moved_at)")

    # 2. Retry visibility on outbox_updates so operators can see stuck rows
    #    without grepping logs.
    op.execute(
        "ALTER TABLE outbox_updates ADD COLUMN attempt_count "
        "INTEGER NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE outbox_updates ADD COLUMN last_error TEXT")
    op.execute("ALTER TABLE outbox_updates ADD COLUMN last_attempt_at TIMESTAMP")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_outbox_dl_moved")
    op.execute("DROP INDEX IF EXISTS ix_outbox_dl_job")
    op.execute("DROP INDEX IF EXISTS ix_outbox_dl_source")
    op.execute("DROP TABLE IF EXISTS outbox_dead_letter")
    op.execute("ALTER TABLE outbox_updates DROP COLUMN last_attempt_at")
    op.execute("ALTER TABLE outbox_updates DROP COLUMN last_error")
    op.execute("ALTER TABLE outbox_updates DROP COLUMN attempt_count")
