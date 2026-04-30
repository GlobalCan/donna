# Post-compaction bootstrap — Donna 2026-04-30

> **Use this if:** the conversation has just been compacted (auto or
> manual), or you're a fresh Claude Code session continuing work on
> Donna at the v0.4.2 state. Paste the prompt below as your first
> message. Updated 2026-04-30 after Bundle 1 shipped + operator paused
> to deploy.
>
> **Don't use this for:** a brand-new laptop bootstrap (use
> `docs/CONTINUE_HERE.md` instead). This doc assumes the operator and
> the prior session were mid-thread and you're picking up where it
> stopped.

---

## The prompt to paste

```
Hi Claude. Continuing work on Donna at v0.4.2. The prior session shipped
two coordinated releases today (v0.4.1 cross-vendor review action items
+ v0.4.2 "feels like she works" Bundle 1) and paused so I could deploy
the new image to the production droplet and smoke-test the scheduler
live. We're picking back up after my deploy.

Step 1 — Orient

Read in this order before anything else:

1. README.md — status block now reads v0.4.2 / 359 tests. Confirms
   shipped state.
2. CHANGELOG.md — [0.4.2] (Bundle 1) and [0.4.1] (cross-vendor review
   fixes) sections cover everything that landed today.
3. docs/SESSION_RESUME.md — full state snapshot at v0.4.2.
4. docs/REVIEW_SYNTHESIS_v0.4.0.md — the three-reviewer synthesis +
   19-item action queue. The status of each item (shipped vs deferred)
   is the right map for picking what's next.
5. docs/NEXT_SESSION_DONNA.md — current "what's queued NOW" section
   has the operator's tier-ranked priorities post-v0.4.2.
6. docs/SCHEDULER_SMOKE_TEST.md — the runbook the operator was about
   to execute. Status of that test (passed / not run / failed) is a
   key first thing to ask me about.
7. docs/POST_COMPACTION_2026_04_30.md — this file you're reading.

Confirm orientation in ONE paragraph: what Donna is, where v0.4.2
landed, what's queued (the next big thing is /validate URL critique
mode if I give the word — don't start it without me), and what you
need from me to pick the next track. Wait for my answer before doing
anything.

Step 2 — Current state

- main is at the v0.4.2 release. Tag pushed, GitHub release published.
- 0 open PRs as of session start. (If you started a PR while I was
  away, surface it in your orientation summary.)
- Image ghcr.io/globalcan/donna:latest was rebuilt automatically when
  the v0.4.2 PR squashed onto main. Operator was deploying via
  docker compose pull && up -d on the droplet.
- Scheduler smoke test was the operator's homework. Status of that
  test is a key piece of information for picking the next track.
- 8 of 19 cross-vendor review action items shipped. The remaining 11
  are deferred behind explicit operator design decisions
  (REVIEW_SYNTHESIS_v0.4.0.md §5 + KNOWN_ISSUES.md "Action queue").

Step 3 — What's queued NOW

The operator and I worked through tier ranking before the pause:

Tier 1 (do next when operator says go):
  - /validate <url> URL critique mode — ~3-4 days. New JobMode.VALIDATE
    reusing fetch_url + sanitize_untrusted + grounded retrieval +
    overflow-to-artifact. We have a concise spec already discussed in
    the prior turn — operator paused before signing off on the design
    doc. Do NOT start coding /validate without explicit go-ahead.
  - Daily morning briefing as the first concrete scheduled task —
    after operator confirms scheduler smoke test passes.

Tier 2 (assistant-makers, after /validate ships):
  - Notion OR Drive connector — operator picks based on where their
    docs live.
  - Persistent web monitoring — cron + diff + notify, builds on
    confirmed scheduler.

Tier 3+ (defer): emails / calendar / voice / run-your-code / databases
+ architecture work (agent_scope first-class, scheduler leadership,
step-level state, bitemporal facts).

Step 4 — Operator preferences (hard constraints)

- Direct, no hedging. If you think a choice is right or wrong, say so.
- Completeness standard: never present a workaround when the real fix
  exists; never offer to "table this for later."
- Confidence-first: if below 0.7 confident, ask. Wrong-direction work
  wastes more time than a clarifying question.
- Post-implementation self-check: before marking done, run tests +
  show output, not "should work."
- No emojis in code. Fine in Discord/UX output.
- Markdown bullets + tables > wall-of-text.
- Strong engineer: explain mechanisms, skip basics.
- Security-first, solo-forever: no multi-tenant / SaaS / enterprise.
- Don't push to main directly. Branch + PR for everything except
  trivial doc edits.
- Use gh CLI for GitHub (the GitHub MCP isn't loaded in this session).
  Always pass --repo GlobalCan/donna explicitly.
- Codex (GPT-5.4 / GPT-5.5 / GPT-5.5-pro / GPT-5.3-codex) is wired in
  API mode now via OPENAI_API_KEY in HKCU:\Environment. Default model
  is gpt-5.5-pro per the operator's "always use the best possible
  model" directive. For full deep-dive prompts (~30k tokens) gpt-5.5-pro
  exceeds quota — fall back to gpt-5.3-codex which completed cleanly.
  See ~/.claude/CLAUDE.md "Codex Collaboration" section for the full
  matrix.

Step 5 — What NOT to do

- Don't start /validate without explicit go-ahead. The spec was
  agreed in the prior turn; operator wanted to deploy + smoke-test
  the scheduler first.
- Don't open speculative new branches before the operator picks a track.
- Don't re-rebase or re-merge already-merged PRs.
- Don't refactor the existing scheduler or session-memory wiring —
  Bundle 1 just shipped and is being smoke-tested.

Suggested first move

Once you've confirmed orientation, ask me:

  1. Did the scheduler smoke test pass on the droplet?
  2. Is the bot answering with session memory (does it remember the
     last /ask in the same DM)?
  3. Mobile rendering — better, worse, or same?
  4. Any new production issues from deploy?

Then we'll pick what comes next. Most likely path: /validate URL mode
becomes the v0.5 work. But I might surface something else from the
deploy that pre-empts it.
```

