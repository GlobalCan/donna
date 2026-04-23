#!/usr/bin/env bash
# Donna nightly backup — runs on the droplet as user `bot` via cron.
#
# Produces a single tarball containing:
#   - Consistent SQLite snapshot (via .backup API; safe with WAL mode and a live writer)
#   - All artifact blobs from /data/donna/artifacts/
#
# Output: $BACKUP_DIR/donna-<UTC-stamp>.tar.gz, plus a `donna-latest.tar.gz`
# symlink the laptop-side fetch script pulls. Local retention is RETAIN_DAYS.
#
# Install:
#   sudo apt-get install -y sqlite3
#   scp scripts/donna-backup.sh bot@<ip>:/home/bot/donna-backup.sh
#   ssh bot@<ip> chmod +x /home/bot/donna-backup.sh
#   ssh bot@<ip> '(crontab -l 2>/dev/null; echo "0 3 * * * /home/bot/donna-backup.sh >>/home/bot/backups/.cron.log 2>&1") | crontab -'
set -euo pipefail

DATA_DIR="${DONNA_DATA_DIR:-/data/donna}"
BACKUP_DIR="${DONNA_BACKUP_DIR:-/home/bot/backups}"
RETAIN_DAYS="${DONNA_BACKUP_RETAIN_DAYS:-7}"

stamp=$(date -u +%Y%m%d-%H%M%S)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir -p "$BACKUP_DIR"

# Consistent SQLite snapshot. .backup uses SQLite's online backup API,
# which is safe to run while the bot is actively writing via WAL.
sqlite3 "$DATA_DIR/donna.db" ".backup '$work/donna.db'"

# Stage artifacts alongside the db so the tarball has a flat layout.
mkdir -p "$work/artifacts"
if [ -d "$DATA_DIR/artifacts" ]; then
    cp -r "$DATA_DIR/artifacts/." "$work/artifacts/"
fi

out="$BACKUP_DIR/donna-$stamp.tar.gz"
tar -czf "$out" -C "$work" donna.db artifacts

ln -sfn "donna-$stamp.tar.gz" "$BACKUP_DIR/donna-latest.tar.gz"

# Retention: prune tarballs older than RETAIN_DAYS. The latest symlink is
# preserved because it's a symlink, not a regular file matched by -type f.
find "$BACKUP_DIR" -maxdepth 1 -name 'donna-*.tar.gz' -type f -mtime +"$RETAIN_DAYS" -delete

size=$(du -h "$out" | cut -f1)
echo "$(date -u -Iseconds) backup ok size=$size path=$out"
