"""pending_consents — persist consent requests across restarts

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-17

Codex review #5 fix. Previously consent.check() waited on an in-memory
future. A restart during consent silently dropped the request. Now:
 - When a consent request is enqueued, a row is written to pending_consents
   and the job is marked status='paused_awaiting_consent'.
 - On startup, the worker finds these jobs and re-posts the prompts to
   Discord before resuming.
 - When the user responds, the row is deleted and job.status is set back
   to 'running' so the worker can continue.
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pending_consents (
            id              TEXT PRIMARY KEY,
            job_id          TEXT NOT NULL REFERENCES jobs(id),
            tool_name       TEXT NOT NULL,
            arguments       TEXT NOT NULL,              -- JSON
            tainted         INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at      TIMESTAMP                   -- optional, for auto-expiry
        )
    """)
    op.execute("CREATE INDEX ix_pending_consents_job ON pending_consents(job_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pending_consents")
