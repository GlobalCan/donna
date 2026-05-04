"""V0.7.3: consent batching + alert digest.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-02

v0.7.3 addresses Codex 2026-05-01's "operator fatigue" finding by
collapsing two N-into-1 problems:

1. **Consent batching** — when the agent emits two `save_artifact` (or
   any other consent-required tool) uses in one model turn, pre-fix
   each one fired its own ✅/❌ button prompt. With N=4 the operator
   was tapping eight buttons in sequence. Now: one batch prompt with
   "Approve all / Decline all" + a "Show details" overflow that
   expands into per-tool decisions if needed.

   New `consent_batches` table holds the coordinator row. Existing
   `pending_consents` rows gain `batch_id` (nullable FK). When
   `batch_id IS NOT NULL`, the Slack drainer posts ONE merged prompt
   covering all rows in that batch instead of N individual prompts.

2. **Alert digest** — pre-fix every dead-letter, budget threshold,
   stuck-job, and consent-timeout fired its own DM. On a slow afternoon
   that pile-up could be 5+ DMs in 10 minutes. Now: when
   `DONNA_ALERT_DIGEST_INTERVAL_MIN > 0`, alerts are queued in
   `alert_digest_queue` and a background flusher batches them into one
   DM per interval. Default interval = 0 keeps the immediate-DM
   behavior so v0.7.x soak isn't disrupted; opt-in via env var or the
   new `/donna_alert_settings` command.

Schema:

- `pending_consents.batch_id` (TEXT, nullable, indexed): when not NULL,
  this row participates in a multi-tool batch and the bot routes its
  posting through the batch path. Approval semantics flow from the
  batch (Approve-All sets all rows' `approved=1`).

- `consent_batches` (NEW table): one row per multi-tool batch.
  - `id` (TEXT PRIMARY KEY) — `cb_<hex12>`
  - `job_id` (FK -> jobs.id)
  - `worker_id` (TEXT) — owner-guard for batch creation
  - `tainted` (INTEGER) — 1 if any tool in the batch is tainted; the
    rendered prompt uses the more conservative icon
  - `approved` (INTEGER NULL) — NULL=pending, 1=approve-all clicked,
    0=decline-all clicked, 2=expanded-to-individual (operator hit
    "Show details", each tool now needs its own decision)
  - `posted_channel_id` / `posted_message_id` — set when the bot
    successfully posts the merged prompt
  - `decided_at` (TIMESTAMP) — when the batch resolved
  - `created_at` (TIMESTAMP) — for ordering + GC

- `alert_digest_queue` (NEW table): one row per pending alert.
  - `id` (TEXT PRIMARY KEY) — `aq_<hex12>`
  - `kind` (TEXT) — 'delivery_failure' | 'budget' | 'stuck_consent' |
    'stuck_running' | 'recent_failures' | 'consent_timeout'
  - `severity` (TEXT) — 'info' | 'warning' | 'error' (rendering hint)
  - `message` (TEXT) — pre-rendered alert body line(s)
  - `dedup_key` (TEXT) — same key the in-memory throttle used; the
    digest flusher collapses adjacent-same-key rows so 50 dead-letter
    rows from one broken channel show as "(50x) channel C012 dead-
    lettered" rather than 50 lines.
  - `created_at` (TIMESTAMP) — flusher cutoff
  - `delivered_at` (TIMESTAMP NULL) — set when the row is included in
    a successfully posted DM; NULL means still queued

WIPED: nothing.

PRESERVED: all existing pending_consents rows have batch_id IS NULL,
so they continue to flow through the legacy single-tool path
unchanged. Empty `consent_batches` table is a no-op.
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- consent batching ----------------------------------------------------
    op.execute(
        "ALTER TABLE pending_consents ADD COLUMN batch_id TEXT"
    )
    op.execute(
        "CREATE INDEX ix_pending_consents_batch ON pending_consents(batch_id) "
        "WHERE batch_id IS NOT NULL"
    )

    op.execute("""
        CREATE TABLE consent_batches (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES jobs(id),
            worker_id           TEXT,
            tainted             INTEGER NOT NULL DEFAULT 0,
            approved            INTEGER,
            posted_channel_id   TEXT,
            posted_message_id   TEXT,
            decided_at          TIMESTAMP,
            created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_consent_batches_job ON consent_batches(job_id)")
    op.execute(
        "CREATE INDEX ix_consent_batches_unposted "
        "ON consent_batches(posted_message_id, approved) "
        "WHERE posted_message_id IS NULL AND approved IS NULL"
    )

    # --- alert digest --------------------------------------------------------
    op.execute("""
        CREATE TABLE alert_digest_queue (
            id              TEXT PRIMARY KEY,
            kind            TEXT NOT NULL,
            severity        TEXT NOT NULL DEFAULT 'warning',
            message         TEXT NOT NULL,
            dedup_key       TEXT,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            delivered_at    TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX ix_alert_digest_pending "
        "ON alert_digest_queue(delivered_at, created_at) "
        "WHERE delivered_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_alert_digest_dedup "
        "ON alert_digest_queue(dedup_key, created_at) "
        "WHERE delivered_at IS NULL AND dedup_key IS NOT NULL"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Forward-only per docs/SCHEMA_LIFECYCLE.md. Recover from "
        "legacy/v0.7.2 git tag if a downgrade is genuinely needed."
    )
