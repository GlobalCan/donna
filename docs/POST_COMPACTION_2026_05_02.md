# Post-compaction bootstrap — Donna 2026-05-02 (v0.6.1 shipped)

> **Use this if:** the conversation was just compacted (auto or manual)
> or you're a fresh Claude Code session continuing work on Donna at the
> v0.6.1 state. Paste the prompt below as your first message. v0.6.1
> shipped the ops-consolidation bundle (8 numbered items + V50-2/V50-3
> live validations + 2 deploy hotfixes); production is live and healthy.

---

## The prompt to paste

```
Hi Claude. Continuing work on Donna at v0.6.1. Today (2026-05-02)
shipped:

- v0.5.1 → v0.5.2 → v0.6.0 → v0.6.0-hotfix → v0.6.1
  Five releases. The v0.6 ops-consolidation bundle Codex called for is
  done. Production is live, bot healthy, worker up, schema at 0011.

Step 1 — Orient

Read in this order before anything else:

1. README.md — status block reads v0.6.1 / 503 tests
2. CHANGELOG.md — [0.6.1] + [0.6.0] entries cover the 8 ops items
   + V50-2/V50-3 live smokes + the two deploy hotfixes
3. docs/SESSION_RESUME.md — v0.6.1 state snapshot
4. docs/KNOWN_ISSUES.md — v0.6 follow-ups + deferred items
   (#9, #10, #11, #15, #16, #17 -> v0.6.1/v0.7)
5. docs/SCHEMA_LIFECYCLE.md — forward-only migration policy + linter
6. docs/RELEASE_SOAK_POLICY.md — 24h soak after platform changes
7. docs/slack/TOKEN_ROTATION_REHEARSAL.md — quarterly dry-run runbook
8. docs/POST_COMPACTION_2026_05_02.md — this file

Confirm orientation in ONE paragraph: what Donna is, where v0.6.1
landed, what's queued (v0.7 product track or v0.6.x cleanup), and
what you need from me to pick the next track. Wait for my answer
before doing anything.

Step 2 — Current state

- main is at v0.6.1. Tag pushed. GitHub release published.
- 0 open PRs.
- ghcr.io/globalcan/donna:latest is v0.6.1 (CMD-SHELL healthcheck +
  slack-doctor app_token kwarg fix).
- Droplet running v0.6.0 + the CMD-SHELL hotfix; v0.6.1's slack-doctor
  fix needs a `docker compose pull bot && up -d bot` to land. Bot
  itself runs fine on either; this only affects the diagnostic
  command.
- All v0.5.0 follow-ups (V50-1 through V50-9) closed:
    * V50-1 (HIGH retry storm) — fixed v0.5.1
    * V50-2 channel-target schedule — live-validated 2026-05-02
    * V50-3 @donna mentions — live-validated 2026-05-02
    * V50-4 to V50-7 — fixed/documented
    * V50-8 dual-field memory — fixed v0.5.2
    * V50-9 secrets push — resolved
- 503 tests green. Ruff clean. Migration linter green on all 11
  migrations.

Step 3 — What's queued

Codex's holistic review (2026-05-01, transcript) recommended this
roadmap:

  v0.6 — ops consolidation                          DONE
  v0.7 — first real product workflow (morning brief recommended)
  v0.8 — external knowledge (Notion / web monitoring)
  v0.9 — multi-vendor runtime (OpenAI adapter)
  v1.0 — specialist-agent foundation

Tier 1 (v0.7 candidates):
- Daily morning briefing — Codex's pick. Smallest visible product
  win + exercises every v0.6 piece (scheduler, channel-target,
  async runner, cost guards, retention). ~2-3 days.
- /validate <url> — URL-bounded grounded critique. Net-new product
  surface. ~3-4 days.
- JobContext extraction (#16 deferred from v0.6) — split into
  JobLifecycleService / OutboxService / ToolStepService façades.
  Pure refactor; ~2 days. Pairs naturally with adding a connector
  (v0.8) since the new service boundaries make extension easier.

Tier 2 (deferred from v0.6):
- #9 prompt-version-compat at resume
- #10 eval realism (poisoned-corpora goldens)
- #11 operator fatigue (consent batching + alert digest)
- #15 cost timing (sanitizer attribution after DONE; cosmetic)
- #14 speculative/debate live smoke (operator-driven)
- #17 auto-update timer (needs restore drill first)

BLOCKED:
- Restore drill (needs operator $0.20 throwaway DO droplet approval)

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
- Codex (gpt-5.5 default via subscription, gpt-5.5-pro fallback for
  big prompts via API mode) is wired in. Use `codex exec` directly
  via Bash for second opinions. ALWAYS embed content inline in the
  prompt (never let Codex grep — costs run away).
- DON'T paste tokens or secrets into chat. Operator did this once
  during v0.5.0 smoke and we had to rotate via the documented
  TOKEN_ROTATION runbook.
- Slack MCP is wired into Claude Code. #donna-test channel
  (C0B11JP55J7) is the smoke surface; Donna's bot user is U0B121DBTCJ;
  operator's user is U05U55BHQ5A.

Step 5 — Live state on the droplet

Last verified 2026-05-02:
- All 3 containers Up: bot (healthy), worker, jaeger
- alembic_version = 0011
- Migration race fixed (only bot runs alembic; worker waits on
  bot's healthcheck via depends_on)
- V50-3 @donna mention validated end-to-end (~6s response)
- V50-2 channel-target schedule validated (#donna-test received
  SCHED_OK on schedule fire)
- slack-doctor passes auth.test, scopes, channel listing — Socket
  Mode check is the v0.6.1 fix (operator hasn't redeployed yet to
  pick that up)

Step 6 — What NOT to do

- Don't start v0.7 product work without explicit go.
- Don't open speculative new branches before operator picks a track.
- Don't re-rebase or re-merge already-merged PRs.
- Don't refactor the v0.6 modules unprompted — they just shipped.
- Don't modify the entrypoint or compose without expecting another
  deploy hotfix; both are live-tested in this exact configuration
  and changes need careful staging.

Step 7 — Suggested first move

Once you've confirmed orientation, ask the operator:

  1. Has anything new surfaced in production since v0.6.1 deploy?
  2. Track choice: v0.7 morning brief (Codex's pick), /validate,
     or JobContext extraction (v0.6.2 cleanup before product)?
  3. Restore drill — ready to approve the $0.20 throwaway droplet?

Then we'll pick what comes next.
```

