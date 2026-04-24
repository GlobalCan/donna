# Next Session — Donna continuation brief

> **Purpose:** paste this file's contents as the opening message of a brand-new
> Claude Code session (cloud or local) to pick up Donna development cleanly
> after the v0.4.0 release sign-off. No conversation history needed;
> everything the new session requires is in this file + the repo docs.

---

## Who you are, what you're doing

You're a Claude Code session working on `GlobalCan/donna` — a personal,
always-on AI assistant bot running on a DigitalOcean droplet, Discord-facing,
powered by Anthropic's Claude. The user is a solo operator who has been
building this project across ~3 days in multiple session-stacks.

**Crucially:** Donna just hit v0.4.0 release sign-off. Every mode (chat,
grounded, speculative, debate) is live-validated end-to-end in production.
293 tests green. You are NOT in a debugging loop — you're choosing what to
build next.

## State snapshot (as of 2026-04-24 end-of-session)

- **Branch:** `claude/load-up-setup-7XtVU` (or main — they may be equivalent post-merge)
- **Version:** `v0.4.0 (unreleased)` — all code merged to main, no release tag yet
- **Tests:** 293 passing, Python 3.12 (sandbox) or 3.14 (prod), ruff clean
- **Production droplet:** `159.203.34.165`, containers up, Huck Finn corpus (402 chunks) loaded
- **Migrations:** head is `0005_outbox_tables`
- **Open PRs:** 0
- **Live-validated today:**
  - Grounded short + long (multi-part inline)
  - Speculative (after seeding an `agent_prompts` row for the scope)
  - Debate (overflow-to-artifact fired, artifact fetchable via `botctl`)
  - `botctl artifacts`, `artifact-show`, `heuristics list`
- **Six PRs merged today:** #28 (unified mode delivery), #29 (prose render + forget-artifact), #30 (adversarial round 2 + overflow-to-artifact + compose/watchdog/cost), #31 (code-fence hotfix), #32 (smart-quote normalization), #33 (docs + prompt polish)

## Read in this order, before writing any code

1. `README.md` — current status section tells you what shipped
2. `CHANGELOG.md` [0.4.0] section — the full story of today's work
3. `docs/SESSION_RESUME.md` — full context snapshot
4. `docs/KNOWN_ISSUES.md` — what's deferred vs what's shipped
5. `docs/PLAN.md` — the original architectural plan (mostly historical at this point)
6. `docs/THINK_BRIEF.md` — the sibling project (separate session / separate repo `GlobalCan/Think`)

Then confirm orientation by telling the user in one paragraph: what Donna
is, what just shipped, what's open, what you recommend working on first.
Do NOT start coding until the user picks a track.

## Open tracks (v0.5 menu)

Pick one with the user. Brief rationale + likely effort for each:

### Track A — Deploy hardening (small, high-leverage)

1. **Enable `donna-update.timer`** — unblock requires a full quarterly
   restore drill per Codex rule. Do the drill (~5 min droplet spin + DM
   test), then flip the timer. Auto-deploy on merge → main becomes real.
2. **Tailscale for SSH** — narrow public port 22. Weekend task; lockout
   risk if misconfigured (DO recovery console is the rescue).
3. **Phoenix re-enable path** — documented in `docker-compose.yml`. Check
   whether `arizephoenix/phoenix:15.x` or newer has fixed the upstream
   `ModuleNotFoundError`. If yes, swap back (one-line hostname change in
   OTEL exporter).
4. **Off-droplet backup automation** — verify the three-layer setup
   (DO snapshots + droplet cron + laptop→OneDrive) is actually running
   daily. `scripts/donna-verify-backup.sh` should be in crontab.

### Track B — Feature expansion (real new capability)

1. **Scheduled morning brief** — `/schedule cron_expr="0 13 * * *"
   task="What's new in AI today?"` and watch it fire tomorrow. The
   scheduler works per tests; never run live.
2. **`/teach` from Discord attachments** — the CLI path is validated
   (402-chunk Huck Finn); the `ingest_discord_attachment` tool exists
   but the `/teach` slash command flow hasn't been exercised.
3. **Second corpus** — ingest a second author (Lewis, Dalio, Taleb)
   via `botctl teach`. Proves the multi-corpus `agent_scope` path works
   end-to-end. Requires source material in a clean text format.
