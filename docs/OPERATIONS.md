# Operations

Quick reference for running Donna day-to-day.

## First-run checklist (tomorrow morning on the clean laptop)

1. **Transfer GitHub ownership** (if staying with Path A)
   - GitHub → `GlobalCan/donna` → Settings → Transfer ownership → target `bot-ops` account
2. **Clone on other machine**
   ```bash
   gh auth login       # as bot-ops
   git clone git@github.com:<bot-ops-user>/donna.git
   cd donna
   python3.12 -m venv .venv
   source .venv/bin/activate   # or .venv/Scripts/activate on Windows
   pip install -e ".[dev]"
   alembic upgrade head
   pytest -q
   ```
3. **Provision the rest of the accounts** (per `docs/PLAN.md`):
   - Anthropic, Discord app, Tavily, Voyage, DigitalOcean droplet
4. **Generate age keypair** and encrypt first `secrets/prod.enc.yaml`
5. **Harden droplet**
   ```bash
   scp scripts/harden-droplet.sh root@<ip>:/root/
   ssh root@<ip> bash /root/harden-droplet.sh
   scp ~/.donna/age.key root@<ip>:/etc/bot/age.key
   ssh root@<ip> "chmod 600 /etc/bot/age.key && chown bot:bot /etc/bot/age.key"
   ```
6. **First deploy**
   ```bash
   ssh bot@<ip>
   git clone git@github.com:<bot-ops-user>/donna.git
   cd donna
   # fill .env or rely on sops-encrypted secrets
   docker compose pull
   docker compose up -d
   docker compose exec bot alembic upgrade head
   sudo systemctl enable --now donna-update.timer
   ```
7. **First smoke test** — DM the bot on Discord ("hello"), confirm it replies

## Daily ops

- `botctl jobs` — see what's running
- `botctl job <id>` — drill into one
- `botctl cost` — today's spend
- `botctl schedule list` — active crons
- `/status <id>` / `/budget` / `/history` from Discord
- Jaeger UI: `ssh -L 16686:localhost:16686 -i <key> bot@<ip>` then open `http://localhost:16686`, filter by service=`donna`. (Phoenix was replaced after 14.x broke upstream; see `docker-compose.yml` for rationale.)

## Teaching a scope

```bash
# Local or via ssh on droplet
botctl teach author_twain /path/to/huck.txt \
    --source-type book --title "Huck Finn" \
    --copyright-status public_domain --publication-date 1884-12-10
```

Or via Discord: `/teach` (not wired in v1 — use CLI).

## Rotating a compromised key

- Pause containers: `docker compose stop`
- Revoke at provider
- Get new key, update `secrets/prod.enc.yaml` (sops), push
- `docker compose up -d`

## Rollback

- `git revert` the bad commit and push, OR
- SSH to droplet, edit `.env` to pin a previous image tag, `docker compose pull && up -d`

## If the droplet is lost

- New droplet, run `harden-droplet.sh`
- Restore `/data/donna.db` from backup (see DR section below)
- `first-deploy.sh` and you're back

## Disaster recovery (v1 — honest story)

### Age key
- Generate on laptop: `age-keygen -o ~/.donna/age.key` → copy to droplet `/etc/bot/age.key`
- **Add a second recipient** to `.sops.yaml` — ideally a paper-backup key stored offline or in a bank deposit box. With two recipients, losing either one still leaves you able to decrypt with the other. Re-encrypt every `secrets/*.enc.yaml` after adding the second recipient.
- If you lose BOTH recipients, every committed encrypted secret is unreadable. Rotate all API keys at their providers and start fresh.

### Database backups — current setup (v0.3.1)

Three layers: DO snapshots, droplet-local cron snapshot, laptop pull.

**Layer 1: DO snapshots ($0.30/mo).** Web console → Droplets → donna →
Backups → Enable backups → Daily, 4-week retention. DO ships these to its own
storage; restore = clone droplet from snapshot. Covers droplet death.

**Layer 2: nightly cron on droplet.** `scripts/donna-backup.sh` produces
`/home/bot/backups/donna-<UTC-stamp>.tar.gz` containing a WAL-safe SQLite
snapshot (via `.backup` API, runs concurrently with the live bot) plus all
artifact blobs. Keeps last 7 days locally. Install:

