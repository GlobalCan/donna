# Schema lifecycle policy

**Forward-only migrations. Additive over destructive. Sequential numeric revisions.**

Codex's 2026-05-01 review flagged "10 migrations in 14 days = migration discipline matters now." This document is the policy. The migration linter (`tests/test_migrations_lint.py`) enforces the structural parts.

---

## Hard rules

1. **Forward-only.** `downgrade()` raises `NotImplementedError` or is a no-op. Never write a real reverse — Donna recovers via the `legacy/<version>` git tag, not by walking migrations backwards. Reasons:
   - Reverse migrations on a populated DB are inherently dangerous (data loss, FK violations).
   - We're solo-user; the cost of "throw away the schema and revive from the legacy tag" is acceptable.
   - Forward-only forces engineers to think hard about each schema change because there's no escape hatch.

2. **Sequential numeric revision IDs.** `0001`, `0002`, ..., `0011`, `0012`. Zero-padded to 4 digits. The padding lets us string-compare (`version >= "0008"`) without numeric parsing, which is how the backup verifier checks compatibility.

3. **Every migration has a docstring.** Lead with the WHY: operational incident, feature, or refactor. Include date, link to the issue/CHANGELOG entry. The docstring is what future-you reads when debugging schema drift; make it honest.

4. **Sequential `down_revision` chain.** Migration `NNNN` has `down_revision = "MMMM"` where `MMMM = NNNN - 1`. The first migration (`0001`) has `down_revision = None`. The linter enforces this — branches are not allowed.

---

## Strong preferences (lint warns, not errors)

5. **Additive over destructive.** Prefer `ADD COLUMN`, `CREATE INDEX`, `CREATE TABLE`. Avoid `DROP COLUMN`, `DROP TABLE`, `RENAME`. When you do destruct (e.g. v0.5.0 migration 0008 dropped Discord-bound rows), the migration must explain *what data is preserved* and *what the recovery story is*.

6. **No data deletion without a comment block.** Migrations that wipe data (`DELETE FROM ...`) must have a **WIPED:** section listing every table affected and a **PRESERVED:** section listing what's kept. Migration 0008 (Slack retool) is the canonical example.

7. **Don't backfill via SQL in the migration.** If a new column needs values from existing rows, write the migration with `DEFAULT NULL` (or a benign default), and have the application code populate over time. Migration backfills can lock the DB for an unbounded window on large tables.

8. **Separate schema changes from semantic changes.** A migration adds a column; the application starts using it in a separate commit. The schema can be ahead of the code by one release without breaking — the reverse is what causes the v0.5.2 deploy race we hit on 2026-05-01.

---

## SQLite-specific gotchas

9. **`ALTER TABLE` is limited.** SQLite supports:
   - `ADD COLUMN`
   - `RENAME COLUMN` (3.25+)
   - `RENAME TABLE` (3.25+)
   - `DROP COLUMN` (3.35+, which we have)
   
   It does NOT support `ALTER COLUMN <type>` or `ALTER COLUMN <constraint>`. Type changes require `DROP TABLE` + `CREATE TABLE` (with data copy if non-empty). Migration 0008 used DROP+CREATE on `outbox_asks` and `pending_consents` to change INTEGER→TEXT.

10. **DDL is auto-committed.** Each `op.execute("CREATE TABLE ...")` commits immediately. If the migration crashes after step 1 of N, alembic_version is NOT bumped but the partial state persists. This caused the 2026-05-01 v0.5.2 deploy race (entrypoint ran alembic in both bot AND worker simultaneously). Mitigation in v0.6 #1: only bot runs alembic; worker waits via depends_on healthcheck.

11. **`PRAGMA foreign_keys` is ON in our connect().** This means delete order matters when purging or wiping. Children before parents. Retention policy (v0.6 #5) honors this; migration data wipes (e.g. 0008) should too.

12. **WAL + busy_timeout = 5000ms.** Concurrent writers wait up to 5s for the lock. Long migrations on a populated DB can starve readers. Keep individual statements bounded; if you need to backfill, do it from application code with batched commits.

---

## Per-release migration count budget

There's no hard cap, but:

- **Healthy:** 0-2 migrations per release. Most releases shouldn't touch schema.
- **Reasonable:** 3-5 migrations during active foundation work or platform retools.
- **Code smell:** 6+ migrations in one release. Reconsider — likely the design is churning.

The 2026-04-30 → 2026-05-01 span shipped migrations 0006 → 0011 (six migrations across v0.4.3 → v0.6). That was foundation work + Slack retool + V50-1 fix. Not normal cadence.

---

## What happens if the linter fails

- **Branch CI fails.** The linter runs in `tests/test_migrations_lint.py` as part of the regular pytest suite. A new migration that violates the policy fails before merge.

- **Operator inspects the failure message.** Each linter assertion explains what went wrong and how to fix.

- **The fix is to amend the migration**, not bypass the linter. If the policy is wrong for a specific case, update *this document* + the linter together, not just the linter.

---

## What the linter checks (`tests/test_migrations_lint.py`)

- Each migration file has `revision`, `down_revision`, `branch_labels`, `depends_on` module attributes.
- `revision` is a 4-char zero-padded numeric (`0001` ... `9999`).
- `down_revision` is `None` for 0001, otherwise points to the immediately preceding revision (no branches).
- Module docstring is non-empty.
- `upgrade()` and `downgrade()` exist.
- `downgrade()` either raises `NotImplementedError` (forward-only by declaration) or is a clean reverse (we do not police what "clean reverse" means; the lint is structural).

---

## When the policy needs to change

Update this document. Update the linter. Land them in the same PR. Reference both in the CHANGELOG entry. The policy is meant to evolve as the project's needs change — the only thing that's not allowed is silent drift.
