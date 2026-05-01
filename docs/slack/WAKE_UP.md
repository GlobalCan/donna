# Good morning. Here's where we are.

You said "build as much as you can overnight." I built the whole thing
(Phases 1–6 of the v0.5.0 plan). v0.4.4 is still live in prod on Discord;
v0.5.0-rc1 is staged in PR #50 awaiting your review.

## What's done

| | |
|---|---|
| **PR [#50](https://github.com/GlobalCan/donna/pull/50)** | v0.5.0-rc1 Slack adapter retool — Open, CI green, ready to merge |
| **Branch** | `feat/slack-v0.5` |
| **Tests** | 373 / 373 pass · ruff clean |
| **Codex review corrections** | 9 of 10 applied; dual-field memory deferred to v0.5.1 per Codex's ship plan |
| **Phase 0 primitive smoke** | Already passed live in your Slack workspace last night |
| **Discord adapter** | Deleted from the branch. Revival point: git tag `legacy/v0.4.4-discord` |
| **Live full-adapter smoke** | Pending — needs you to run on your Slack post-deploy |

## What changed

Schema migration `0008_slack_schema_cleanup` — renames `discord_*`
columns to platform-agnostic, changes posted_*_id from INTEGER to TEXT
(Slack `ts` is a string), adds `target_channel_id` + `target_thread_ts`
to schedules, wipes Discord-bound rows. **Forward-only** — no downgrade.

Adapter rewrite: `adapter/discord_adapter.py` + `adapter/discord_ux.py`
(~1100 lines, deleted) → `adapter/slack_adapter.py` (~370 lines,
Socket Mode, Block Kit, per-channel rate limit, untrusted-text
escaping, unfurl disable, allowlist) + `adapter/slack_ux.py`
(~530 lines, slash commands, button-based consent, modal-based
`/schedule`, message + app_mention intake).

Settings: `DISCORD_*` removed; `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`,
`SLACK_TEAM_ID`, `SLACK_ALLOWED_USER_ID` added.

UX wins from Slack:
- **Channel-target scheduling** — `/schedule` modal has a channel selector. Daily brief routes to `#morning-brief`, not your DM.
- **Modal `/schedule`** — structured fields (cron, task, channel, mode) replace Slack's bad raw-text slash arg parsing.
- **Block Kit consent** — ✅/❌ buttons on the consent card. Click → handler acks within 3s → `chat.update` removes buttons + shows resolution. Slacker than Discord's reaction model.
- **`@donna` in channels** — in-thread replies keep the channel clean.

## Decision points for you

### 1. Review the PR

[donna#50](https://github.com/GlobalCan/donna/pull/50). The diff is large (~28 files, ~2200 net lines added). The CHANGELOG entry is comprehensive — read that first to get the shape.

### 2. Merge or hold?

If you want to live-smoke before promoting to main: don't merge yet.
You can deploy from the branch directly to a test env, or just code-review and merge if it looks right.

If you trust the test suite + Codex's design review + Phase 0
primitive smoke (already passed in your workspace): squash-merge,
tag rc1, deploy.

### 3. Live smoke after deploy

Run these in Slack to validate the full adapter end-to-end:

| Test | What to do | Expected |
|---|---|---|
| DM | Type "hello" in DM with Donna | "Job queued" + then a real reply |
| `/ask` | `/ask author_twain: walk through Huck's moral arc` | Grounded reply with citations |
| `/schedule` (modal) | Type `/schedule`, fill in cron + task + channel selector + mode, Submit | "Scheduled sched_xxx" confirmation |
| Channel-target schedule | Wait ~1 min for the every-minute schedule to fire | Reply lands in the channel you picked, NOT your DM |
| `@donna` mention | Invite Donna to a channel, type `@donna what's the weather?` | In-thread reply (not channel pollution) |
| Consent button flow | Force a consent gate (`/ask` triggering a tainted tool) | ✅/❌ buttons render; click ✅ → handler acks + `chat.update` removes buttons |

## What's NOT in this PR (deferred)

- **v0.5.1: dual-field memory** (raw_content + safe_summary). Per
  Codex's recommended ship plan — bundling with platform migration
  would make regressions impossible to diagnose.
- **Phoenix observability re-enable**. Still on Jaeger; Phoenix
  upstream image is still broken.
- **Off-droplet backup automation**. DO snapshots + droplet cron +
  laptop OneDrive remain the three layers.

## If something breaks

Two recovery paths:

1. **Revert merge**: `git revert <merge-sha>` on main. v0.4.4 Discord
   still works because it's still tagged. CI builds new image, deploy.

2. **Revive Discord from scratch**: branch from `legacy/v0.4.4-discord`,
   undo migration 0008 manually if needed (the migration is forward-
   only by design — the schema rename is reversible by you, though).
   This is the "Slack is permanently broken" path, not the "Slack has
   a small bug" path.

## Token / context budget

I burned ~250k tokens on the build (estimated ~115-170k upfront; some
unexpected ruff/test fixes pushed it higher). Still well within the
1M context window — no compaction occurred. The full conversation
transcript should be intact when you read this.

If you want to keep iterating in this session: there's plenty of
budget. If you want to compact and start fresh, this doc + PR #50 +
the CHANGELOG entry are enough to resume cleanly.

## My recommendation when you wake up

1. Read PR #50 description (5 min)
2. Skim the CHANGELOG [0.5.0-rc1] entry (5 min)
3. Merge → CI builds → deploy → live smoke (~20 min)
4. If green: tag v0.5.0 final, write release notes, ship
5. If red: triage with me — most likely surface area is event payload
   shapes, modal field names, or rate limiting

Or, if you'd rather I do that step-by-step with you holding the
remote: just say "go" and I'll take you through merge → deploy → smoke.