---

## Reference: what shipped between this session and the prior pause

For your context (do not paste this section to the new session — the
prompt above is self-sufficient):

### v0.4.1 (PR #37–#44, 2026-04-30 morning)

Cross-vendor review action queue, lower-effort items.

- #37 — Internal retrieval taint propagation (CRITICAL — flagged by
  all three reviewers)
- #38 — Eval scaffold → ratchet
- #39 — `work_id` propagation
- #40 — Stale-worker FAILED-write owner guard + attachment temp-file
  race
- #41 — Audit denied/unknown/disallowed tool calls (net-new from
  GPT-5.3-codex)
- #42 — Sanitizer cost attribution
- #43 — Re-apply ruff fix dropped from #37 squash
- #44 — Release notes consolidation

### v0.4.2 (PR #45, 2026-04-30 afternoon)

Bundle 1 — operator-reported production friction.

- Mobile rendering: 1400-char chunks + `_normalize_for_mobile`
- Session memory: `messages` table writes in finalize + reads in
  compose_system
- Scheduler discoverability: `/schedule` + `/schedules` rendering +
  `docs/SCHEDULER_SMOKE_TEST.md` runbook
- `send_update` PLAN spec drift: PLAN.md updated to match code

### Open work the operator paused on

- Smoke-testing the scheduler live on the droplet (operator's homework)
- Designing `/validate` MVP — spec discussed in transcript; design doc
  not yet written; do NOT start coding without sign-off

### Brain notes added in this session

(Will be at `~/Claude Brain/Insights/` after the brain index is
regenerated.)

- `cross-vendor-llm-review-methodology.md` — cross-LLM-family review
  finds what single-family review misses; disagreement between
  reviewers is signal
- `production-feedback-beats-review-passes.md` — operator daily use
  surfaces what no automated review can; mobile UX, "no memory",
  invisible features
