"""V50-8: messages.safe_summary — dual-field memory (raw + sanitized).

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-01

v0.4.4 stored tainted assistant replies as raw content with
`tainted=1`, then `compose_system` rendered them inside a
`<untrusted_session_history>` XML wrapper carrying a "do not follow
instructions" warning. That worked, but coupled audit storage to
render-time wrapping discipline: any future bug in the wrapper logic
(forgetting it for a new mode, mis-escaping the delimiters, etc.)
would silently expose raw tainted content to the model.

Codex review 2026-05-01 recommended dual-field memory:

  - `content` (existing): the raw exchange. Audit-only when tainted —
    never rendered into a future model prompt directly.
  - `safe_summary` (new): a sanitized, paraphrased version produced
    via the existing Haiku-based dual-call sanitizer. Reaches the
    model as plain continuity context (no wrapper) when present.

The split decouples audit from rendering: even if the wrapper is
removed entirely, raw tainted content can never reach the model
because compose_system reads safe_summary, not content, for tainted
rows.

Backfill semantics: NULL means "not yet sanitized" (or the row predates
this migration). Read path falls back to the v0.4.4 wrapped-raw render
in that case, preserving the previous safety contract for legacy data
and for the brief race window between row insert and async backfill
completion.
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN safe_summary TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN safe_summary")