```bash
ssh -i %USERPROFILE%\.ssh\id_ed25519_droplet bot@<ip>
sudo apt-get install -y sqlite3                                    # one-time
mkdir -p /home/bot/backups
# paste contents of scripts/donna-backup.sh -> /home/bot/donna-backup.sh
chmod +x /home/bot/donna-backup.sh
/home/bot/donna-backup.sh                                          # dry-run smoke
(crontab -l 2>/dev/null; echo "0 3 * * * /home/bot/donna-backup.sh >>/home/bot/backups/.cron.log 2>&1") | crontab -
crontab -l                                                         # verify
```

**Layer 3: laptop pull → OneDrive.** `scripts/donna-fetch-backup.ps1` scps
`donna-latest.tar.gz` to `%USERPROFILE%\OneDrive\Donna-Backups\` (so the
backup gets a 4th copy in OneDrive cloud automatically). 30-day local
retention. Wire up via Task Scheduler:

```cmd
schtasks /Create /SC DAILY /ST 06:00 /TN "Donna Backup Fetch" ^
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\dev\donna\scripts\donna-fetch-backup.ps1" /F
```

Manual run any time:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\donna-fetch-backup.ps1
```

### Restore from a tarball

```bash
# on a new droplet (already harden + first-deploy'd)
docker compose stop bot worker
tar -xzf donna-<stamp>.tar.gz -C /tmp/restore
mv /data/donna/donna.db /data/donna/donna.db.broken
mv /data/donna/artifacts /data/donna/artifacts.broken
cp /tmp/restore/donna.db /data/donna/donna.db
cp -r /tmp/restore/artifacts /data/donna/artifacts
chown -R 1001:1001 /data/donna
docker compose up -d
```

### Optional later: `litestream` for continuous replication
The current cron+scp approach gives ~24h RPO. Acceptable for a personal
assistant; not acceptable for anything transactional. If you ever need
sub-minute RPO, add `litestream` streaming to DO Spaces (~$5/mo). Keep the
cron as belt-and-suspenders.

### Weekly backup-tarball verifier (lightweight)

Cheapest drill — proves the TARBALL is a valid SQLite DB with uncorrupted
artifact blobs, without spinning a droplet or touching Discord:

```bash
# On droplet, against the latest nightly:
scripts/donna-verify-backup.sh /home/bot/backups/donna-latest.tar.gz

# On laptop, against the OneDrive copy:
scripts/donna-verify-backup.sh \
    "$env:USERPROFILE\OneDrive\Donna-Backups\donna-<stamp>.tar.gz"
```

The script:

- Extracts the tarball to a temp dir
- Runs `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on the
  snapshot DB
- Counts rows in the core tables (jobs / facts / knowledge_* / artifacts)
- Re-computes SHA-256 of every `.blob` and asserts it matches the filename

Exit 0 + `OK — tarball is valid and restorable` means the data is good.
A real full-deploy drill (below) is still needed; this just prunes out
"the tarball itself was corrupt" from the list of things that can kill
the restore path.

Add to the droplet's crontab if you want continuous proof:
```bash
(crontab -l 2>/dev/null; echo "15 3 * * * /home/bot/donna/scripts/donna-verify-backup.sh >>/home/bot/backups/.verify.log 2>&1") | crontab -
```
(15 minutes after the nightly backup runs at 03:00 UTC.)

### Quarterly full restore drill
Pick a random Saturday every 3 months. Provision a throwaway droplet,
restore from your most recent backup (see above), boot the bot, DM it
"hello." If it answers, you're covered. If not, you have time to fix the
DR story before you actually need it.

**Gotcha:** the existing droplet's `DISCORD_BOT_TOKEN` is the same token
the throwaway droplet would use; running both simultaneously makes
Discord kick one. Easiest workflow: stop the main container, spin the
drill droplet, DM, confirm, destroy the drill droplet, restart main.
Total downtime: ~5 min. Cost: ~$0.01 in droplet hours.

### Enabling auto-update (`donna-update.timer`)

`harden-droplet.sh` installs a systemd unit + timer that does
`git pull && docker compose pull && up -d` every 5 min. It's
**deliberately left disabled** until the operator has confirmed backups
work (above) — auto-deploy without a proven restore path widens blast
radius per Codex.

Once the tarball verifier has passed on a real backup AND you've done
at least one quarterly full restore drill, enable it via the DO web
console (bot has no sudo password):

```bash
# As root via DO recovery console:
systemctl enable --now donna-update.timer
systemctl status donna-update.timer
```

After that, any merge to main → GHA builds image → ~5 min → droplet pulls
+ restarts automatically. Rollback is `git revert + push`, not a manual
image pin.
