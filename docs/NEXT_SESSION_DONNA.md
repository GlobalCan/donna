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

## State snapshot (as of 2026-04-30 end-of-session)

- **Branch:** `main`. Open PR `claude/v042-deploy-prep` (docs sync only)
  pending merge — squash + tag v0.4.2 right after.
- **Version:** `v0.4.2` (Bundle 1 — "feels like she works" production
  fixes) — supersedes v0.4.1 (cross-vendor review action queue items
  #1, #2, #7, #9, #11, #12, #13, #15) and v0.4.0 (unified mode delivery).
- **Tests:** **359 passing**, Python 3.14 local / 3.12 CI, ruff clean.
  Migrations head: `0005_outbox_tables`. No new schema since v0.4.0.
- **Production droplet:** `159.203.34.165`, containers up, Huck Finn
  corpus (402 chunks) loaded.
- **Operator's pending action:** smoke-test the scheduler live per
  `docs/SCHEDULER_SMOKE_TEST.md` after deploying v0.4.2. Then decide
  what's next (see "What's queued" below).
- **What shipped in v0.4.2 (Bundle 1, 2026-04-30):**
  - Mobile-friendly Discord rendering (1400-char chunks +
    `_normalize_for_mobile` collapse runs of blank lines, strip
    trailing whitespace, tabs → 2 spaces; inline path only)
  - Session memory in chat mode (`messages` table now written on
    `JobContext.finalize` + read into `compose_system` via new
    `session_history` kwarg; tainted jobs stripped to preserve trust
    boundary)
  - Scheduler discoverability (`/schedule` shows next-fire-time +
    task preview; `/schedules` shows count + last-fired-at; new
    `docs/SCHEDULER_SMOKE_TEST.md` runbook)
  - `send_update` policy spec drift resolved (PLAN.md updated to
    match the audit-flag-only design that the code already had)
- **What shipped in v0.4.1 (cross-vendor review fixes, 2026-04-30):**
  PR #37 (internal retrieval taint), #38 (eval ratchet), #39 (work_id
  propagation), #40 (stale-worker FAILED-write owner guard +
  attachment temp-file race), #41 (audit denied tool calls),
  #42 (sanitizer cost attribution), #43 (CI ruff cleanup),
  #44 (release notes consolidation).

## Read in this order, before writing any code

1. `README.md` — current status section tells you what shipped (v0.4.2)
2. `CHANGELOG.md` `[0.4.2]` and `[0.4.1]` sections — what just shipped
3. `docs/SESSION_RESUME.md` — full context snapshot
4. `docs/REVIEW_SYNTHESIS_v0.4.0.md` — three-reviewer synthesis + the
   19-item action queue with shipped vs deferred status. **The right
   place to start when picking what's next.**
5. `docs/KNOWN_ISSUES.md` — what's deferred vs what's shipped
6. `docs/PLAN.md` — the original architectural plan (mostly historical
   at this point — search for "send_update" to see the v0.4.2
   spec-drift fix)
7. `docs/THINK_BRIEF.md` — the sibling project (separate session /
   separate repo `GlobalCan/Think`)

Then confirm orientation by telling the user in one paragraph: what Donna
is, what just shipped (v0.4.2), what's queued (`/validate` is the next
big thing if the operator gives the word), what you recommend working
on first. **Do NOT start coding until the user picks.**

## What's queued NOW (post-v0.4.2, ranked)

The cross-vendor review's 19-item action queue had 8 items shipped in
v0.4.1 + v0.4.2. The remaining 11 are deferred behind explicit operator
decisions. Ranked by the operator's tier system from the `/validate`
walkthrough:

### Tier 1 — actual product (do these next when the operator says go)

1. **`/validate <url>` URL critique mode** (~3-4 days). New
   `JobMode.VALIDATE`. Reuses fetch_url + sanitize_untrusted +
   grounded retrieval + overflow-to-artifact. Output: structured per-
   claim verdicts with quoted_span evidence + red-flag detection +
   cross-corpus + web-source verification. Operator's words: "the
   actual product." Spec discussion in the most recent transcript;
   ready to scope into a design doc the moment the operator says go.
2. **Daily morning briefing** as the first concrete scheduled task
   (~hours, after operator confirms scheduler smoke test passes).

### Tier 2 — assistant-makers (do once `/validate` is shipping)

3. **Read your files: Notion OR Drive connector** (~1 week). Operator
   has both; pick one based on where their docs actually live. New
   per-source ingest pipeline + OAuth wiring + scheduled re-sync.
4. **Persistent web monitoring** (~3 days post-scheduler). Cron +
   diff against last `fetch_url` output + Discord notify on change.

### Tier 3 — heavier (defer)

5. **Send emails / calendar events** — security boundary, the lethal-
   trifecta endpoint. Big trust step.
6. **Long-running research** — mostly tuning of compaction + tool
   budget; not new infrastructure.

### Tier 4 — different products (probably never as a Donna feature)

7. **Voice (STT + TTS)** — different UX altogether
8. **Run YOUR code** — workspace architecture decision (git-clone
   pattern vs attachment vs SSH-back)
9. **Database / spreadsheet access** — niche for a personal bot

### Architecture queue (defer until forced)

10. **`agent_scope` first-class** (#3 from review queue) — until 3+
    corpora exist or THINK starts
11. **Step-level checkpoint/replay/fork** (#5) — until evals demand it
12. **Scheduler leadership lock** (#4) — until multi-worker is real
13. **Bitemporal facts** (#11) — market-driven, not user-driven
14. **Claim objects + span drilldown** (#10) — fold into `/validate`
    when it ships

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

1. **`/validate <url|attachment>`** — user-requested, high leverage.
   Send articles, reels, videos, social posts; Donna extracts claims,
   flags emotional framing / missing context / logical fallacies,
   cross-checks against the user's ingested corpora, returns a
   structured critique. Pipeline: fetch (or `ingest_discord_attachment`
   for uploads, or a new `fetch_video_transcript` tool for reels/videos
   using yt-dlp + Whisper or AssemblyAI) → new `validate` mode handler
   → structured output (claims / verifiability / red flags /
   counter-evidence / follow-ups). Reuses overflow-to-artifact for
   long critiques and the grounded-retrieval path for counter-evidence.
   The one non-trivial add: transcript pipeline for video/reel URLs.
2. **Scheduled morning brief** — `/schedule cron_expr="0 13 * * *"
   task="What's new in AI today?"` and watch it fire tomorrow. The
   scheduler works per tests; never run live.
3. **`/teach` from Discord attachments** — the CLI path is validated
   (402-chunk Huck Finn); the `ingest_discord_attachment` tool exists
   but the `/teach` slash command flow hasn't been exercised.
4. **Second corpus** — ingest a second author (Lewis, Dalio, Taleb)
   via `botctl teach`. Proves the multi-corpus `agent_scope` path works
   end-to-end. Requires source material in a clean text format.
5. **Multi-turn chat state** — today each `/ask` / DM is a fresh chat
   job. A conversation spanning multiple messages with continuity would
   require tracking a `thread_id` → `jobs[]` chain and feeding the
   previous turn's context. The schema already has `threads.id`;
   unclear if adapter wires it.
6. **Author debate with ingested corpora** — e.g. Twain vs Dalio
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
