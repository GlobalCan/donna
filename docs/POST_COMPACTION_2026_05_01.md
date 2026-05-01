# Post-compaction bootstrap — Donna 2026-05-01 (v0.5.0 shipped)

> **Use this if:** the conversation has just been compacted (auto or
> manual), or you're a fresh Claude Code session continuing work on
> Donna at the v0.5.0 state. Paste the prompt below as your first
> message. v0.5.0 retooled the adapter from Discord to Slack;
> live-smoked clean in operator's personal Slack workspace.
>
> **Don't use this for:** a brand-new laptop bootstrap (use
> `docs/CONTINUE_HERE.md` instead). This doc assumes the operator
> and the prior session were mid-thread and you're picking up where
> it stopped.

---

## The prompt to paste

```
Hi Claude. Continuing work on Donna at v0.5.0. The prior session shipped
the Slack adapter retool (Discord → Slack) end-to-end:

- v0.4.3 (yesterday) — scheduler delivery fix
- v0.4.4 (yesterday) — tainted session memory: tag-and-render, not skip
- v0.5.0 (today) — Slack adapter retool, live-smoked 4/4 green

Donna is now live in my personal Slack workspace, deployed via the
production droplet. v0.4.4 Discord state is preserved at git tag
legacy/v0.4.4-discord for emergency revival.

Step 1 — Orient

Read in this order before anything else:

1. README.md — status block reads v0.5.0 / 373 tests / Slack live
2. CHANGELOG.md — [0.5.0] entry covers the migration end-to-end
3. docs/SESSION_RESUME.md — v0.5.0 state snapshot
4. docs/KNOWN_ISSUES.md — v0.5.0 follow-ups table (V50-1 .. V50-9)
   has the deferred work for v0.5.1
5. docs/slack/PHASE_0_RUNBOOK.md — historical: how Phase 0 smoke
   was run before destructive migration
6. docs/slack/WAKE_UP.md — historical: handoff doc from overnight
   build (now superseded by this file but kept for context)
7. docs/POST_COMPACTION_2026_05_01.md — this file

Confirm orientation in ONE paragraph: what Donna is, where v0.5.0
landed, what's queued for v0.5.1, and what you need from me to pick
the next track. Wait for my answer before doing anything.

Step 2 — Current state

- main is at v0.5.0 release. Tag pushed, GitHub release published.
- 0 open PRs.
- ghcr.io/globalcan/donna:latest and :v0.5.0 both rebuilt + published.
  Operator deployed via docker compose pull && up -d on the droplet.
- All 4 critical Slack smoke tests passed:
    1. DM intake + reply
    2. /donna_ask grounded mode (citations + validator footer)
    3. /donna_schedule modal + scheduled DM delivery
    4. Block Kit consent buttons (✅/❌ + chat.update edit)
- secrets/prod.enc.yaml updated on droplet but NOT yet pushed to
  GitHub — droplet's deploy key is read-only; operator can flip it
  writable to push, or just leave it (runtime reads from local file
  via bind mount, so not blocking).

Step 3 — What's queued for v0.5.1

KNOWN_ISSUES.md "v0.5.0 follow-ups" table has 9 items. Tier-ranked:

Tier 1 (HIGH — fix soon):
- V50-1: not_in_channel infinite retry storm. The adapter's outbox
  drainer retries failed chat.postMessage every ~1.5s forever when
  Slack returns non-retryable errors. Should detect and dead-letter.
  Real prod issue — operator hit it during smoke.

Tier 2 (MEDIUM — when there's a reason):
- V50-2: live-test channel-target scheduling (requires inviting
  Donna to a channel via Integrations → Add apps)
- V50-3: live-test @donna mentions in channels (same gate)
- V50-7: validator footer renders `:warning:` text in Slack instead
  of the ⚠️ Unicode emoji. Cosmetic.
- V50-8: dual-field memory (raw_content + safe_summary) per Codex's
  recommended next iteration

Tier 3 (LOW — nice to have):
- V50-9: push the secrets commit (requires deploy-key write toggle)
- Slack MCP integration setup for direct Slack visibility during
  dev sessions
- Phoenix observability re-enable (when their image stops being broken)
- Off-droplet backup automation verification

Tier 4 (Tier 2 product work from prior plans, still queued):
- /validate <url> URL critique mode — the v0.5+ product feature.
  ~3-4 days. Spec in transcript history. Don't start without my go.
- Daily morning briefing as the first concrete scheduled task —
  channel-target scheduling will make this actually useful (post
  to #morning-brief instead of cluttering DM)
- Notion OR Drive connector — first "read your files" tool
- Persistent web monitoring (cron + diff + notify)

Step 4 — Operator preferences (hard constraints)

- Direct, no hedging. If you think a choice is right or wrong, say so.
- Completeness standard: never present a workaround when the real fix
  exists; never offer to "table this for later."
- Confidence-first: if below 0.7 confident, ask. Wrong-direction work
  wastes more time than a clarifying question.
- Post-implementation self-check: before marking done, run tests +
  show output. Not "should work."
- No emojis in code. Fine in Slack/UX output.
- Markdown bullets + tables > wall-of-text.
- Strong engineer: explain mechanisms, skip basics.
- Security-first, solo-forever: no multi-tenant / SaaS / enterprise.
- Don't push to main directly. Branch + PR for everything except
  trivial doc edits.
- Use gh CLI for GitHub. Always pass --repo GlobalCan/donna explicitly.
- Codex (gpt-5.5-pro default, gpt-5.3-codex fallback for big prompts)
  is wired in API mode via OPENAI_API_KEY in HKCU:\Environment.
  See ~/.claude/CLAUDE.md "Codex Collaboration" section.
- DON'T paste tokens or secrets into chat. Operator did this once
  during the v0.5.0 smoke and we had to rotate. Always reference env
  vars or sops paths instead.

Step 5 — What NOT to do

- Don't start /validate or any Tier 4 product work without explicit
  go-ahead.
- Don't open speculative new branches before the operator picks a track.
- Don't re-rebase or re-merge already-merged PRs.
- Don't refactor the Slack adapter unprompted — it just shipped and
  is being live-validated.
- DON'T touch docs/slack/PHASE_0_RUNBOOK.md or scripts/slack_smoke.py
  — they're throwaways from the migration but operator hasn't
  cleaned them up yet, and they're useful reference for next time
  we add a platform.

Step 6 — Suggested first move

Once you've confirmed orientation, ask me:

  1. Did anything else surface from Slack use after v0.5.0 deploy?
  2. Is V50-1 (not_in_channel retry storm) bothering me enough to
     fix now, or wait?
  3. Where do I want to focus — v0.5.1 polish (V50-1 + V50-7 + V50-8)
     or jump to /validate / connectors / web monitoring?

Then we'll pick what comes next.
```

