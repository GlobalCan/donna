#!/usr/bin/env bash
# scripts/donna-restore-drill.sh
#
# Donna restore drill — Phase 0 gate per docs/PATH_3_INVARIANTS.md §17 / §21.
#
# Provisions a throwaway DigitalOcean droplet, restores Donna from a
# backup tarball, runs smoke checks + the full pytest suite against
# the restored DB, then tears the droplet down.
#
# WHAT THIS PROVES (when it passes)
#   - Backup tarballs are recoverable end-to-end.
#   - alembic_version on restored DB matches expected.
#   - Schema integrity preserved (foreign_key_check + integrity_check).
#   - Core tables + artifact blobs survive the round-trip.
#   - All 639 tests pass against restored data.
#   - Operator's muscle memory on disaster recovery is exercised.
#
# WHAT THIS DOES NOT PROVE
#   - Live bot startup / Slack connectivity. The drill deliberately
#     does NOT put Slack credentials on the throwaway droplet — that
#     would be a credential-on-disposable-host risk for no gain. The
#     drill validates DATA recoverability + the test suite; live-bot
#     startup is a separate concern.
#   - Slack-side credential rotation (use TOKEN_ROTATION runbook for that).
#   - Multi-day operational soak (this is point-in-time validation).
#   - Off-droplet backup discipline (test the backup PIPELINE separately).
#
# COST
#   ~$0.01 for the droplet (DO charges hourly; a 30-min run is roughly
#   one cent). Approved by operator at $0.20 budget — anything close to
#   that is a red flag (probably the script hung).
#
# Usage:
#   bash scripts/donna-restore-drill.sh
#
# Required environment:
#   DRILL_DO_TOKEN         DigitalOcean API token
#                          (https://cloud.digitalocean.com/account/api)
#
# Optional environment (sane defaults shown):
#   DRILL_BACKUP_FILE      path to a backup tarball
#                          default: latest in ~/OneDrive/Donna-Backups/
#   DRILL_SSH_KEY_PATH     SSH private key for droplet access
#                          default: ~/.ssh/donna-drill-key
#   DRILL_DO_SSH_KEY_NAME  name of an SSH key REGISTERED in DigitalOcean
#                          (must already exist; doctl sees it). REQUIRED
#                          if DRILL_SSH_KEY_PATH points to a non-default
#                          location.
#   DRILL_REGION           DO region. default "nyc1"
#   DRILL_SIZE             DO size slug. default "s-1vcpu-1gb"
#   DRILL_IMAGE            DO base image. default "ubuntu-24-04-x64"
#   DRILL_KEEP_ON_FAIL     "true" / "false". default "true" — keep
#                          droplet on failure so operator can inspect.
#                          Set to "false" for unattended runs.
#   DRILL_LOG_DIR          where logs go. default /tmp/donna-drill-<ts>
#   DRILL_EXPECTED_VERSION expected alembic_version. default "0014"
#                          (current head; bump when migrations advance)
#
# Exit codes:
#   0   full pass
#   10  prerequisites failed
#   20  droplet provisioning failed
#   30  bootstrap failed
#   40  restore failed
#   50  smoke checks failed
#   60  test suite failed
#   90  unexpected failure
#
# Re-running:
#   The drill name uses a timestamp suffix so consecutive runs don't
#   collide. Stale droplets from prior failed runs need manual cleanup
#   via DO console (look for `donna-drill-*`).

set -euo pipefail

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

readonly TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
readonly DRILL_NAME="donna-drill-${TIMESTAMP}-$$"
readonly LOG_DIR="${DRILL_LOG_DIR:-/tmp/donna-drill-${TIMESTAMP}}"
mkdir -p "$LOG_DIR"

# Defaults
readonly REGION="${DRILL_REGION:-nyc1}"
readonly SIZE="${DRILL_SIZE:-s-1vcpu-1gb}"
readonly IMAGE="${DRILL_IMAGE:-ubuntu-24-04-x64}"
readonly KEEP_ON_FAIL="${DRILL_KEEP_ON_FAIL:-true}"
readonly EXPECTED_VERSION="${DRILL_EXPECTED_VERSION:-0014}"
readonly SSH_KEY_PATH="${DRILL_SSH_KEY_PATH:-$HOME/.ssh/donna-drill-key}"

# State
DROPLET_ID=""
DROPLET_IP=""
PHASE_FAILED=""
START_EPOCH=$(date +%s)

