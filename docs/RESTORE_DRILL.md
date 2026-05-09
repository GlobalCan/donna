# Restore Drill — Operator Runbook

**Status:** Phase 0 gate per `docs/PATH_3_INVARIANTS.md` §17 / §21.
**Owner:** operator (must execute personally; this is muscle memory).
**Cadence:** quarterly minimum, plus after any platform change that
touches schema or backup format.

---

## Why this exists

`PATH_3_INVARIANTS.md §21` makes restore-drill execution the **gate
for Phase 1 spine work on P920**. Three reasons it's a gate:

1. **The drill validates the backup pipeline end-to-end.** Tarballs
   that fail integrity verification are useless. `donna-verify-backup.sh`
   covers the data-layer; the drill covers "deploy comes up against
   restored data."
2. **It builds operator muscle memory.** Disaster recovery under
   stress, with hours of downtime ticking, is the wrong moment to be
   reading documentation. The drill rehearses the procedure when
   stakes are zero.
3. **My data is the only AI-system data the operator currently has.**
   If the droplet dies during Phase 1, recovering Donna v0.7.3 is the
   fallback. Recovery procedure must be proven before it's needed.

The drill's discipline also feeds Phase 1: every system on P920 ships
with a tested restore drill before going to production. Practice on
Donna first.

---

## What the drill does

`scripts/donna-restore-drill.sh` performs six phases:

| Phase | What | Exit code on failure |
|------:|------|---------------------:|
| 1 | Prerequisites — doctl, SSH key, backup file | 10 |
| 2 | Provision throwaway droplet (~30s) | 20 |
| 3 | Bootstrap (docker, repo clone, backup transfer + sha256 verify) | 30 |
| 4 | Restore (extract tarball, alembic upgrade head) | 40 |
| 5 | Smoke checks (alembic_version, integrity_check, foreign_key_check, artifact hashes) | 50 |
| 6 | Full pytest suite against restored DB (expect 639 passed) | 60 |

On success: droplet is destroyed automatically. On failure:
`DRILL_KEEP_ON_FAIL=true` (default) leaves it standing so you can SSH
in and inspect, with the destroy command printed in the summary.

**Total runtime:** ~10 minutes for phases 1-5, ~6 minutes for the
test suite. Plan for 20 minutes including investigation if anything
goes wrong.

**Cost:** about $0.01 for the droplet (DO charges hourly; one-cent
slot for a 30-min run). Operator approved a $0.20 budget — anything
near that means the script hung.

---

## One-time setup

### 1. DigitalOcean account + API token

If you don't already have a personal DO account, create one. Generate
a personal access token at:

```
https://cloud.digitalocean.com/account/api/tokens
```

- **Name:** `donna-drill`
- **Scopes:** read + write (`droplet:create`, `droplet:delete`,
  `ssh_key:read` are the strict minimum).
- **Expiry:** 90 days (quarterly cadence; rotate on each drill).

Save the token in your secrets manager. Don't commit it; don't paste
it in chat.

### 2. doctl CLI

Install:

```bash
# macOS
brew install doctl

# Linux / WSL2
sudo snap install doctl

# Windows
# Download from https://github.com/digitalocean/doctl/releases
# Extract to a folder on PATH (e.g., %USERPROFILE%\bin)
```

Auth:

```bash
doctl auth init
# paste DO token when prompted
doctl auth list
# should show 'default' as current
```

### 3. SSH key for drill droplets

