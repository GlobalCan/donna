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
- Phoenix: `ssh -L 6006:localhost:6006 scout` then open `http://localhost:6006`

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

### Quarterly restore drill
Pick a random Saturday every 3 months. Provision a throwaway droplet, restore
from your most recent backup, boot the bot, DM it "hello." If it answers, you're
covered. If not, you have time to fix the DR story before you actually need it.