# Logging
log() {
    local msg="$*"
    printf "[%s] %s\n" "$(date -u +%H:%M:%S)" "$msg" | tee -a "$LOG_DIR/drill.log"
}

phase() {
    local name="$1"
    log ""
    log "==============================================================="
    log "  PHASE: $name"
    log "==============================================================="
}

err() {
    local msg="$*"
    printf "[%s] ERROR: %s\n" "$(date -u +%H:%M:%S)" "$msg" | tee -a "$LOG_DIR/drill.log" >&2
}

# Cleanup runs on every exit path — success, failure, or interrupt.
cleanup() {
    local exit_code=$?
    local elapsed=$(( $(date +%s) - START_EPOCH ))

    log ""
    log "==============================================================="
    log "  CLEANUP"
    log "==============================================================="
    log "Elapsed: ${elapsed}s"
    log "Logs:    $LOG_DIR"

    if [[ -n "$DROPLET_ID" ]]; then
        if [[ "$exit_code" -eq 0 ]]; then
            log "Pass — destroying droplet $DROPLET_ID"
            destroy_droplet
        elif [[ "$KEEP_ON_FAIL" == "true" ]]; then
            log "Fail — KEEP_ON_FAIL=true; leaving droplet $DROPLET_ID"
            log "  IP:      $DROPLET_IP"
            log "  SSH:     ssh -i $SSH_KEY_PATH root@$DROPLET_IP"
            log "  Destroy: doctl compute droplet delete $DROPLET_ID --force"
        else
            log "Fail — KEEP_ON_FAIL=false; destroying droplet $DROPLET_ID"
            destroy_droplet
        fi
    fi

    log ""
    if [[ "$exit_code" -eq 0 ]]; then
        log "RESULT: PASS"
    else
        log "RESULT: FAIL (exit $exit_code, phase: ${PHASE_FAILED:-unknown})"
    fi
}
trap cleanup EXIT

destroy_droplet() {
    if [[ -n "$DROPLET_ID" ]]; then
        if doctl compute droplet delete "$DROPLET_ID" --force 2>>"$LOG_DIR/cleanup.log"; then
            log "Droplet $DROPLET_ID destroyed."
            DROPLET_ID=""
        else
            err "Could not destroy droplet $DROPLET_ID via doctl. Manual cleanup required."
        fi
    fi
}

# -----------------------------------------------------------------------------
# Phase 1 — prerequisites
# -----------------------------------------------------------------------------

phase "PREREQUISITES"
PHASE_FAILED="prerequisites"

# DO token
if [[ -z "${DRILL_DO_TOKEN:-}" ]]; then
    err "DRILL_DO_TOKEN env var is required. Get one at:"
    err "  https://cloud.digitalocean.com/account/api"
    exit 10
fi
export DIGITALOCEAN_ACCESS_TOKEN="$DRILL_DO_TOKEN"

# doctl present
if ! command -v doctl >/dev/null 2>&1; then
    err "doctl CLI not found. Install:"
    err "  https://docs.digitalocean.com/reference/doctl/how-to/install/"
    exit 10
fi
log "doctl version: $(doctl version | head -1)"

# Auth check
if ! doctl auth list >/dev/null 2>&1; then
    err "doctl auth failed. Run: doctl auth init"
    exit 10
fi

# SSH key file present
if [[ ! -f "$SSH_KEY_PATH" ]]; then
    err "SSH private key not found at $SSH_KEY_PATH"
    err "Generate one with:"
    err "  ssh-keygen -t ed25519 -f $SSH_KEY_PATH -N ''"
    err "Then upload the .pub to DO:"
    err "  doctl compute ssh-key import donna-drill --public-key-file $SSH_KEY_PATH.pub"
    exit 10
fi

# Find the matching DO-registered SSH key fingerprint
SSH_FINGERPRINT="$(ssh-keygen -l -E md5 -f "$SSH_KEY_PATH" 2>/dev/null | awk '{print $2}' | sed 's/^MD5://')"
if [[ -z "$SSH_FINGERPRINT" ]]; then
    err "Could not compute MD5 fingerprint for $SSH_KEY_PATH"
    exit 10
fi
log "SSH fingerprint: $SSH_FINGERPRINT"

if ! doctl compute ssh-key list --format ID,Name,FingerPrint --no-header 2>/dev/null \
        | grep -q "$SSH_FINGERPRINT"; then
    err "SSH key fingerprint $SSH_FINGERPRINT not registered in DO."
    err "Register it:"
    err "  doctl compute ssh-key import donna-drill --public-key-file $SSH_KEY_PATH.pub"
    exit 10
