"""chunks_fts: add missing UPDATE trigger

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-17

Codex adversarial review flagged: chunks_ai (INSERT) and chunks_ad (DELETE)
triggers exist, but chunks_au (UPDATE) does not — mirroring facts_au which
IS present. If `knowledge_chunks.content` is ever updated in place (e.g.
re-embedding, content correction), the FTS index goes stale silently.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TRIGGER chunks_au AFTER UPDATE ON knowledge_chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
          INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
        END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS chunks_au")