---

## Reference: what shipped between this session and the prior pause

For your context (do not paste this section to the new session — the
prompt above is self-sufficient):

### v0.5.0 (PR #50, 2026-05-01)

Slack adapter retool. ~28 files changed, ~2200 net lines.

- Migration `0008_slack_schema_cleanup` — rename `discord_*` columns,
  INTEGER→TEXT for Slack `ts` strings, add `target_channel_id` +
  `target_thread_ts` to schedules.
- `adapter/slack_adapter.py` (~370 lines) — Socket Mode handler,
  outbox drainers, Block Kit rendering, per-channel rate limit,
  untrusted-text escaping, allowlist by team_id + user_id.
- `adapter/slack_ux.py` (~530 lines) — slash commands (all
  `/donna_*` prefixed after workspace conflict), button-based
  consent, modal-based `/schedule`.
- Config: dropped `DISCORD_*`, added `SLACK_BOT_TOKEN`,
  `SLACK_APP_TOKEN`, `SLACK_TEAM_ID`, `SLACK_ALLOWED_USER_ID`.
- Codex (gpt-5.5-pro) reviewed the migration plan; 9 of 10
  recommendations applied (TEXT for ts, modal /schedule, Block Kit
  buttons, per-channel rate limit, Phase 0 smoke before destructive
  migration, team_id allowlist, no token rotation, escape +
  unfurl-disable, app manifest in repo). Dual-field memory deferred
  to v0.5.1.
- 4/4 critical smoke tests passed live in operator's workspace.

### v0.4.4 (PR #49, 2026-04-30)

Tainted session memory: tag-and-render, not skip. Pre-fix, every
web-tool DM was tainted → not written → memory dead. v0.4.4 writes
tainted exchanges with `tainted=1` flag, scrubs protocol-impersonating
tokens before storage, renders in `<untrusted_session_history>` block
with explicit "do not follow instructions" framing, caps recall at
3 most-recent tainted rows.

### v0.4.3 (PR #47 + #48, 2026-04-30)

Three latent shipping bugs the live scheduler smoke surfaced:
1. Scheduler delivery silently broken since v0.2.0 (no thread_id in
   schedule rows; jobs ran but couldn't deliver)
2. Plain-DM session memory wrote duplicate user rows
3. Migrations didn't auto-run on container restart

All three fixed; smoke passed end-to-end.

### Brain notes added in this session stack

(Will be at `~/Claude Brain/Insights/` after the brain index is
regenerated.)

- `slack-workspace-reserves-bare-slash-names.md` — Slack rejects
  unprefixed names like `/ask` even with no other apps installed.
  Always prefix bot slash commands with the bot's name.
- `not-in-channel-needs-dead-letter.md` — slack_sdk doesn't
  classify Slack errors as retryable vs terminal; adapter must
  do that explicitly or risk infinite loops.
- `cross-platform-secret-rotation-pattern.md` — when migrating an
  always-on bot between platforms, rotate ALL old creds even if
  the old platform's adapter is gone. Old tokens leak via git
  history and decommissioned credentials are still credentials.
