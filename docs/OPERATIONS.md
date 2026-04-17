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
- Restore `/data/donna.db` from backup (rsync/restic — not set up in v1; add this when you have active use)
- `first-deploy.sh` and you're back
