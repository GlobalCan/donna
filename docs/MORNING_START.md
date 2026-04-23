# Morning start — what to do when you wake up

Everything below is runnable in order. Estimated total time: **2–3 hours**.

## 1. Clone on the other laptop (5 min)

```bash
# Install prerequisites: git, python 3.12, docker, gh cli
gh auth login                              # sign in as GlobalCan for now
git clone git@github.com:GlobalCan/donna.git
cd donna

python3.12 -m venv .venv
source .venv/bin/activate                  # or .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## 2. Run the tests (2 min)

```bash
# Offline tests only — no real API calls
pytest -q
```

Expected: all pass. If any fail, fix before continuing.

## 3. Create the `bot-ops` identity (15 min)

- Sign up fresh GitHub: `<yourname>-bot-ops`
- Enable 2FA
- Create new private repo `donna`
- Push an SSH key

Then transfer `GlobalCan/donna` → `<bot-ops>/donna`:
- GitHub → repo → Settings → **Transfer ownership**
- Update the remote on both machines:
  ```bash
  git remote set-url origin git@github.com:<bot-ops>/donna.git
  ```

## 4. Provision the service accounts (30 min)

All with the bot-ops email, Privacy.com virtual cards:

- **Anthropic** → API key → save as `ANTHROPIC_API_KEY`, set $50/mo cap
- **Discord** — new app, bot token, **enable `MESSAGE_CONTENT` privileged intent**, invite to a private server with only you
- **Tavily** → API key
- **Voyage AI** → API key
- **DigitalOcean** → create $6/mo Ubuntu 24.04 droplet, SSH key

## 5. Generate the age keypair (2 min)

```bash
mkdir -p ~/.donna
age-keygen -o ~/.donna/age.key
# Copy the `# public key: age1...` line
```

Edit `.sops.yaml` — replace `age1REPLACE_WITH_YOUR_PUBLIC_KEY_HERE` with yours, commit.

## 6. Encrypt the first secrets file (5 min)

`prod.enc.yaml` is parsed as YAML at container startup (`scripts/entrypoint.sh`),
so the plaintext source must be YAML (`KEY: value`), not dotenv (`KEY=value`).
Quote Discord snowflake IDs so they stay strings rather than being coerced to int.

```bash
cat > /tmp/plain.yaml <<'EOF'
DISCORD_BOT_TOKEN: mfa.xxx
DISCORD_ALLOWED_USER_ID: "123456789012345678"
DISCORD_GUILD_ID: "123456789012345678"   # optional; omit if you don't use a guild
ANTHROPIC_API_KEY: sk-ant-xxx
TAVILY_API_KEY: tvly-xxx
VOYAGE_API_KEY: pa-xxx
EOF
sops -e /tmp/plain.yaml > secrets/prod.enc.yaml
rm /tmp/plain.yaml
git add secrets/prod.enc.yaml
git commit -m "Initial encrypted secrets"
git push
```

## 7. Harden the droplet (10 min)

```bash
# from laptop
scp scripts/harden-droplet.sh root@<DROPLET_IP>:/root/
ssh root@<DROPLET_IP> bash /root/harden-droplet.sh
scp ~/.donna/age.key root@<DROPLET_IP>:/etc/bot/age.key
ssh root@<DROPLET_IP> "chown bot:bot /etc/bot/age.key && chmod 600 /etc/bot/age.key"
```

## 8. First deploy (15 min)

```bash
ssh bot@<DROPLET_IP>
git clone git@github.com:<bot-ops>/donna.git
cd donna

# Pull signed image from GHCR (first push will happen via GHA once you push to main)
# If the image isn't built yet, build locally:
docker build -t ghcr.io/<bot-ops>/donna:latest .

cp .env.example .env   # will still be overridden by sops at runtime
docker compose up -d

# Wait ~10s, then migrate
docker compose exec bot alembic upgrade head

# Enable the update timer
sudo systemctl enable --now donna-update.timer
```

## 9. First smoke test (5 min)

- Open Discord
- DM the bot: `hello`
- Expected: it replies with `📌 Job ... queued. I'll post updates...` and later a response from the orchestrator
- Try: `/status <job_id>` — should return a rich embed
- Try: `/budget` — should show $0.00 spend initially

## 10. Teach your first scope (10 min)

Start with a public-domain author to validate the pipeline cleanly:

```bash
# On your laptop or on the droplet
curl -o huck.txt https://www.gutenberg.org/files/76/76-0.txt
botctl teach author_twain huck.txt \
    --source-type book --title "Adventures of Huckleberry Finn" \
    --copyright-status public_domain --publication-date "1884-12-10"

# Then in Discord:
# /ask scope=author_twain question="What did Twain think about formal education?"
```

## 11. Check Phoenix (5 min)

```bash
ssh -L 6006:localhost:6006 bot@<DROPLET_IP>
# open http://localhost:6006 in browser
# filter: agent.job.tainted = true to see any tainted runs
```

## 12. Set up the daily scheduled task (2 min)

```bash
# Via Discord:
# /schedule cron_expr="0 8 * * *" task="morning brief: what's new in AI today?"
```

## When done

- Bot is live, taking DMs, durable across restarts
- One persona loaded + grounded + speculative working
- Phoenix traces flowing
- `botctl` works locally
- You can go to bed knowing if anything dies, the systemd timer + checkpoint recovery will handle it

## If something breaks

- Check `docker compose logs bot worker phoenix --tail 100`
- Check `botctl jobs` for any stuck rows
- Phoenix view → filter by job_id
- Worst case: `docker compose down -v && docker compose up -d` — DB survives on `/data`