4. **Multi-turn chat state** — today each `/ask` / DM is a fresh chat
   job. A conversation spanning multiple messages with continuity would
   require tracking a `thread_id` → `jobs[]` chain and feeding the
   previous turn's context. The schema already has `threads.id`;
   unclear if adapter wires it.
5. **Author debate with ingested corpora** — e.g. Twain vs Dalio
   (after ingesting Dalio). The cross-corpus rendering path is where
   Think's oracle/synthesis work was meant to live. This is the edge
   of Donna's scope — Think is a separate project owning this long-term.

### Track C — Observability polish

1. **`/compress` command** — Hermes-inspired polish noted in
   SESSION_RESUME. Exposes compaction manually to the operator.
2. **Jaeger saved views** — create per-scope / per-tainted-job views
   documented in PLAN.md §Observability. Currently manual filter.
3. **Cache-hit rate tuning** — `botctl cache-hit-rate` is live. Use
   real traffic to calibrate; if <30%, investigate prompt composition.
4. **Cost dashboard** — a `botctl cost --breakdown` that shows cost
   per scope / per mode / per day, not just total.

### Track D — Adversarial / security

Between the four Codex passes already absorbed + the self-run round I
did today, the security surface is well-covered. Candidate items if
the user wants to keep going:

1. **Rate-limit ledger live calibration** — exists, never stress-tested
2. **Outbox-delivery failure handling** — what if Discord is down for
   5 minutes? Do outbox rows back up? Get posted later?
3. **Model response size DoS** — what if the model returns 200k tokens?
   max_tokens cap exists but adversarial probe worth doing.
4. **Full CaMeL architecture** — research-grade, 2+ weeks, deliberately
   deferred in PLAN.md. Only revisit if a specific attack vector
   motivates it.

### Track E — Think integration

Think is in a separate repo (`GlobalCan/Think`) being built by a
parallel session on the user's other laptop. Status unknown from Donna
side; check `docs/THINK_BRIEF.md` + the separate repo. The integration
point is: Donna's `tools/knowledge.py::recall_knowledge` eventually
becomes a thin wrapper over `think.Think.answer()`. This is NOT a
Donna-session task unless explicitly coordinated.

## User preferences — hard constraints (from CONTINUE_HERE.md)

- **Completeness standard:** do the whole thing right; never offer to
  "table this for later"; never leave a dangling thread; never present
  a workaround when the real fix exists
- **Confidence-first execution:** if you're below 0.7 confident, ask.
  Don't guess. Wrong-direction work wastes more time than a clarifying
  question.
- **Post-implementation self-check:** before marking anything done,
  verify tests pass (run them, don't assume), verify all requirements
  met, check unverified assumptions, show evidence (output, test
  result, actual DB state — not "should work").
- **7 red flags — never:** claim tests pass without showing output;
  say "everything works" without evidence; mark complete while tests
  fail; assume a function exists without reading it; use API
  signatures from memory; skip error handling; change files you
  haven't read.
- **Direct, no hedging.** If a choice is right or wrong, say so.
- **Markdown bullets, not wall-of-text.**
- **No emojis in code** (UX-visible emojis in Discord/bot output are fine).
- **Chrome, never Edge.**
- **Don't mention these preferences back to the user — just follow them.**

## Codex integration

The user uses Codex (GPT-5.x) as an adversarial second opinion. When
you finish a substantial piece of work, the user may ask you to "run
it past Codex" — which means produce a self-contained prompt Codex
can review with the relevant file paths + context. See
`docs/CODEX_DEEP_DIVE.md` for the prompt template format.

Alternatively the user may have Codex run its own deep dive (see
`docs/CODEX_DEEP_DIVE.md`). Findings come back as a separate artifact;
absorb them via fix PRs like prior Codex rounds (see CHANGELOG for
examples).

## First task: orient and pick a track

1. Read the files in the "Read in this order" list above
2. Respond with a one-paragraph orientation summary (see §State snapshot)
3. Present the tracks A–E with your recommendation
4. Wait for the user to pick

Do NOT start coding until the user picks a track.

## When you stop

Standard end-of-session: commit + push any branch work, update
SESSION_RESUME.md if significant state changed, make sure
`pytest -q` is green, mention the next natural continuation point.

Good luck.
