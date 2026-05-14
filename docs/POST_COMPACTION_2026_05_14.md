# Post-compaction bootstrap — Donna 2026-05-14 (frozen at v0.7.3, Path 3 in progress)

> **Use this if:** the conversation was just compacted (auto or manual),
> or you're a fresh Claude Code session continuing work on the Donna
> repo. Paste the prompt below as your first message.
>
> **The one thing that matters most:** Donna is FROZEN. The project
> pivoted from "evolve Donna" to "build a greenfield system on P920,
> retire Donna per-capability." A fresh session's instinct is to
> improve Donna — that instinct is wrong now. Read the prompt.

---

## The prompt to paste

```
Hi Claude. Continuing work on Donna at C:\dev\donna (repo
GlobalCan/donna). Context was just compacted. The single most
important thing to internalize before doing anything:

DONNA IS FROZEN at v0.7.3. The project has pivoted. You are NOT
here to improve Donna. Read Step 1 before touching anything.

Step 1 — Orient (read in this order)

1. README.md — product identity, v0.7.3 / 639 tests status
2. CHANGELOG.md — [Unreleased] section spans PRs #64-#67 (the
   Path 3 governance work); [0.7.3] is the last functional release
3. docs/SESSION_RESUME.md — §1 "Where we are" is the Path 3 frame.
   Read this fully; it's the master orientation doc.
4. docs/PATH_3_INVARIANTS.md — v0.3.2, THE spec for the new system.
   Codex-approved across 5 review rounds. 23 numbered-invariant
   sections. §23 governs how it changes.
5. docs/PHASE_1_ARCHITECTURE.md — v1.0.1, the tooling lock for the
   Phase 1 build (Python control plane, TS PWA, Postgres 18, WSL2
   host on P920, etc.). Governed OUTSIDE §23 — it's tooling.
6. docs/RESTORE_DRILL.md — the Phase 0 gate runbook
7. scripts/donna-freeze.sh + scripts/donna-restore-drill.sh — the
   two Phase 0 enforcement artifacts

Confirm orientation in ONE paragraph: what Donna is, what Path 3
is, why Donna is frozen, what the Phase 0 gate is, and what you'd
need from me to do anything. Then WAIT for my answer.

Step 2 — Current state (2026-05-14)

- Donna FROZEN at v0.7.3. Deployed to the DO droplet 2026-05-05,
  running clean. #donna-test quiet since 2026-05-03, no incidents.
- Strategic pivot (Path 3): stop evolving Donna. Build a greenfield
  personal-AI system on the operator's P920 workstation. Retire
  Donna per-capability as the new system absorbs each. Donna stays
  running on the droplet as the bridge until decommission.
- main @ c703303 — clean working tree, in sync with origin, 0 open
  PRs. Local branches: main + feat/slack-v0.5 (one intentional WIP
  remnant; everything else cleaned up). 0 worktrees.
- Tags through v0.7.3. The Path 3 PRs (#64-#67) are docs/ops-tooling,
  not releases — no tags, no droplet redeploy needed.
- Freeze hook: commit-msg hook rejects anything not prefixed
  fix:/chore:/docs:/security:. Installed on THIS checkout. 19/19
  hook tests pass.

Step 3 — The Phase 0 gate (BLOCKS all Phase 1 work — 3 OPERATOR
actions, none are yours to do)

1. bash scripts/install-freeze-hook.sh  — on my checkout
2. Run the restore drill: export DRILL_DO_TOKEN=... then
   bash scripts/donna-restore-drill.sh  (~$0.01, ~20 min;
   de-risked by PR #67's PEP 668 fix but never yet executed)
3. systemctl enable --now donna-update.timer  — on the droplet,
   post-drill

Until all 3 clear, Phase 1 spine work on P920 does NOT start.

Step 4 — Operator preferences (hard constraints)

- Direct, no hedging. Completeness standard — ship the whole thing,
  no "table this for later." Confidence-first: below 0.7 confident,
  ask.
- No emojis in code. Markdown bullets + tables > wall-of-text.
- Strong engineer — explain mechanisms, skip basics.
- Security-first, solo-forever. No multi-tenant / SaaS / enterprise.
- Branch + PR for non-trivial changes. Trivial doc edits can go
  direct to main. Always: gh --repo GlobalCan/donna explicitly.
- Codex (real GPT-5.5 via `codex exec` directly in Bash — NOT the
  rescue subagent) for second opinions. ALWAYS embed content inline
  in the prompt; never let Codex grep (cost runaway).
- §23 governance: any change to a NUMBERED invariant in
  PATH_3_INVARIANTS requires a Codex review + sign-off pass. This
  has been exercised 5 times; the procedure works. Honor it.
- Don't paste tokens/secrets in chat.
- Slack MCP is wired: #donna-test = C0B11JP55J7, Donna bot user
  U0B121DBTCJ, operator user U05U55BHQ5A.

Step 5 — What NOT to do

- Do NOT add features to Donna. The freeze hook will reject the
  commit, but more importantly: it's the wrong direction. Donna is
  in maintenance-only mode.
- Do NOT scaffold Phase 1 / the new P920 system before the Phase 0
  gate clears. That bypasses the exact discipline the operator and
  Codex agreed on (prove you can recover the old thing before
  building the new). The new system also lives in a SEPARATE repo
  that doesn't exist yet — not inside donna/.
- Do NOT change a numbered PATH_3_INVARIANTS invariant without
  routing it through Codex per §23.
- Do NOT re-create the deleted branches/worktrees. The repo was
  deliberately cleaned to main + feat/slack-v0.5.
- Do NOT redeploy the droplet for the #64-#67 work — it's docs/ops
  tooling, no runtime change.

Step 6 — Suggested first move

After you confirm orientation, ask me:
1. Have any of the 3 Phase 0 gate items been done since 2026-05-14?
2. If the gate is clear: ready to start Phase 1 spine work? (That's
   a new repo — confirm the repo name from PHASE_1_ARCHITECTURE §8,
   "spine" or "sovereign" were the candidates.)
3. If the gate is NOT clear: is there anything autonomous and
   freeze-legal I should do (drill script hardening, doc currency,
   PATH_3 v0.4 prep), or do you just need the gate-clearance
   walkthrough?

Then we pick the next move.
```