---

## Reference: what shipped this session

For context (do not paste this section to the new session — the
prompt above is self-sufficient):

### v0.6.0 (PR #53, 2026-05-02)

8 numbered ops items + V50-2/V50-3 live validations:

1. Entrypoint race fix (only bot runs alembic; worker waits via
   depends_on healthcheck)
2. Supervised async pattern (`async_tasks` + `AsyncTaskRunner`;
   replaces fire-and-forget for safe_summary backfill)
3. botctl dead-letter list/show/retry/discard + async-tasks list/show
4. botctl slack-doctor (token + scopes + Socket Mode + delivery probe)
5. Retention policy + auto-purge for traces/dead_letter/tool_calls/
   async_tasks/jobs
6. Schema lifecycle policy doc + migration linter
7. Cost runaway guards (daily/weekly hard caps + intake refusal)
8. Integration spine — 4 tests against the seams that broke before

V50-2 (channel-target schedule) + V50-3 (@donna mentions) live-
validated in #donna-test.

### v0.6.0 hotfix (PR #54, 2026-05-02)

Bot healthcheck used bare `["CMD", "test", ...]` — `/usr/bin/test`
doesn't ship in `python:3.14-slim`. Healthcheck failed forever,
worker waited forever. Fix: `["CMD-SHELL", "test -f ..."]` invokes
through `/bin/sh` builtin.

### v0.6.1 (PR #55, 2026-05-02)

slack_sdk requires `app_token=` kwarg to `apps.connections.open()`
even with `WebClient(token=app_token)`. Pre-fix slack-doctor crashed
with TypeError mid-run. Fix: pass kwarg explicitly + generic
Exception catch around the call.

### Brain notes added this session

(In `~/Claude Brain/Insights/`.)

- `docker-compose-healthcheck-cmd-vs-cmd-shell.md` — slim images
  don't ship coreutils' `test` binary; use CMD-SHELL form.
- `slack-sdk-apps-connections-open-requires-app-token-kwarg.md` —
  apps.* methods enforce explicit token pass-through.
- `multi-process-alembic-race-on-startup.md` — Docker compose's
  parallel start vs alembic's multi-step DDL = partial-state
  restart loops. Use depends_on healthcheck to serialize.