fi
log "SSH key registered in DO. Good."

# Backup file
if [[ -z "${DRILL_BACKUP_FILE:-}" ]]; then
    # Auto-detect: latest tarball in OneDrive backup folder
    BACKUP_DIR="$HOME/OneDrive/Donna-Backups"
    if [[ -d "$BACKUP_DIR" ]]; then
        DRILL_BACKUP_FILE="$(ls -t "$BACKUP_DIR"/donna-*.tar.gz 2>/dev/null | head -1)"
    fi
fi

if [[ -z "${DRILL_BACKUP_FILE:-}" || ! -f "$DRILL_BACKUP_FILE" ]]; then
    err "DRILL_BACKUP_FILE is empty or missing."
    err "Set explicitly:"
    err "  export DRILL_BACKUP_FILE=/path/to/donna-YYYYMMDD-HHMMSS.tar.gz"
    err "Or place a backup in ~/OneDrive/Donna-Backups/"
    exit 10
fi
BACKUP_SIZE=$(stat -c%s "$DRILL_BACKUP_FILE" 2>/dev/null || stat -f%z "$DRILL_BACKUP_FILE")
log "Backup file: $DRILL_BACKUP_FILE (${BACKUP_SIZE} bytes)"

if [[ "$BACKUP_SIZE" -lt 1024 ]]; then
    err "Backup file is suspiciously small (<1KB). Possible truncation."
    exit 10
fi

# -----------------------------------------------------------------------------
# Phase 2 — provision droplet
# -----------------------------------------------------------------------------

phase "PROVISION DROPLET"
PHASE_FAILED="provision"

log "Region:  $REGION"
log "Size:    $SIZE"
log "Image:   $IMAGE"
log "Name:    $DRILL_NAME"

DROPLET_CREATE_OUT="$LOG_DIR/droplet-create.json"
if ! doctl compute droplet create "$DRILL_NAME" \
        --region "$REGION" \
        --size "$SIZE" \
        --image "$IMAGE" \
        --ssh-keys "$SSH_FINGERPRINT" \
        --enable-ipv6 \
        --output json \
        --wait \
        > "$DROPLET_CREATE_OUT" 2>"$LOG_DIR/droplet-create.err"; then
    err "doctl droplet create failed."
    err "stderr: $(cat "$LOG_DIR/droplet-create.err")"
    exit 20
fi

DROPLET_ID="$(grep -oE '"id":[[:space:]]*[0-9]+' "$DROPLET_CREATE_OUT" | head -1 | grep -oE '[0-9]+')"
DROPLET_IP="$(grep -oE '"ip_address":[[:space:]]*"[0-9.]+"' "$DROPLET_CREATE_OUT" | head -1 | grep -oE '[0-9.]+')"

if [[ -z "$DROPLET_ID" || -z "$DROPLET_IP" ]]; then
    err "Could not parse droplet ID / IP from response."
    err "  See $DROPLET_CREATE_OUT"
    exit 20
fi

log "Droplet ID: $DROPLET_ID"
log "Droplet IP: $DROPLET_IP"

# Wait for SSH to come up. doctl --wait returns when DO marks the droplet
# active, but cloud-init still needs to finish + sshd to bind.
log "Waiting for SSH readiness..."
SSH_READY=false
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if ssh -i "$SSH_KEY_PATH" \
           -o StrictHostKeyChecking=no \
           -o UserKnownHostsFile=/dev/null \
           -o ConnectTimeout=5 \
           "root@$DROPLET_IP" \
           "echo ssh-ready" >>"$LOG_DIR/ssh-probe.log" 2>&1; then
        SSH_READY=true
        log "SSH ready after $attempt attempt(s)."
        break
    fi
    sleep 5
done

if ! $SSH_READY; then
    err "SSH did not become ready within ~50s."
    err "  Check: $LOG_DIR/ssh-probe.log"
    exit 20
fi

# SSH wrapper for the rest of the script
ssh_drill() {
    ssh -i "$SSH_KEY_PATH" \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        "root@$DROPLET_IP" \
        "$@"
}

scp_drill() {
    scp -i "$SSH_KEY_PATH" \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        "$@"
}

# -----------------------------------------------------------------------------
# Phase 3 — bootstrap
# -----------------------------------------------------------------------------

phase "BOOTSTRAP"
PHASE_FAILED="bootstrap"