Generate a dedicated key (don't reuse your production droplet key):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/donna-drill-key -N ''
```

Register it with DO:

```bash
doctl compute ssh-key import donna-drill --public-key-file ~/.ssh/donna-drill-key.pub
doctl compute ssh-key list
# should show 'donna-drill' with a fingerprint
```

### 4. Backup file accessible

The script auto-detects the latest tarball in
`~/OneDrive/Donna-Backups/` (Layer 3 of Donna's three-layer backup
strategy). If your tarballs live elsewhere:

```bash
export DRILL_BACKUP_FILE=/path/to/donna-YYYYMMDD-HHMMSS.tar.gz
```

The drill does NOT pull from the production droplet — that would
miss the point. It uses a tarball you already have on your laptop.

---

## Running the drill

```bash
cd C:/dev/donna   # or wherever your repo is
export DRILL_DO_TOKEN='dop_v1_...'    # from step 1 above
bash scripts/donna-restore-drill.sh
```

Optional environment overrides:

```bash
export DRILL_BACKUP_FILE='/path/to/specific/backup.tar.gz'   # default: latest in OneDrive
export DRILL_KEEP_ON_FAIL='false'                            # default: true (keep on failure)
export DRILL_REGION='nyc1'                                   # default: nyc1
export DRILL_SIZE='s-1vcpu-1gb'                              # default: cheapest valid
export DRILL_EXPECTED_VERSION='0014'                         # default: current head
```

Console output is tee'd to `/tmp/donna-drill-<timestamp>/drill.log`
plus per-phase logs (`bootstrap.log`, `restore.log`,
`test-output.log`, etc.). Logs are preserved across runs so you can
diff sequential drills.

---

## What "passing" looks like

Last lines of console output should read:

```
==============================================================
  ALL PHASES PASSED
==============================================================
Restored backup:    /home/.../donna-20260509-030000.tar.gz
alembic_version:    0014
Tests:              639 passed in 388.x seconds
Logs preserved at:  /tmp/donna-drill-20260509-XXXXXX/
RESULT: PASS
```

Plus the droplet is destroyed automatically. Confirm via:

```bash
doctl compute droplet list --format Name,Status,IPv4
# should NOT contain 'donna-drill-*'
```

If you see a `donna-drill-*` droplet still listed after a passing
run, the cleanup failed silently — destroy it manually with:

```bash
doctl compute droplet delete <id> --force
```

---

## What "failing" looks like + per-phase troubleshooting

### Phase 1 (prerequisites) — exit 10

Most common: `doctl auth list` shows no token, or the SSH key isn't
registered.

```bash
# re-authenticate
doctl auth init

# re-register SSH key
doctl compute ssh-key import donna-drill --public-key-file ~/.ssh/donna-drill-key.pub
```

### Phase 2 (provisioning) — exit 20

Common causes:
- DO account ran out of droplet quota (default is 10 droplets per
  account).
- Region capacity issue. Try `DRILL_REGION=sfo3` or `tor1`.
- API token doesn't have write scope.

Inspect the create attempt:

```bash
cat /tmp/donna-drill-<ts>/droplet-create.err
```

### Phase 3 (bootstrap) — exit 30

Common causes:
- `apt-get` fails because DO image was unhealthy. Retry the drill —
  next provision usually gets a different image instance.
- Backup transfer integrity mismatch. Local backup file might be
  corrupted; verify with `donna-verify-backup.sh` against the
  intended tarball.
- Repo clone failed. Could be GitHub rate-limit or network blip.

Inspect:

```bash
cat /tmp/donna-drill-<ts>/bootstrap.log
```

If `KEEP_ON_FAIL=true` (default), SSH in and inspect:

```bash
ssh -i ~/.ssh/donna-drill-key root@<droplet-ip>
cd /opt/donna
ls -la
```

### Phase 4 (restore) — exit 40

This is the most diagnostic phase. Common causes:

- **Alembic migration race**: backup has rows that violate a newer
  migration's invariants. Look at:
  ```bash
  cat /tmp/donna-drill-<ts>/restore.log
  ```
- **Schema mismatch**: backup was taken from a v0.6.x DB but the
  cloned repo is v0.7.3. The drill clones at v0.7.3 — if your backup
  is older, set `DRILL_EXPECTED_VERSION` to the version that backup
  was taken at, OR check out an older tag of the repo first.
- **Permissions**: extracted files chowned wrong. The script does
  `chown -R 1001:1001 /data/donna` but if the tarball had unexpected
  ownership, this might fail.

### Phase 5 (smoke checks) — exit 50

Hard failures:
- **alembic_version mismatch**: the migration upgrade didn't reach
  the expected version. Read `restore.log` — likely a migration
  failed mid-way and exited cleanly anyway.
- **integrity_check fails**: SQLite database was corrupted in the
  tarball. The backup itself is bad — investigate `donna-backup.sh`
  on the production droplet.
- **foreign_key_check finds violations**: the backup has orphan rows
  (a child row referencing a parent that doesn't exist). Either the
  backup is corrupt, or the production DB has FK violations that
  the drill exposes.

Both of the latter two are SERIOUS — do not destroy the drill
droplet; SSH in and investigate. The bug is in your backup pipeline
or your production data.

### Phase 6 (test suite) — exit 60

Common causes:
- **Test count regressed**: drill expects 639 tests; if some failed
  there's a real regression. Read the bottom of `test-output.log`
  for the failing tests. Compare against your local `pytest -q`.
- **Environment mismatch**: the drill droplet is Ubuntu 24.04 +
  Python 3.12 (image default), while your dev environment may be
  3.14. Some Python 3.14-specific behavior may diverge. If this
  happens, install Python 3.14 in the bootstrap phase.

---

## Inspecting a failed drill

If `KEEP_ON_FAIL=true` (default) and the drill failed, the script
prints:

```
SSH:     ssh -i ~/.ssh/donna-drill-key root@<ip>
Destroy: doctl compute droplet delete <id> --force
```

SSH in and start with:

```bash
# What state is the droplet in?
ls -la /opt/donna /data/donna
docker ps -a
sqlite3 /data/donna/donna.db 'SELECT version_num FROM alembic_version'
```

Look at `/var/log/cloud-init-output.log` if Phase 2 / 3 was odd.

When done investigating:

```bash
doctl compute droplet delete <id> --force
```

Always verify with `doctl compute droplet list` afterward.

---

## After a passing drill

1. **Update `KNOWN_ISSUES.md`** — close the "restore drill never
   completed" follow-up. Record date + tarball SHA used.
2. **Enable `donna-update.timer`** on the production droplet — the
   gate per Codex's rule was specifically "no auto-update without a
   passing restore drill." Now you can:

   ```bash
   ssh bot@<production-ip>
   sudo systemctl enable --now donna-update.timer
   sudo systemctl status donna-update.timer
   ```

   This unblocks PATH_3_INVARIANTS §21 Phase 0 final criterion
   ("Auto-update timer un-gated post-drill") and clears Donna's
   internal #17 follow-up.
3. **Begin Phase 1 spine work on P920.** Phase 0 gate is now
   satisfied.

---

## Frequency

- **Quarterly minimum.** Calendar reminder.
- **After any change that touches schema** — every migration past
  0014 should trigger a drill before that migration reaches
  production. (Also bump `DRILL_EXPECTED_VERSION` env var after
  migration head changes.)
- **After any change to `donna-backup.sh`** — the backup pipeline
  itself.
- **After any backup format change.** (None expected during the
  freeze, but if it happens, drill catches it.)

---

## What this drill does NOT cover

- **Slack-side credential rotation.** That's `docs/slack/TOKEN_ROTATION.md`.
- **Off-droplet backup discipline** — the drill consumes a tarball;
  it doesn't validate that tarballs are reaching OneDrive on the
  expected cadence. Spot-check that separately.
- **Multi-day operational soak.** This is point-in-time. The
  production droplet has its own soak per
  `docs/RELEASE_SOAK_POLICY.md`.
- **Operator passphrase / hardware-key recovery.** That's DR-3 / DR-6
  in PATH_3_INVARIANTS §17 — separate runbook (which the new
  system's Phase 0 must include).

---

## Security note

The drill droplet contains:
- A copy of your Donna SQLite database (real personal data)
- A copy of your artifacts directory (real fetched URLs, sanitized
  summaries, saved facts)

DO NOT skip the cleanup step on a passing drill. DO destroy a failed
drill once you've inspected it. The drill droplet has no firewall
hardening (`harden-droplet.sh` isn't part of bootstrap because the
drill is intentionally short-lived); treat it as exposed.

If you SSH into a failed drill, do not paste production tokens, do
not log in via secrets-manager auto-fill that might leak credentials
to bash history. Read-only investigation only.
