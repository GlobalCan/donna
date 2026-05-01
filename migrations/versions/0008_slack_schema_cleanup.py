"""platform-agnostic schema cleanup for v0.5.0 — Discord → Slack migration.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-01

v0.5.0 retools the adapter from Discord to Slack. The schema was
Discord-shaped: integer channel/message IDs, columns named `discord_*`.
Slack uses string `ts` IDs ("1234567890.123456") and we want
platform-agnostic column names so the adapter abstraction stays clean
(Codex review 2026-05-01).

Changes:

1. Rename columns:
   - threads.discord_channel    → channel_id
   - threads.discord_thread     → thread_external_id
   - messages.discord_msg       → external_msg_id

2. Change types from INTEGER to TEXT (Slack ts is a string):
   - outbox_asks.posted_channel_id
   - outbox_asks.posted_message_id
   - pending_consents.posted_channel_id
   - pending_consents.posted_message_id

3. Add Slack-specific columns:
   - schedules.target_channel_id  TEXT (nullable)
       — when /schedule fires, post the reply here instead of the
         originating DM. Operator UX win: morning brief → #morning-brief
         channel, not cluttering DM scrollback.
   - schedules.target_thread_ts   TEXT (nullable)
       — when set, reply in the specified thread (Slack thread parent ts).

4. Wipe Discord-platform-bound rows (operator confirmed: no production
   data worth migrating). Keeps:
     - knowledge_sources / knowledge_chunks (the 402-chunk Huck Finn
       corpus)
     - artifacts
     - cost_ledger / traces / tool_calls
     - model_runtimes / agent_prompts / heuristics
   Wipes:
     - threads (Discord channel/thread IDs)
     - messages (Discord-bound)
     - jobs (test data, all terminal)
     - outbox_updates / outbox_asks / pending_consents (operational state)
     - schedules (FK refs to threads we're dropping; test data only)

DELETE order respects FK direction (children first) even though SQLite
doesn't enforce FKs by default. Defensive against pragma changes.
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Wipe Discord-platform-bound data.
    # Order: children before parents to satisfy any FK enforcement.
    op.execute("DELETE FROM outbox_updates")
    op.execute("DELETE FROM outbox_asks")
    op.execute("DELETE FROM pending_consents")
    # tool_calls references jobs(id); some rows reference scope ids that
    # are about to be wiped. Wiping all keeps audit trail consistent.
    op.execute("DELETE FROM tool_calls")
    op.execute("DELETE FROM messages")
    op.execute("DELETE FROM schedules")
    op.execute("DELETE FROM jobs")
    op.execute("DELETE FROM threads")

    # 2. Rename Discord-named columns to platform-agnostic.
    # SQLite 3.25+ supports ALTER TABLE ... RENAME COLUMN; Python 3.14's
    # bundled sqlite is well past that.
    op.execute("ALTER TABLE threads RENAME COLUMN discord_channel TO channel_id")
    op.execute("ALTER TABLE threads RENAME COLUMN discord_thread TO thread_external_id")
    op.execute("ALTER TABLE messages RENAME COLUMN discord_msg TO external_msg_id")

    # 3. Change types of posted_*_id columns from INTEGER to TEXT.
    # SQLite doesn't have clean ALTER COLUMN type change, so we drop +
    # recreate. Data is already wiped (step 1), so no copy needed.
    op.execute("DROP INDEX IF EXISTS ix_outbox_asks_job")
    op.execute("DROP INDEX IF EXISTS ix_outbox_asks_posted_msg")
    op.execute("DROP INDEX IF EXISTS ix_outbox_asks_unposted")
    op.execute("DROP TABLE outbox_asks")
    op.execute("""
        CREATE TABLE outbox_asks (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES jobs(id),
            question            TEXT NOT NULL,
            posted_channel_id   TEXT,
            posted_message_id   TEXT,
            reply               TEXT,
            replied_at          TIMESTAMP,
            created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at          TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_outbox_asks_job ON outbox_asks(job_id)")
    op.execute("CREATE INDEX ix_outbox_asks_posted_msg ON outbox_asks(posted_message_id)")
    op.execute(
        "CREATE INDEX ix_outbox_asks_unposted ON outbox_asks(posted_message_id) "
        "WHERE posted_message_id IS NULL"
    )

    op.execute("DROP INDEX IF EXISTS ix_pending_consents_posted_msg")
    op.execute("DROP TABLE pending_consents")
    op.execute("""
        CREATE TABLE pending_consents (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES jobs(id),
            tool_name           TEXT NOT NULL,
            arguments           TEXT NOT NULL,
            tainted             INTEGER NOT NULL DEFAULT 0,
            approved            INTEGER,
            decided_at          TIMESTAMP,
            posted_channel_id   TEXT,
            posted_message_id   TEXT,
            created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX ix_pending_consents_posted_msg "
        "ON pending_consents(posted_message_id)"
    )

    # 4. Add Slack-specific scheduling columns.
    op.execute("ALTER TABLE schedules ADD COLUMN target_channel_id TEXT")
    op.execute("ALTER TABLE schedules ADD COLUMN target_thread_ts TEXT")
    op.execute(
        "CREATE INDEX ix_schedules_target_channel ON schedules(target_channel_id)"
    )


def downgrade() -> None:
    # No downgrade — v0.5.0 is a forward-only platform migration. If we
    # need to revive Discord we revive from the legacy/v0.4.4-discord
    # tag, not by walking this migration backwards. Re-installing the
    # old schema would orphan whatever Slack-shaped data exists.
    raise NotImplementedError(
        "v0.5.0 (Slack) is forward-only. Revive Discord from "
        "git tag legacy/v0.4.4-discord."
    )
