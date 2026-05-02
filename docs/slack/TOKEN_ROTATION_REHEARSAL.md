# Token rotation rehearsal

**Practice the runbook against a throwaway test app before you need it for real.**

Codex 2026-05-01 review: "Secret rotation runbook is not enough. Run it once."

This rehearsal mirrors `docs/slack/TOKEN_ROTATION.md` but against a **second Slack app** that's deliberately separate from production Donna. You go through every step, including the parts that touch sops + the droplet, without any risk to live operations.

**Time required:** ~30 minutes including the first-time app setup.

**Frequency:** quarterly minimum, plus any time you suspect leaked credentials.

---

## One-time setup: create a rehearsal app

1. Slack apps dashboard → **Create New App** → **From an app manifest**.
2. Pick a *different* Slack workspace for the rehearsal (a free personal one is fine — Slack's Free tier is sufficient).
3. Paste the manifest from `docs/slack/app-manifest.yml` but rename the `display_information.name` to `Donna-Rehearsal`.
4. Click Create → Install to Workspace → approve scopes.
5. Collect:
   - `xoxb-...` from OAuth & Permissions
   - `xapp-...` from Basic Information → App-Level Tokens (generate one, scope `connections:write`)
   - `T...` workspace ID
   - Your `U...` user ID in the rehearsal workspace

Stash these in a temp text file *on disk* (not in chat / not in the repo). You'll throw them away after the rehearsal.

---

## Rehearsal steps

Run the **production** runbook (`docs/slack/TOKEN_ROTATION.md`) verbatim, substituting:

| Production reference | Rehearsal substitute |
|---|---|
| Slack app dashboard → Donna | Slack app dashboard → Donna-Rehearsal |
| `secrets/prod.enc.yaml` | `secrets/rehearsal.enc.yaml` (create + add to .gitignore for rehearsal-only files) |
| Production droplet | Skip the droplet step entirely — `git pull && docker compose down && up` is what you'd practice on prod, but the rehearsal stops at the local sops update |
| `/donna_status` verification | Verify in the rehearsal workspace with the rehearsal app's slash command (it'll have the same prefix per manifest, but a different bot user) |

Steps to specifically verify:

1. **Step 2 (bot token rotation):** Revoke All OAuth Tokens → Reinstall → confirm new token DIFFERS from the old one. The whole point of the runbook is that "Reinstall" alone doesn't always rotate; this step proves you can force a rotation.
2. **Step 3 (app-level token):** Revoke + regenerate → confirm new token works for Socket Mode connection.
3. **Step 6 (sops update):** Use a test sops file. Verify you can decrypt it (`sops -d secrets/rehearsal.enc.yaml`).
4. **Step 7 (verification):** Skip the production-droplet steps. Practice the verification commands locally with `python -c "from slack_sdk.web.client import WebClient; ..."` against the rehearsal token.

---

## Mistakes to look out for during the rehearsal

These are the failure modes the rehearsal exists to catch *before* a real incident:

- **You can't find the "Revoke All OAuth Tokens" button.** It's at the *bottom* of the OAuth & Permissions page, red text, easy to miss. Click around until you find it without the runbook open. The whole reason this runbook exists is the operator pasted tokens into chat once and assumed "Reinstall to Workspace" rotated them — it didn't.
- **You forget to scope app-level token to `connections:write`.** Without it, Socket Mode connection fails with a confusing `not_authed` error.
- **sops decrypt fails.** Wrong age key, wrong recipient, the secrets file has been edited outside sops. Common, dangerous in production.
- **The bot user ID doesn't match `SLACK_ALLOWED_USER_ID`.** Same hole that bit us 2026-05-02 (V50-3 `app_mention` events silently dropped).

---

## After the rehearsal

1. **Throw away the rehearsal credentials.** Delete the rehearsal app from the dashboard, or just leave it dormant.
2. **Update production runbook if anything was unclear during rehearsal.** The runbook is only as good as how easy it is to follow under stress.
3. **Log the rehearsal in the brain note** (`Insights/secret-rotation-rehearsal.md`):
   - Date
   - Anything confusing or surprising
   - Time taken
   - Whether the runbook needs updates

---

## When to actually rotate

Run the **production** runbook (not this rehearsal) when:

- A token leaked (chat, log, screenshot, repo, Docker env dump)
- A team member with deploy access leaves
- 90 days have passed since last rotation
- Slack alerts you about suspicious API usage

Don't rotate "just in case" without a trigger. Each rotation has ~5 minutes of downtime; routine rotation makes outages routine.
