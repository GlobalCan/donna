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

### Database backups — use `litestream` (recommended)
`litestream` streams SQLite WAL frames to a remote store (DO Spaces, S3, SFTP).
Low overhead, continuous replication, point-in-time restore.

```bash
# on droplet
apt-get install -y litestream
# /etc/litestream.yml example (edit endpoints for your own DO Space)
cat > /etc/litestream.yml <<'EOF'
dbs:
  - path: /data/donna/donna.db
    replicas:
      - type: s3
        endpoint: https://nyc3.digitaloceanspaces.com
        bucket: donna-backups
        path: donna.db
        access-key-id: ...
        secret-access-key: ...
EOF
systemctl enable --now litestream
```

Restore: `litestream restore -o /data/donna/donna.db s3://donna-backups/donna.db`

### Manual fallback (if no litestream yet)
```bash
# on droplet — run nightly via cron
sqlite3 /data/donna/donna.db ".backup '/tmp/donna-$(date +%F).db'"
# ship off-droplet somehow — rsync to laptop, or `doctl spaces upload`
```

### Quarterly restore drill
Pick a random Saturday every 3 months. Provision a throwaway droplet, restore
from your most recent backup, boot the bot, DM it "hello." If it answers, you're
covered. If not, you have time to fix the DR story before you actually need it.
