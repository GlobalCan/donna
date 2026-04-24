#!/usr/bin/env bash
# Donna backup tarball verifier — lightweight restore drill.
#
# Extracts a backup tarball to a temp dir, runs SQLite integrity checks on
# the snapshot, and verifies every artifact blob decodes to its filename
# (sha256 file naming scheme from save_artifact). Doesn't boot containers
# — this is the "is the DATA restorable" proof, not the "can a throwaway
# droplet come up" proof. The second is a quarterly task (docs/OPERATIONS.md).
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

echo
echo "=== SQLite integrity check ==="
result=$(python3 - "$db" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
try:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"integrity_check: {integrity}")
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    print(f"foreign_key_check rows: {len(fk)}")
    for name in ("jobs", "facts", "knowledge_sources", "knowledge_chunks",
                 "artifacts", "threads", "messages"):
        n = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {n} rows")
finally:
    conn.close()
PY
)
echo "$result"
if ! echo "$result" | grep -q "integrity_check: ok"; then
    echo "FAIL: integrity check did not report ok" >&2
    exit 1
fi

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