---

## Reference: what happened since the last post-compaction doc

For context (do not paste this section — the prompt above is
self-sufficient):

### The pivot (2026-05-08 → 2026-05-09)

Three planning-session iterations (pre-audit / security audit /
decision review) produced **Path 3**: stop evolving Donna, build a
greenfield personal-AI system on the P920 workstation, retire Donna
per-capability. Chosen over Path 1 (evolve in place) and Path 2
(freeze + build alongside). Codex's framing landed hard: "Donna's
maturity is evidence of discipline, not evidence it's the right
substrate for the target system."

### PRs shipped this span (#64 → #67)

- **#64** — PATH_3_INVARIANTS v0.2 + freeze hook + restore drill.
  The freeze hook (`scripts/donna-freeze.sh`) puts Donna in
  maintenance-only mode. The restore drill (`scripts/donna-restore-drill.sh`)
  is the Phase 0 gate.
- **#65** — PATH_3_INVARIANTS v0.3. Donna's strategic-briefing
  pushback absorbed (5 §8.x clarifications + 8 nits). Codex-approved
  across 3 review rounds — caught a real CO-6 split-brain race that
  took 2 rounds to fully close (fail-closed Phase 2+ was the fix).
- **#66** — PATH_3_INVARIANTS v0.3.2 + PHASE_1_ARCHITECTURE v1.0.1.
  Codex ratification caught a blocking SC-5 conflict (`pip-tools` vs
  `uv`) — SC-5 amended to a tool-neutral hash-pinning invariant.
  Four advisory tightenings absorbed (Ollama loopback, Pushover
  payloads, OAuth secret_taint, GPU passthrough split).
- **#67** — restore drill correctness fix. Logic review of the
  never-executed drill caught a PEP 668 blocker (system `pip3
  install` fails on Ubuntu 24.04), a dead docker dependency, and a
  header overclaim. All fixed before the operator's first run.

### Repo hygiene (2026-05-14)

- CHANGELOG + SESSION_RESUME brought current through PR #67.
- 3 locked agent worktrees removed.
- 35 stale local branches deleted (4 git-verified-merged + 31
  verified against shipped tags / merged PR numbers). All
  reflog-recoverable ~90 days.
- Repo deliberately cleaned to `main` + `feat/slack-v0.5` (the one
  paused WIP branch that couldn't be cleanly verified as merged —
  kept on purpose).

### §23 governance — exercised, works

PATH_3_INVARIANTS numbered-invariant changes require a Codex
review + sign-off pass. Exercised 5 times across v0.3 → v0.3.2.
Every round caught something real (split-brain races, tool-vs-
invariant conflicts, audit-log drift). The procedure is not
ceremonial — keep honoring it.
