#!/usr/bin/env bash
# Donna backup tarball verifier — lightweight restore drill.
#
# Extracts a backup tarball to a temp dir, runs:
#   - SQLite integrity_check + foreign_key_check
#   - Alembic version check (must be >= the current Slack-shaped head)
#   - Schema column-type check for migration 0008 changes
#     (Slack `ts` strings can't deserialize cleanly from INTEGER columns;
#     V50-1 follow-up after 2026-05-01 review caught this gap)
#   - Schema check for migration 0009 dead-letter additions
#   - Slack ts string shape check on a sample of rows
#   - Row counts on core tables
#   - SHA-256 verify of every artifact blob
#
# Doesn't boot containers — this is the "is the DATA restorable" proof,
# not the "can a throwaway droplet come up" proof. The second is a
# quarterly task (docs/OPERATIONS.md).
#
# Usage:
#   scripts/donna-verify-backup.sh /path/to/donna-YYYYMMDD-HHMMSS.tar.gz
#
# Runs happily on the droplet against /home/bot/backups/donna-latest.tar.gz.
set -euo pipefail

TARBALL="${1:-/home/bot/backups/donna-latest.tar.gz}"
if [ ! -f "$TARBALL" ] && [ ! -L "$TARBALL" ]; then
    echo "tarball not found: $TARBALL" >&2
    exit 2
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

echo "=== extracting $TARBALL ==="
tar -xzf "$TARBALL" -C "$work"

db="$work/donna.db"
artifacts="$work/artifacts"

if [ ! -f "$db" ]; then
    echo "FAIL: donna.db missing from tarball" >&2
    exit 1
fi

# Lowest schema version that produces a backup compatible with the
# current Slack-shaped binary. Backups from before this revision were
# Discord-shaped and aren't restorable for the v0.5.0+ deployment.
MIN_SCHEMA_VERSION="0008"

echo
echo "=== schema + integrity check ==="
result=$(MIN_SCHEMA_VERSION="$MIN_SCHEMA_VERSION" python3 - "$db" <<'PY'
import os
import re
import sqlite3
import sys

db_path = sys.argv[1]
min_version = os.environ["MIN_SCHEMA_VERSION"]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
errors: list[str] = []
try:
    # 1. integrity + FK -----------------------------------------------------
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"integrity_check: {integrity}")
    if integrity != "ok":
        errors.append(f"integrity_check returned {integrity!r}")
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    print(f"foreign_key_check rows: {len(fk)}")
    if fk:
        errors.append(f"{len(fk)} foreign key violations")

    # 2. alembic version ----------------------------------------------------
    try:
        version = conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        version = None
    print(f"alembic_version: {version!r}")
    if version is None:
        errors.append("alembic_version table missing or empty")
    elif version < min_version:
        # String compare works for our zero-padded numeric revision ids
        # (0001..0009). Any future format change must keep this property.
        errors.append(
            f"backup is at alembic revision {version}; "
            f"minimum compatible with current Slack-shaped binary is "
            f"{min_version}. Restore will fail with missing-column errors."
        )

    # 3. Slack-shaped column types (migration 0008) ------------------------
    # Codex review 2026-05-01: backup verifier was blind to migration
    # 0008's INTEGER->TEXT changes. A successful integrity_check on a
    # pre-0008 backup would have produced a "passing" backup that
    # silently broke posted_message_id deserialization on restore.
    expected_text_cols = {
        "threads": ("channel_id", "thread_external_id"),
        "messages": ("external_msg_id",),
        "outbox_asks": ("posted_channel_id", "posted_message_id"),
        "pending_consents": ("posted_channel_id", "posted_message_id"),
        "schedules": ("target_channel_id", "target_thread_ts"),
    }
    for table, columns in expected_text_cols.items():
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        col_types = {r["name"]: r["type"].upper() for r in info}
        for col in columns:
            if col not in col_types:
                errors.append(
                    f"{table}.{col} missing — backup predates migration 0008"
                )
                continue
            t = col_types[col]
            # SQLite stores type affinity as the declared type; TEXT
            # normalizes to TEXT. Old INTEGER columns from pre-0008
            # would still be INTEGER here.
            if "TEXT" not in t:
                errors.append(
                    f"{table}.{col} type is {t!r}; expected TEXT "
                    f"(Slack ts is a string; INTEGER will lose decimal precision)"
                )

    # 4. V50-1 dead-letter additions (migration 0009) ----------------------
    tables = {
        r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if version is not None and version >= "0009":
        if "outbox_dead_letter" not in tables:
            errors.append(
                "outbox_dead_letter table missing despite "
                f"alembic_version={version}"
            )
        ou_cols = {
            r["name"] for r in conn.execute(
                "PRAGMA table_info(outbox_updates)"
            ).fetchall()
        }
        for col in ("attempt_count", "last_error", "last_attempt_at"):
            if col not in ou_cols:
                errors.append(
                    f"outbox_updates.{col} missing despite alembic_version=0009"
                )

    # 5. Slack ts shape check ---------------------------------------------
    # Sample posted_message_id values; if the backup was taken pre-0008
    # but the alembic version is somehow correct, the data shape itself
    # would tell us. Empty-table is acceptable (operational state often
    # is empty).
    ts_re = re.compile(r"^\d{10}\.\d{6}$")
    for table, col in (
        ("outbox_asks", "posted_message_id"),
        ("pending_consents", "posted_message_id"),
    ):
        try:
            rows = conn.execute(
                f"SELECT {col} FROM {table} "
                f"WHERE {col} IS NOT NULL LIMIT 5"
            ).fetchall()
        except sqlite3.OperationalError:
            continue  # column missing already reported above
        for r in rows:
            value = r[col]
            if not isinstance(value, str) or not ts_re.match(value):
                errors.append(
                    f"{table}.{col}={value!r} doesn't look like a Slack ts "
                    f"(expected '1234567890.123456' format)"
                )
                break

    # 6. Core row counts (operator situational awareness) -----------------
    for name in ("jobs", "facts", "knowledge_sources", "knowledge_chunks",
                 "artifacts", "threads", "messages",
                 "outbox_updates", "outbox_dead_letter"):
        if name not in tables:
            continue
        n = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {n} rows")
finally:
    conn.close()

if errors:
    print()
    print("SCHEMA CHECK FAILURES:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
PY
)
echo "$result"

echo
echo "=== artifact blob sha256 verification ==="
if [ ! -d "$artifacts" ]; then
    echo "no artifacts dir in tarball (empty corpus?) — skipping"
else
    bad=0
    total=0
    for blob in "$artifacts"/*.blob; do
        [ -e "$blob" ] || continue
        total=$((total + 1))
        expected=$(basename "$blob" .blob)
        actual=$(sha256sum "$blob" | awk '{print $1}')
        if [ "$expected" != "$actual" ]; then
            echo "  CORRUPT: $expected (got $actual)" >&2
            bad=$((bad + 1))
        fi
    done
    echo "  verified $total blobs ($bad corrupt)"
    if [ "$bad" -gt 0 ]; then
        echo "FAIL: $bad artifact blob(s) have mismatched sha256" >&2
        exit 1
    fi
fi

echo
echo "=== OK — tarball is valid and restorable ==="