# The drill validates DATA recovery + the test suite — it does not
# start the live bot, so docker is not needed. Install only what the
# restore + alembic + pytest path actually uses. python3-venv is
# required because Ubuntu 24.04 enforces PEP 668 (externally-managed
# environment) — a bare `pip3 install` system-wide fails. Every Python
# install in this drill goes through a venv.
log "Installing dependencies (sqlite3, git, python venv tooling)..."
if ! ssh_drill "
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
        sqlite3 git python3 python3-pip python3-venv
" >"$LOG_DIR/bootstrap.log" 2>&1; then
    err "Bootstrap failed."
    err "  See $LOG_DIR/bootstrap.log"
    exit 30
fi
log "Bootstrap complete."

log "Uploading backup tarball..."
if ! scp_drill "$DRILL_BACKUP_FILE" "root@$DROPLET_IP:/tmp/backup.tar.gz" \
        >>"$LOG_DIR/bootstrap.log" 2>&1; then
    err "Failed to upload backup."
    exit 30
fi

# Verify backup arrived intact
LOCAL_SHA=$(sha256sum "$DRILL_BACKUP_FILE" 2>/dev/null | awk '{print $1}' \
            || shasum -a 256 "$DRILL_BACKUP_FILE" | awk '{print $1}')
REMOTE_SHA=$(ssh_drill "sha256sum /tmp/backup.tar.gz | awk '{print \$1}'")

if [[ "$LOCAL_SHA" != "$REMOTE_SHA" ]]; then
    err "Backup transfer integrity check failed."
    err "  Local:  $LOCAL_SHA"
    err "  Remote: $REMOTE_SHA"
    exit 30
fi
log "Backup integrity verified ($LOCAL_SHA)."

# Clone the repo at v0.7.3 — that's the exact version the backup expects.
# We don't pull random latest because schema head may have advanced beyond
# the backup's alembic_version.
log "Cloning Donna repo at v0.7.3..."
if ! ssh_drill "
    set -euo pipefail
    git clone --depth 1 --branch v0.7.3 https://github.com/GlobalCan/donna.git /opt/donna
" >>"$LOG_DIR/bootstrap.log" 2>&1; then
    err "git clone failed."
    err "  See $LOG_DIR/bootstrap.log"
    exit 30
fi
log "Repo cloned."

# -----------------------------------------------------------------------------
# Phase 4 — restore
# -----------------------------------------------------------------------------

phase "RESTORE"
PHASE_FAILED="restore"

log "Extracting backup tarball..."
if ! ssh_drill "
    set -euo pipefail
    mkdir -p /data/donna /data/donna/artifacts
    cd /tmp
    tar xzf backup.tar.gz
    # Backup format: donna.db + artifacts/
    if [[ ! -f /tmp/donna.db ]]; then
        echo 'Backup missing donna.db — wrong format?' >&2
        ls -la /tmp/ >&2
        exit 1
    fi
    cp /tmp/donna.db /data/donna/donna.db
    if [[ -d /tmp/artifacts ]]; then
        cp -r /tmp/artifacts/. /data/donna/artifacts/
    fi
    chown -R 1001:1001 /data/donna
" >"$LOG_DIR/restore.log" 2>&1; then
    err "Restore extraction failed."
    err "  See $LOG_DIR/restore.log"
    exit 40
fi
log "Backup extracted."

# Build the venv + install Donna here (not in Phase 6). This serves
# two purposes: it provides alembic for the upgrade below, and it
# front-loads the dependency install so Phase 6 just runs pytest.
# `.[dev]` already pulls alembic + sqlalchemy + everything pytest
# needs — no separate `pip install alembic sqlalchemy` required.
# Bare system `pip3 install` would fail here: Ubuntu 24.04 enforces
# PEP 668. The venv is the fix.
log "Building venv + installing Donna (provides alembic + test deps)..."
if ! ssh_drill "
    set -euo pipefail
    cd /opt/donna
    python3 -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -e '.[dev]'
" >>"$LOG_DIR/restore.log" 2>&1; then
    err "venv build / Donna install failed."
    err "  See $LOG_DIR/restore.log"
    exit 40
fi
log "venv built, Donna installed."

log "Running alembic upgrade head against restored DB..."
if ! ssh_drill "
    set -euo pipefail
    cd /opt/donna
    DONNA_DATA_DIR=/data/donna .venv/bin/python -m alembic -c alembic.ini upgrade head
" >>"$LOG_DIR/restore.log" 2>&1; then
    err "alembic upgrade head failed."
    err "  See $LOG_DIR/restore.log"
    exit 40
fi
log "alembic upgrade head succeeded."

