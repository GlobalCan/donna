# Slack token rotation runbook

> **When to use this:** anytime you suspect a Donna Slack credential has
> leaked. Common triggers:
> - Token pasted into chat / log / git history (caught operator twice
>   in v0.5.0 smoke).
> - Container env dump exposed via `docker inspect` to a 3rd party.
> - End-of-quarter security hygiene.
> - Off-boarding anyone who had droplet deploy access.
>
> **What this rotates:** the bot token (`SLACK_BOT_TOKEN`, `xoxb-...`)
> and/or the Socket Mode app-level token (`SLACK_APP_TOKEN`, `xapp-...`).
>
> **Time required:** ~10 minutes including bot restart and smoke test.
>
> **Hard rule from v0.5.0:** Slack's "Reinstall to Workspace" button does
> NOT actually rotate the bot token most of the time. Always go through
> the explicit revoke + reinstall path documented below. (See brain note
> `slack-reinstall-doesnt-always-rotate.md` for context.)

---

## Step 1 — Decide what to rotate

| Suspect | Rotate |
|---|---|
| Bot token pasted somewhere (`xoxb-...`) | Step 2 (bot token only) |
| App-level token leaked (`xapp-...`) | Step 3 (app token only) |
| Both leaked, or unsure | Both — Step 2 then Step 3 |
| App's signing secret leaked | Step 4 |
| Client secret leaked (rare for Donna; we use Socket Mode) | Step 5 |

If unsure: rotate everything. The cost is ~5min of bot downtime; the
cost of a leaked token is unbounded.

---

## Step 2 — Bot token (`xoxb-...`)

1. Go to the [Slack apps dashboard](https://api.slack.com/apps), pick the
   Donna app.
2. **OAuth & Permissions** → scroll to the bottom → **"Revoke All OAuth
   Tokens"** (red button) → confirm.
   - This destroys the existing `xoxb-` immediately. The bot stops being
     able to authenticate from this moment.
   - **Do NOT click "Reinstall to Workspace" without revoking first** —
     reinstall alone reuses the existing token most of the time.
3. Scroll back up → **"Install to Workspace"** → review scopes → approve.
4. The page now shows a fresh **Bot User OAuth Token** (`xoxb-...`) at
   the top. Copy it (don't paste in chat — keep it in the clipboard).

---

## Step 3 — App-level token (`xapp-...`)

1. Same Slack app dashboard → **Basic Information**.
2. Scroll to **App-Level Tokens** section.
3. Click on the existing token name (e.g. `donna-socket-mode`).
4. Click **"Revoke"** → confirm.
5. Back on Basic Information → **"Generate Token and Scopes"** → enter
   the same name → add scope `connections:write` → **Generate**.
6. Copy the new `xapp-...`.

---

## Step 4 — Signing secret (if leaked)

Donna uses Socket Mode, so the signing secret isn't on the hot path.
But it's still part of the app config and worth rotating if exposed.

1. Slack app dashboard → **Basic Information** → **App Credentials**.
2. Click **Regenerate** next to **Signing Secret**.
3. Update `SLACK_SIGNING_SECRET` in secrets if Donna ever starts using
   it (e.g. if we ever flip from Socket Mode to HTTP events).

---

## Step 5 — Client secret (if leaked)

Same Basic Information → **App Credentials** → **Regenerate** next to
**Client Secret**. Donna doesn't use OAuth 2.0 redirect flow, so this is
only material if the secret was exposed via the dashboard URL.

---

## Step 6 — Update Donna's secrets

The droplet reads from `secrets/prod.enc.yaml` (sops + age encrypted).
Update the relevant fields:

```bash
# On your laptop
cd /c/dev/donna
sops secrets/prod.enc.yaml
# Edit:
#   slack_bot_token: xoxb-NEW-TOKEN
#   slack_app_token: xapp-NEW-TOKEN
# Save with :wq
git add secrets/prod.enc.yaml
git commit -m "Rotate Slack credentials (incident: <reason>)"
git push origin main
```

Then on the droplet (no other deploy needed if secrets-only change):

```bash
ssh bot@<droplet-ip>
cd ~/donna
git pull
docker compose down
docker compose up -d
docker compose logs -f bot --tail=30
# Look for: "slack.start" with no SLACK_BOT_TOKEN errors
```

If the droplet's deploy key is read-only and you need to push from the
droplet (because secrets were edited there), see
`docs/slack/PHASE_0_RUNBOOK.md` §Deploy-key write-toggle.

---

## Step 7 — Verify rotation

In Slack, send Donna a DM:

```
/donna_status
```

Expected: response from Donna, no auth errors in container logs.
If you see `invalid_auth` or `token_revoked` in logs, the bot is still
holding the old token — restart the container.

Quick smoke for both tokens:

```bash
# On droplet
docker compose exec bot python -c "
from slack_sdk.web.client import WebClient
from donna.config import settings
s = settings()
client = WebClient(token=s.slack_bot_token)
print('auth:', client.auth_test()['ok'])
"
```

---

## Step 8 — Audit trail

After rotation, log it in the brain note (`Insights/`):

- What was rotated (bot/app/signing)
- Why (leak / hygiene / off-boarding)
- Date
- Whether the leaked value was confirmed compromised or only suspected

This is the audit record. Don't include the actual tokens (old or new).

---

## What NOT to do

- **Don't click "Reinstall to Workspace" alone.** Slack returns the same
  `xoxb-` most of the time; the reinstall flow is for scope refresh, not
  rotation.
- **Don't paste tokens into chat / Slack / commit messages** — including
  this file. The whole reason this runbook exists is the v0.5.0 incident
  where tokens got pasted during smoke.
- **Don't enable Slack's "Token rotation" feature** in Basic Information
  unless you're ready to plumb refresh-token cycling. Donna v0.5.x
  explicitly does NOT use it; manual rotation per this runbook is the
  current model.
- **Don't skip Step 7.** A "successful" rotation that leaves the bot
  silently using the old token is worse than no rotation.

---

## When rotation is part of a wider response

If the leak is part of a broader incident (e.g. droplet compromise,
deploy-key exfiltration), rotation is just the first step. Also do:

- Rotate `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `VOYAGE_API_KEY`
- Rotate the droplet's age key (re-encrypt secrets with new keypair)
- Rotate the GitHub deploy key
- Audit `outbox_dead_letter` and `tool_calls` for anomalous activity in
  the suspect window
- Force-push a `git push origin :branch` for any branches that contained
  leaked secrets (and rotate everything from those branches anyway —
  GitHub caches, archive sites, attacker mirrors)

See `docs/OPERATIONS.md` §Disaster recovery for the full incident playbook.
