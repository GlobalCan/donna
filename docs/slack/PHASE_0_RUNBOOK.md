# Phase 0 — Slack smoke test runbook

> **Goal:** prove the 9 Slack primitives Donna depends on actually work
> in this environment, before we delete a single line of Discord code.
>
> **Time:** ~10 minutes once tokens are pasted. ~30 minutes total
> including the app-creation step.
>
> **Outcome:** PASS/FAIL list for each primitive. If everything's green,
> Phase 1 (schema migration) starts immediately. If anything's red, we
> triage before destructive work.

---

## What we're testing

| # | Primitive | Why it matters |
|---|---|---|
| 1 | Socket Mode connects from this environment | Proves outbound WebSocket reaches Slack with no inbound HTTPS endpoint. If this fails, the whole architecture needs rethinking. |
| 2 | Bot receives DM events | Validates `message.im` subscription + payload shape. |
| 3 | Bot replies via `chat.postMessage` | Outbound posting works. |
| 4 | Slash command `/donna_smoke` reaches handler | Slash routing works; ephemeral acks render correctly. |
| 5 | Modal opens from slash command | Replaces Discord's bad slash-arg parsing for `/schedule`. |
| 6 | Modal submission delivers form values to handler | Structured input is viable. |
| 7 | Block Kit message with button renders | Consent flow primitive. |
| 8 | Button click → handler fires within 3s + `chat.update` works | Consent flow complete shape. Ack-then-edit replaces Discord's reaction model. |
| 9 | `chat.postMessage` to a specific channel | Channel-target scheduling is feasible. |

---

## Step 1 — create the Slack app

1. Go to <https://api.slack.com/apps>
2. Click **"Create New App"** → **"From an app manifest"**
3. Pick your personal Slack workspace
4. Open `docs/slack/app-manifest.yml` from this repo, copy the entire file
5. Paste into the manifest editor → click **"Next"** → **"Create"**

## Step 2 — install to workspace

1. In the app's left sidebar, click **"Install to Workspace"**
2. Approve the requested scopes (matches what's in the manifest)
3. You're redirected to the app dashboard

## Step 3 — collect tokens

You need three values. **Treat these like passwords — don't paste in chat, don't commit to git.**

### `SLACK_BOT_TOKEN` (starts `xoxb-`)

- Left sidebar → **"OAuth & Permissions"**
- Top of page: **"Bot User OAuth Token"** → click "Copy"

### `SLACK_APP_TOKEN` (starts `xapp-`)

- Left sidebar → **"Basic Information"**
- Scroll to **"App-Level Tokens"** → **"Generate Token and Scopes"**
- Name: `donna-socket-mode`
- Scope: `connections:write` (only)
- Click "Generate" → copy the token

### `SLACK_TEAM_ID` (starts `T0...`)

Easiest: visit your Slack workspace in a browser. Look at the URL —
e.g. `https://app.slack.com/client/T0ABCDEFG/...` — the `T0ABCDEFG`
chunk is your team ID.

Alternative: **"Basic Information"** → scroll to **"Display Information"**
→ "Workspace Team ID" might be visible there.

## Step 4 — invite the bot to a channel (for primitive #9)

The bot needs to be a member of at least one channel for the
"post to channel" test. In Slack:

1. Go to any channel (`#general` works, or create a `#donna-smoke` test channel)
2. Type `/invite @donna`
3. Confirm

Note the channel ID (right-click channel → "Copy link" → the trailing chunk after the last `/`). Paste this when the smoke prompts.

## Step 5 — set environment variables

On your laptop (PowerShell):

```powershell
$env:SLACK_BOT_TOKEN = "xoxb-..."
$env:SLACK_APP_TOKEN = "xapp-..."
$env:SLACK_TEAM_ID = "T0..."
$env:SLACK_TEST_CHANNEL = "C0..."   # the channel ID from Step 4
```

Or in bash / Git Bash:

```bash
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_APP_TOKEN="xapp-..."
export SLACK_TEAM_ID="T0..."
export SLACK_TEST_CHANNEL="C0..."
```

## Step 6 — install slack_bolt and run the smoke

```bash
.venv/Scripts/pip install slack-bolt
python scripts/slack_smoke.py
```

The script:

1. Connects via Socket Mode
2. Prints "✅ Socket Mode connected" or "❌ FAIL: <reason>"
3. Prints next-step instructions for the interactive primitives ("DM the bot anything", "type `/donna_smoke` anywhere", etc.)
4. Logs each primitive's PASS/FAIL as you exercise it
5. Prints a final summary table when you Ctrl+C

## Step 7 — paste output back to Claude

Copy the final summary block (the one with "PASS" / "FAIL" for each primitive). I'll read it and either:

- All green → start Phase 1 (schema migration) immediately
- Anything red → triage and fix before any destructive change

---

## What if something fails

**Socket Mode won't connect:**
- Check outbound WebSocket isn't blocked (corporate firewall, VPN)
- Verify `SLACK_APP_TOKEN` has `connections:write` scope (not the default scopes)
- Check Slack app status page

**Slash command "dispatch_failed":**
- Re-check the manifest got applied (Slack sometimes needs a re-install after manifest edits)

**Button click doesn't fire:**
- Verify Interactivity is enabled in the app settings
- Some browsers cache Slack's UI badly — try a different browser

**Permission denied on channel post:**
- Bot isn't a member of `SLACK_TEST_CHANNEL` — re-run `/invite @donna`

If any of the above don't unblock, paste me the script output verbatim and I'll triage.

---

## Cleanup after Phase 0

`scripts/slack_smoke.py` and the `/donna_smoke` slash command are
**throwaway** — both get deleted before the v0.5.0 ship. The app
manifest at `docs/slack/app-manifest.yml` becomes the v0.5.0 source
of truth and stays in the repo.