# -----------------------------------------------------------------------------
# Phase 5 — smoke checks
# -----------------------------------------------------------------------------

phase "SMOKE CHECKS"
PHASE_FAILED="smoke"

log "Verifying alembic_version = $EXPECTED_VERSION..."
ACTUAL_VERSION=$(ssh_drill "
    sqlite3 /data/donna/donna.db 'SELECT version_num FROM alembic_version'
" 2>/dev/null | tr -d '[:space:]')

if [[ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" ]]; then
    err "alembic_version mismatch."
    err "  Expected: $EXPECTED_VERSION"
    err "  Actual:   $ACTUAL_VERSION"
    exit 50
fi
log "alembic_version = $ACTUAL_VERSION (matches expected)."

log "Running PRAGMA integrity_check..."
INTEGRITY=$(ssh_drill "sqlite3 /data/donna/donna.db 'PRAGMA integrity_check'")
if [[ "$INTEGRITY" != "ok" ]]; then
    err "integrity_check failed."
    err "  Output: $INTEGRITY"
    exit 50
fi
log "integrity_check: ok"

log "Running PRAGMA foreign_key_check..."
FK_CHECK=$(ssh_drill "sqlite3 /data/donna/donna.db 'PRAGMA foreign_key_check'")
if [[ -n "$FK_CHECK" ]]; then
    err "foreign_key_check found violations:"
    err "$FK_CHECK"
    exit 50
fi
log "foreign_key_check: clean"

log "Verifying core tables have expected shape..."
TABLE_REPORT=$(ssh_drill "
    sqlite3 /data/donna/donna.db <<'SQL'
.headers off
.mode column
SELECT 'jobs',           COUNT(*) FROM jobs;
SELECT 'threads',        COUNT(*) FROM threads;
SELECT 'messages',       COUNT(*) FROM messages;
SELECT 'schedules',      COUNT(*) FROM schedules;
SELECT 'brief_runs',     COUNT(*) FROM brief_runs;
SELECT 'consent_batches', COUNT(*) FROM consent_batches;
SELECT 'alert_digest_queue', COUNT(*) FROM alert_digest_queue;
SQL
")
log "Core table row counts:"
echo "$TABLE_REPORT" | while read -r line; do log "  $line"; done

# Verify all artifact blobs are intact (sha256 matches filename)
log "Verifying artifact blob hashes..."
ARTIFACT_VERIFY=$(ssh_drill "
    cd /data/donna/artifacts 2>/dev/null && find . -name '*.blob' -type f | head -5 | while read -r blob; do
        expected=\$(basename \"\$blob\" .blob)
        actual=\$(sha256sum \"\$blob\" | awk '{print \$1}')
        if [[ \"\$expected\" != \"\$actual\" ]]; then
            echo \"MISMATCH: \$blob (expected \$expected, got \$actual)\"
        fi
    done
")
if [[ -n "$ARTIFACT_VERIFY" ]]; then
    err "Artifact hash mismatches found:"
    err "$ARTIFACT_VERIFY"
    exit 50
fi
log "Sample artifact hashes verified."

# -----------------------------------------------------------------------------
# Phase 6 — full pytest suite
# -----------------------------------------------------------------------------

phase "FULL TEST SUITE"
PHASE_FAILED="tests"

# venv + `.[dev]` were built in Phase 4 (restore). Reuse it — no
# second install pass.
log "Running pytest -q (this takes ~6 minutes)..."
if ! ssh_drill "
    cd /opt/donna
    .venv/bin/python -m pytest -q --tb=line 2>&1
" > "$LOG_DIR/test-output.log" 2>&1; then
    err "Test suite failed."
    err "  See $LOG_DIR/test-output.log"
    err "Last 30 lines:"
    tail -30 "$LOG_DIR/test-output.log" | while read -r line; do err "  $line"; done
    exit 60
fi

PASS_LINE=$(grep -E '^[0-9]+ passed' "$LOG_DIR/test-output.log" | tail -1)
log "Tests result: $PASS_LINE"

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------

PHASE_FAILED=""
log ""
log "==============================================================="
log "  ALL PHASES PASSED"
log "==============================================================="
log "Restored backup:    $DRILL_BACKUP_FILE"
log "alembic_version:    $ACTUAL_VERSION"
log "Tests:              $PASS_LINE"
log "Logs preserved at:  $LOG_DIR"
log ""
log "Drill complete. Phase 0 gate satisfied per PATH_3_INVARIANTS §17."

# Cleanup trap will destroy the droplet on exit-0
exit 0
