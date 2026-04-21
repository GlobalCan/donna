"""v1.1 Hermes-inspired additions

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-20

Pattern A from the Hermes adversarial review — cherry-picked mechanisms:

 1. model_runtimes registry: vendor abstraction as data, not slogan. Pricing
    and provider details live in a table. Adding OpenAI later is `INSERT INTO
    model_runtimes ...`, not a rewrite of model_adapter.
 2. threads.model_tier_override: powers the /model Discord command. User
    can switch tier for a specific conversation without touching env.
 3. jobs.compaction_log: compaction events reference pre-compaction
    artifact ids so the raw history is recoverable for audit.
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ModelRuntime registry
    op.execute("""
        CREATE TABLE model_runtimes (
            id                 TEXT PRIMARY KEY,
            provider           TEXT NOT NULL,      -- 'anthropic' | 'openai' | 'openrouter' | ...
            model_id           TEXT NOT NULL,      -- provider-specific id
            tier               TEXT NOT NULL,      -- 'fast' | 'strong' | 'heavy'
            api_base           TEXT,               -- NULL = provider default
            api_key_env        TEXT NOT NULL,      -- env var name
            context_limit      INTEGER,            -- token window
            price_input        REAL NOT NULL,      -- $ per 1M input tokens
            price_output       REAL NOT NULL,
            price_cache_read   REAL NOT NULL DEFAULT 0.0,
            price_cache_write  REAL NOT NULL DEFAULT 0.0,
            active             INTEGER NOT NULL DEFAULT 1,
            UNIQUE(provider, model_id)
        )
    """)
    op.execute("CREATE INDEX ix_runtimes_provider_tier ON model_runtimes(provider, tier, active)")

    # Seed with the three Anthropic tiers already in use
    op.execute("""
        INSERT INTO model_runtimes
            (id, provider, model_id, tier, api_key_env, context_limit,
             price_input, price_output, price_cache_read, price_cache_write)
        VALUES
          ('mr_haiku',  'anthropic', 'claude-haiku-4-5-20251001', 'fast',
              'ANTHROPIC_API_KEY', 200000, 1.00,  5.00,  0.10, 1.25),
          ('mr_sonnet', 'anthropic', 'claude-sonnet-4-6',         'strong',
              'ANTHROPIC_API_KEY', 200000, 3.00,  15.00, 0.30, 3.75),
          ('mr_opus',   'anthropic', 'claude-opus-4-6',           'heavy',
              'ANTHROPIC_API_KEY', 200000, 15.00, 75.00, 1.50, 18.75)
    """)

    # Per-thread tier override — powers /model command
    op.execute("ALTER TABLE threads ADD COLUMN model_tier_override TEXT")

    # Per-job tier override (when a specific job should use a tier regardless of thread)
    op.execute("ALTER TABLE jobs ADD COLUMN model_tier_override TEXT")

    # Compaction audit trail — list of {artifact_id, replaced_count, at} per job
    op.execute("ALTER TABLE jobs ADD COLUMN compaction_log TEXT")  # JSON array


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_runtimes")
    # SQLite can't DROP COLUMN pre-3.35 without gymnastics; skip in downgrade.
    # (Our minimum SQLite is 3.45, which DOES support DROP COLUMN)
    for col, tbl in [
        ("model_tier_override", "threads"),
        ("model_tier_override", "jobs"),
        ("compaction_log", "jobs"),
    ]:
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN {col}")
