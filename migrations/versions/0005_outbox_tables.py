"""outbox tables + extend pending_consents for cross-process drain

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-22

Phase-1 live-run finding: send_update, ask_user, and consent all went
through in-memory `asyncio.Queue` objects. Donna runs as TWO processes
(donna.main + donna.worker), and an asyncio.Queue only exists inside
its own process. The worker wrote updates into its own queue; the bot
read from a separate empty queue in its own process. Jobs completed but
nothing ever reached Discord.

Consent was half-fixed in 0003 (pending_consents table) but the decision
itself still flowed through an in-memory Future, so it was broken too.

Fix: SQLite is the single source of truth. Every outbox message is a row.
Worker writes rows. Bot polls, posts, updates state. Tests run in-process
so they didn't catch this; the bug only shows up in production's two-process
configuration (which is also the docker-compose setup).
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- outbox_updates: fire-and-forget from worker; bot posts then deletes --
    op.execute("""
        CREATE TABLE outbox_updates (
            id          TEXT PRIMARY KEY,
            job_id      TEXT NOT NULL REFERENCES jobs(id),
            text        TEXT NOT NULL,
            tainted     INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_outbox_updates_created ON outbox_updates(created_at)")

    # --- outbox_asks: worker INSERTs then polls until reply arrives -----------
    op.execute("""
        CREATE TABLE outbox_asks (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES jobs(id),
            question            TEXT NOT NULL,
            posted_channel_id   INTEGER,     -- bot fills after posting
            posted_message_id   INTEGER,     -- bot fills after posting
            reply               TEXT,        -- bot fills on user reply
            replied_at          TIMESTAMP,
            created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at          TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_outbox_asks_job ON outbox_asks(job_id)")
    op.execute("CREATE INDEX ix_outbox_asks_posted_msg ON outbox_asks(posted_message_id)")
    op.execute("CREATE INDEX ix_outbox_asks_unposted ON outbox_asks(posted_message_id) WHERE posted_message_id IS NULL")

    # --- extend pending_consents with decision + posting state ---------------
    # `approved` is the worker's polling target (NULL = no decision yet).
    # `decided_at` is for audit.
    # posted_* let the bot know the row is already displayed and let the
    # reaction handler find the right row by message id.
    op.execute("ALTER TABLE pending_consents ADD COLUMN approved INTEGER")
    op.execute("ALTER TABLE pending_consents ADD COLUMN decided_at TIMESTAMP")
    op.execute("ALTER TABLE pending_consents ADD COLUMN posted_channel_id INTEGER")
    op.execute("ALTER TABLE pending_consents ADD COLUMN posted_message_id INTEGER")
    op.execute(
        "CREATE INDEX ix_pending_consents_posted_msg "
        "ON pending_consents(posted_message_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pending_consents_posted_msg")
    op.execute("DROP INDEX IF EXISTS ix_outbox_asks_unposted")
    op.execute("DROP INDEX IF EXISTS ix_outbox_asks_posted_msg")
    op.execute("DROP INDEX IF EXISTS ix_outbox_asks_job")
    op.execute("DROP INDEX IF EXISTS ix_outbox_updates_created")
    op.execute("DROP TABLE IF EXISTS outbox_updates")
    op.execute("DROP TABLE IF EXISTS outbox_asks")
    # SQLite 3.35+ supports DROP COLUMN (Python 3.14 ships with new-enough sqlite)
    op.execute("ALTER TABLE pending_consents DROP COLUMN posted_message_id")
    op.execute("ALTER TABLE pending_consents DROP COLUMN posted_channel_id")
    op.execute("ALTER TABLE pending_consents DROP COLUMN decided_at")
    op.execute("ALTER TABLE pending_consents DROP COLUMN approved")
