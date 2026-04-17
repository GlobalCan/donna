"""initial schema — full v1

Revision ID: 0001
Revises:
Create Date: 2026-04-17

Full v1 schema in one migration. Future migrations are additive.
Tables: threads, messages, jobs, tool_calls, traces, facts, artifacts,
permission_grants, schedules, knowledge_sources, knowledge_chunks,
agent_heuristics, agent_examples, agent_prompts, cost_ledger.
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Core conversational tables ------------------------------------------------
    op.execute("""
        CREATE TABLE threads (
            id               TEXT PRIMARY KEY,
            discord_channel  TEXT,
            discord_thread   TEXT,
            title            TEXT,
            created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_active_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE messages (
            id            TEXT PRIMARY KEY,
            thread_id     TEXT NOT NULL REFERENCES threads(id),
            role          TEXT NOT NULL,                  -- user | assistant | system
            content       TEXT NOT NULL,
            discord_msg   TEXT,
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_messages_thread ON messages(thread_id, created_at)")

    # Jobs with lease-and-recovery semantics -----------------------------------
    op.execute("""
        CREATE TABLE jobs (
            id                  TEXT PRIMARY KEY,
            thread_id           TEXT REFERENCES threads(id),
            agent_scope         TEXT NOT NULL DEFAULT 'orchestrator',
            task                TEXT NOT NULL,
            mode                TEXT NOT NULL DEFAULT 'chat',   -- chat | grounded | speculative | debate
            status              TEXT NOT NULL DEFAULT 'queued', -- queued | running | paused_awaiting_consent | done | failed | cancelled
            priority            INTEGER NOT NULL DEFAULT 5,
            owner               TEXT,                           -- worker id
            lease_until         TIMESTAMP,
            heartbeat_at        TIMESTAMP,
            checkpoint_state    TEXT,                           -- JSON
            tainted             INTEGER NOT NULL DEFAULT 0,
            taint_source_tool   TEXT,
            cost_usd            REAL NOT NULL DEFAULT 0.0,
            tool_call_count     INTEGER NOT NULL DEFAULT 0,
            created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at          TIMESTAMP,
            finished_at         TIMESTAMP,
            error               TEXT
        )
    """)
    op.execute("CREATE INDEX ix_jobs_status_priority ON jobs(status, priority, created_at)")
    op.execute("CREATE INDEX ix_jobs_thread ON jobs(thread_id)")
    op.execute("CREATE INDEX ix_jobs_owner_lease ON jobs(owner, lease_until)")

    op.execute("""
        CREATE TABLE tool_calls (
            id           TEXT PRIMARY KEY,
            job_id       TEXT NOT NULL REFERENCES jobs(id),
            tool_name    TEXT NOT NULL,
            arguments    TEXT NOT NULL,                    -- JSON
            result       TEXT,                             -- JSON or excerpt
            result_artifact_id TEXT,                       -- full result stored here if large
            started_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at  TIMESTAMP,
            duration_ms  INTEGER,
            cost_usd     REAL NOT NULL DEFAULT 0.0,
            idempotent   INTEGER NOT NULL DEFAULT 1,
            tainted      INTEGER NOT NULL DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'done',     -- done | error | denied
            error        TEXT
        )
    """)
    op.execute("CREATE INDEX ix_tool_calls_job ON tool_calls(job_id, started_at)")
    op.execute("CREATE INDEX ix_tool_calls_name ON tool_calls(tool_name)")

    op.execute("""
        CREATE TABLE traces (
            id           TEXT PRIMARY KEY,
            job_id       TEXT REFERENCES jobs(id),
            span_name    TEXT NOT NULL,
            parent_span  TEXT,
            attributes   TEXT,                              -- JSON
            started_at   TIMESTAMP NOT NULL,
            duration_ms  INTEGER,
            tainted      INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX ix_traces_job ON traces(job_id, started_at)")

    # Facts (long-term memory, scoped) -----------------------------------------
    op.execute("""
        CREATE TABLE facts (
            id                 TEXT PRIMARY KEY,
            agent_scope        TEXT,                         -- NULL = shared
            fact               TEXT NOT NULL,
            tags               TEXT,                         -- comma-separated
            embedding          BLOB,                         -- voyage-3, 1024d, optional
            written_by_tool    TEXT,
            written_by_job     TEXT REFERENCES jobs(id),
            tainted            INTEGER NOT NULL DEFAULT 0,
            created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_used_at       TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_facts_scope ON facts(agent_scope)")
    op.execute("""
        CREATE VIRTUAL TABLE facts_fts USING fts5(
            fact, tags,
            content='facts', content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)
    # keep FTS in sync via triggers
    op.execute("""
        CREATE TRIGGER facts_ai AFTER INSERT ON facts BEGIN
          INSERT INTO facts_fts(rowid, fact, tags) VALUES (new.rowid, new.fact, new.tags);
        END
    """)
    op.execute("""
        CREATE TRIGGER facts_ad AFTER DELETE ON facts BEGIN
          INSERT INTO facts_fts(facts_fts, rowid, fact, tags) VALUES('delete', old.rowid, old.fact, old.tags);
        END
    """)
    op.execute("""
        CREATE TRIGGER facts_au AFTER UPDATE ON facts BEGIN
          INSERT INTO facts_fts(facts_fts, rowid, fact, tags) VALUES('delete', old.rowid, old.fact, old.tags);
          INSERT INTO facts_fts(rowid, fact, tags) VALUES (new.rowid, new.fact, new.tags);
        END
    """)

    # Artifacts ----------------------------------------------------------------
    op.execute("""
        CREATE TABLE artifacts (
            id            TEXT PRIMARY KEY,
            sha256        TEXT NOT NULL UNIQUE,
            name          TEXT,
            mime          TEXT,
            bytes         INTEGER NOT NULL,
            tags          TEXT,
            tainted       INTEGER NOT NULL DEFAULT 0,
            created_by_job TEXT REFERENCES jobs(id),
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_artifacts_sha ON artifacts(sha256)")

    # Permission grants --------------------------------------------------------
    op.execute("""
        CREATE TABLE permission_grants (
            id            TEXT PRIMARY KEY,
            job_id        TEXT REFERENCES jobs(id),
            tool_name     TEXT NOT NULL,
            scope         TEXT NOT NULL DEFAULT 'job',     -- job | global
            granted_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at    TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_grants_job_tool ON permission_grants(job_id, tool_name)")

    # Schedules (cron triggers, v1) -------------------------------------------
    op.execute("""
        CREATE TABLE schedules (
            id            TEXT PRIMARY KEY,
            agent_scope   TEXT NOT NULL DEFAULT 'orchestrator',
            cron_expr     TEXT NOT NULL,
            task          TEXT NOT NULL,                   -- the prompt to run
            mode          TEXT NOT NULL DEFAULT 'chat',
            enabled       INTEGER NOT NULL DEFAULT 1,
            last_run_at   TIMESTAMP,
            next_run_at   TIMESTAMP,
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_schedules_next ON schedules(enabled, next_run_at)")

    # Agent-scoped knowledge substrate ----------------------------------------
    op.execute("""
        CREATE TABLE knowledge_sources (
            id                TEXT PRIMARY KEY,
            agent_scope       TEXT NOT NULL,
            source_type       TEXT NOT NULL,              -- book|article|interview|podcast|tweet|transcript|other
            work_id           TEXT,
            title             TEXT NOT NULL,
            publication_date  TEXT,                       -- ISO date
            author_period     TEXT,                       -- early|mid|late (optional)
            source_ref        TEXT,                       -- URL / artifact_id / ISBN
            copyright_status  TEXT NOT NULL,              -- public_domain|personal_use|licensed|public_web
            added_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            added_by          TEXT NOT NULL,
            tainted           INTEGER NOT NULL DEFAULT 0,
            chunk_count       INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX ix_knowledge_sources_scope ON knowledge_sources(agent_scope)")

    op.execute("""
        CREATE TABLE knowledge_chunks (
            id               TEXT PRIMARY KEY,
            source_id        TEXT NOT NULL REFERENCES knowledge_sources(id),
            agent_scope      TEXT NOT NULL,
            work_id          TEXT,
            publication_date TEXT,
            source_type      TEXT NOT NULL,
            content          TEXT NOT NULL,
            embedding        BLOB,                         -- voyage-3 1024d
            chunk_index      INTEGER NOT NULL,
            token_count      INTEGER,
            fingerprint      TEXT NOT NULL,
            is_style_anchor  INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX ix_chunks_scope_work ON knowledge_chunks(agent_scope, work_id)")
    op.execute("CREATE INDEX ix_chunks_scope_date ON knowledge_chunks(agent_scope, publication_date)")
    op.execute("CREATE INDEX ix_chunks_fingerprint ON knowledge_chunks(fingerprint)")

    # FTS index on chunks for hybrid retrieval
    op.execute("""
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            content,
            content='knowledge_chunks', content_rowid='rowid',
            tokenize='porter unicode61'
        )
    """)
    op.execute("""
        CREATE TRIGGER chunks_ai AFTER INSERT ON knowledge_chunks BEGIN
          INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
        END
    """)
    op.execute("""
        CREATE TRIGGER chunks_ad AFTER DELETE ON knowledge_chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
        END
    """)

    op.execute("""
        CREATE TABLE agent_heuristics (
            id           TEXT PRIMARY KEY,
            agent_scope  TEXT NOT NULL,
            heuristic    TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'proposed',   -- proposed|active|retired
            approved_at  TIMESTAMP,
            provenance   TEXT,
            created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_heuristics_scope_status ON agent_heuristics(agent_scope, status)")

    op.execute("""
        CREATE TABLE agent_examples (
            id                TEXT PRIMARY KEY,
            agent_scope       TEXT NOT NULL,
            task_description  TEXT NOT NULL,
            good_response     TEXT NOT NULL,
            embedding         BLOB,
            tags              TEXT,
            added_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_examples_scope ON agent_examples(agent_scope)")

    op.execute("""
        CREATE TABLE agent_prompts (
            id              TEXT PRIMARY KEY,
            agent_scope     TEXT NOT NULL,
            version         INTEGER NOT NULL,
            system_prompt   TEXT NOT NULL,
            speculation_allowed INTEGER NOT NULL DEFAULT 0,
            active          INTEGER NOT NULL DEFAULT 0,
            eval_passed_at  TIMESTAMP,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(agent_scope, version)
        )
    """)
    op.execute("CREATE INDEX ix_prompts_scope_active ON agent_prompts(agent_scope, active)")

    # Cost ledger --------------------------------------------------------------
    op.execute("""
        CREATE TABLE cost_ledger (
            id         TEXT PRIMARY KEY,
            job_id     TEXT REFERENCES jobs(id),
            model      TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cache_write_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd   REAL NOT NULL DEFAULT 0.0,
            kind       TEXT NOT NULL DEFAULT 'llm',        -- llm | embed | tavily
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX ix_cost_time ON cost_ledger(created_at)")

    # Seed: orchestrator scope's default prompt (v1) ---------------------------
    op.execute("""
        INSERT INTO agent_prompts (id, agent_scope, version, system_prompt, speculation_allowed, active, created_at)
        VALUES (
            'prompt_orchestrator_v1',
            'orchestrator',
            1,
            '[placeholder — loaded from src/donna/agent/prompts/orchestrator.md at runtime]',
            0,
            1,
            CURRENT_TIMESTAMP
        )
    """)


def downgrade() -> None:
    # drop in reverse dependency order
    for tbl in (
        "cost_ledger",
        "agent_prompts",
        "agent_examples",
        "agent_heuristics",
        "chunks_fts",
        "knowledge_chunks",
        "knowledge_sources",
        "schedules",
        "permission_grants",
        "artifacts",
        "facts_fts",
        "facts",
        "traces",
        "tool_calls",
        "jobs",
        "messages",
        "threads",
    ):
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
