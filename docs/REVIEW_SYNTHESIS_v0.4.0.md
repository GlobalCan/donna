# Review Synthesis — Donna v0.4.0

> Synthesis of three independent passes against HEAD `0149002`:
>
> 1. **Claude (Opus 4.7, 2026-04-24)** — full architectural review against
>    `docs/CODEX_DEEP_DIVE.md`. Captured in
>    [`docs/CODEX_REVIEW_DONNA_v0.4.0.md`](CODEX_REVIEW_DONNA_v0.4.0.md)
>    (filename misleading; corrections inline).
> 2. **Codex (GPT-5.4, 2026-04-29)** — cross-vendor adversarial pass with
>    Claude's findings, the market research synthesis, and the prior
>    verification table fed in as context. Captured in
>    [`docs/CODEX_REVIEW_DONNA_v0.4.0_GPT5.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT5.md).
> 3. **Market research synthesis (2026-04-25)** — landscape report covering
>    60+ products across commercial / OSS / agent frameworks / memory /
>    GraphRAG / persona / security / validation. Branch
>    `claude/donna-market-research-7Drtc` at
>    `research/donna-landscape-2026/REPORT.md`.
>
> A prior session also verified Claude's specific file:line claims; that
> verification stands and was independently confirmed by Codex.
>
> Synthesized 2026-04-29 by the cross-vendor orchestrator session.
> Repo at HEAD `0149002`, 293 tests green.

---

## 0 · Executive summary

The cross-vendor pass was worth running. **Codex found seven concrete
red flags that Claude missed**, the headline being **internal retrieval
bypasses taint policy entirely** — every mode (chat / grounded /
speculative / debate) loads chunk content via `retrieve_knowledge()`
without checking `knowledge_sources.tainted`, while only the tool wrapper
`recall_knowledge()` does. This is the single most actionable security
finding from any of the three passes.

Beyond that, Claude and Codex broadly agree on the architectural
fundamentals (12 of 13 scorecard verdicts match). They diverge on three
items where Codex's framing is stronger: `agent_scope` is **❌ change**,
not **⚠️ reconsider**; compaction is **partial-keep with step-state
guardrails** because debate doesn't checkpoint per turn; the Huck Finn
migration to `think_*` should be **bridge → dual-read → cut over**, not
atomic.

The market report's "five-quadrant persona-stance taxonomy with Donna
in the empty fifth quadrant" turns out to be **aspirational, not
shipped** — Codex confirms grounded mode renders a global footer badge,
not per-claim inline status primitives. That recasts Donna's *current*
defensible niche as "solo-operator, grounded-to-owned-corpora,
security-posture-first with structural citation validation." The
labeled-extrapolation niche is a v0.6+ goal, not present moat.

Two of Claude's specific recommendations are **factually wrong** and
have been struck through in the original review file: subprocess
`run_python` is already shipped, and the eval harness exists as scaffold
(it just isn't a ratchet yet). The correct framing of the eval work is
"turn scaffold into ratchet," not "build harness."

The merged action queue (§4 below) puts internal-retrieval taint at #1,
the eval ratchet at #2, and `agent_scope` first-classing at #3. Numbers
4-7 are split between checkpointing-for-debate, `/validate` URL mode,
`work_id` propagation, and session memory across Discord threads. Items
8-13 are smaller security or quality fixes. **Bitemporal facts** (the
market report's #1 steal) is correctly down-ranked to #10 — important
but not before Donna can measure regressions.

---

## 1 · Where the three passes agree

These are high-confidence findings — both reviewers reached the same
conclusion independently, and the market research backs at least one
side.

### 1.1 Architectural keepers (12 of 13 scorecard items)

Both Claude and Codex score these as **✅ keep**:

- Hand-rolled Anthropic SDK (re-evaluate at v1.0)
- Unified `JobContext` across modes
- Mode dispatch via `if/elif`
- SQLite as single source of truth (with documented single-writer)
- Discord-only with no adapter abstraction
- Outbox pattern (DB-rows-drained-by-poll)
- Quoted-span validator structural, not semantic
- `ModelRuntime` registry (pricing as data)
- Cache-aware prompt composition
- Overflow-to-artifact for tainted content

Two are **⚠️ reconsider** in both reviews:

- Taint as per-job boolean
- (Claude:) `agent_scope` flat string — Codex stronger ❌

One is **agree-but-with-extension** in Codex and **✅ keep** in Claude:

- Compaction-as-summarization with audit artifact — chat path is sound;
  debate path lacks per-turn checkpointing.

### 1.2 Top product moves (rough ranking, both reviews)

- **Eval harness expansion** — both top-3.
- **`agent_scope` first-classing** — both flag, Codex stronger.
- **Session memory across Discord threads** — both flag.
- **`/validate` URL critique only (not video)** — both unanimous.
- **Step-level checkpoint/replay/fork for long modes** — both flag.
- **Grounded chunk caching** — both flag (Codex broadens to all
  retrieval, not just retry).
- **Claim objects / span drilldown for grounded UI** — both flag, market
  report frames as the missing-fifth-quadrant infrastructure.

### 1.3 Verified red flags from Claude's review (all confirmed by Codex spot-check + prior verifier)

| # | Claude red flag | Status |
|---|---|---|
| 8.1 | Two `donna-worker` containers would corrupt state | Confirmed |
| 8.2 | `JobContext.open` silent-return on missing job | Confirmed |
| 8.3 | `_sanitize_hits` stringifies exceptions into snippet | Confirmed |
| 8.4 | Consent timeout silent at 30 min, no Discord message | Confirmed |
| 8.5 | No `threads.conversation_state` (sessionless across jobs) | Confirmed |
| 8.6 | Compaction strands artifact_refs past 20 | Confirmed |
| 8.7 | No rate limit on tainting commands | Confirmed |
| 8.8 | Jaeger in-memory, audit in `traces` SQLite, undocumented | Confirmed |
| 8.9 | No per-job consecutive-error cap | Confirmed |
| 8.10 | `_estimate_tokens` 4-chars/token wrong for JSON/code | Confirmed |

---

## 2 · Where Codex disagrees with Claude

Direct conflicts. In all of these, Codex's framing is supported by
specific file:line evidence.

| § | Topic | Claude | Codex | Resolution |
|---|---|---|---|---|
| §B.1.8 / §B.4.1 | Eval harness | "no eval harness — biggest single omission" | "scaffold exists, isn't a ratchet" | **Codex** — `evals/runner.py:24-49` exists; framing as "missing" is wrong; expansion remains top priority |
| §B.4.2 | `run_python` subprocess isolation | "ship subprocess version" | "already done" | **Codex** — `tools/exec_py.py:39-73` is already subprocess-isolated; recommendation is OBSOLETE |
| §B.2.5 | `agent_scope` flat string | ⚠️ reconsider | ❌ change | **Codex** — already constraining product shape across `memory/prompts.py`, `memory/knowledge.py`, retrieval, validator |
| §B.6.4 | Compaction strategy | "right; watch drift after 3 compactions" | partial — debate doesn't checkpoint per turn | **Codex** — separate concern; both true |
| §B.7.3 | Huck Finn migration to `think_*` | atomic rename + wrapper flip in one PR | bridge → dual-read → cut over | **Codex** — live `knowledge_*` dependency means atomic carries real risk |
| §B.9.8 | Sanitization coverage | "every untrusted ingress path is dual-call sanitized" | overstated — attachment ingest + internal retrieval bypass | **Codex** — `tools/attachments.py:119-137` and `modes/retrieval.py:17-79` are paths Claude missed |

---

## 3 · New findings only Codex surfaced

The headline value of running cross-vendor. Each item has been spot-checked
against current code in this synthesis pass.

### 3.1 Internal retrieval bypasses taint policy entirely (CRITICAL)

`recall_knowledge()` (`tools/knowledge.py:54-87`) propagates `tainted=True`
to the job when `knowledge_sources.tainted=1` is hit. But every mode's
internal `retrieve_knowledge()` call — `agent/loop.py:55-62`,
`modes/grounded.py:73`, `modes/speculative.py:45-55`,
`modes/debate.py:104-111` — bypasses this check entirely. Chunks are
loaded straight into prompt composition; the job never sees the taint.

A future tainted corpus (e.g. a `/validate` artifact promoted to
knowledge by mistake) would silently shape every grounded answer
without firing consent gates on downstream `remember` / `run_python` /
write tools. **Top priority fix.**

### 3.2 Debate mode does not checkpoint transcript incrementally (HIGH)

`modes/debate.py:98-176` runs `for r in range(rounds): for scope in
scopes:` and inside the inner loop calls `ctx.model_step` without any
`ctx.checkpoint_or_raise()` between turns. A worker crash mid-debate
loses every prior turn — exactly the expensive recovery class the
architecture is otherwise designed to avoid. Rough order of magnitude:
a 3-round 3-scope debate is 9 STRONG-tier model calls plus a summary
call; losing 5 of those to a transient crash is real money and real
latency.

### 3.3 Plan/implementation drift on tainted `send_update` (MEDIUM)

`docs/PLAN.md:94,159` mandates that tainted updates require confirmation.
`tools/communicate.py:27-52` shows `send_update` has no `taints_job` flag
and no `confirmation` parameter. `security/taint.py:19-27`'s
`TAINT_ESCALATED_TOOLS` frozenset doesn't include `send_update`. The
tool simply accepts a `tainted: bool` argument and stores it in the
outbox row. The PLAN says one thing; the code does another.

### 3.4 Attachment ingest temp-file race under concurrency (MEDIUM)

`tools/attachments.py:84-86` writes to a fixed path
`tmp_dir / f"attach{ext or '.bin'}"`. Two concurrent ingests with the
same extension overwrite each other before either finishes processing.
Solo bot today only triggers via Discord attachments (rate limit by
human typing speed), so this is latent — but the `/teach` flow could
trip it during a corpus-batch ingest.

### 3.5 Stale worker exception path can clobber job state (MEDIUM)

`Worker._run_one()` (`jobs/runner.py:60-67`) writes `FAILED` without an
owner guard. A stale worker — one whose lease was reclaimed but whose
exception handler still runs — can mark a job FAILED that another worker
has since recovered or completed. Symmetric to the owner-guard fix Codex
landed for `consent._persist_pending` in v0.3.3 (#23); just missed here.

### 3.6 `work_id` propagation broken for default ingests (HIGH for retrieval quality)

`ingest/pipeline.py:48-60` and `:107-120` give the *source* row a
surrogate `work_id`, but the *chunk* rows get `work_id=None`. The
retrieval diversity logic at `modes/retrieval.py:156-171` groups by
`work_id`, so all unrelated NULL-work_id sources collapse into a single
diversity bucket. Effect: when retrieving across mixed corpora, the
diversity heuristic silently fails to spread results across sources.

### 3.7 Sanitizer cost not attributed to jobs (MEDIUM observability)

`security/sanitize.py:35-68` calls `model().generate()` without passing
`job_id` to the cost ledger. Per-job cost in `botctl cost` undercounts
by exactly the sanitizer spend on `fetch_url` / `search_web` /
`ingest_discord_attachment` calls, which can be substantial on a
heavily-tainted day. The `cost_ledger` schema supports `job_id`; it just
isn't wired through.

### 3.8 `checkpoint_state` is opaque JSON, not first-class step state

Codex flagged this as a load-bearing decision that Claude's scorecard
missed. `types.py:60-104` + `memory/jobs.py:84-138`: the entire
checkpoint is a JSON blob serialized from the in-memory `JobState`.
That's why replay/fork/eval drift and mid-debate recovery are all
awkward. Promotion to a first-class step log unblocks each of those
independently.

---

## 4 · Where market research adds context both reviewers underweight

The market report's strongest contribution is *strategic positioning*,
not *bug-finding*. Two specific reframes deserve weight:

### 4.1 Donna's current niche is narrower than the market report initially claims

The five-quadrant persona-extrapolation taxonomy has Donna in the empty
fifth quadrant: "extrapolate-with-structured-per-claim-status-header in
an assistant UI." Codex's spot-check (`modes/grounded.py:148-168`,
`modes/speculative.py:74-80`) confirms this is **aspirational, not
shipped**: grounded mode renders a global footer, speculative renders
a global banner. Per-claim inline status primitives don't exist yet.

That doesn't change the strategic direction — it's still the empty
quadrant — it just changes the framing. Donna's *current* moat is
**structural citation validation** (the `quoted_span` contract), not
labeled extrapolation. The labeled-extrapolation work is a real
v0.6+ initiative, ~M effort, and lands in `modes/grounded.py`,
`modes/speculative.py`, plus a new claim-rendering primitive.

### 4.2 Substrate decision (LangGraph vs hand-roll) is closer than Claude framed it

Claude says "hand-roll one more major version." The market report says
"build on LangGraph v1." Codex's nuance is: hand-rolled remains correct
through v1.0, but the closing window is *not* framework maturity. It's
Donna's own missing first-class state model for scopes/profiles/steps.

Read together: don't migrate to LangGraph for the framework's sake;
fix the schema/state issues first. After that, the question becomes
"do we still need a framework?" and the answer is probably still no —
but the migration cost is then bounded because the state shape is right.

### 4.3 Three concrete steals from the market report worth ranking

- **Bitemporal fact edges** (Graphiti): real but defer; Codex correctly
  ranks this lower than Donna's current taint/eval/scope work
- **MCP hygiene primitives at spawn boundary** (Hermes Agent): worth
  borrowing wholesale when MCP-via-agent goes live; not before
- **schema.org/ClaimReview as canonical claim object**
  (Google Fact Check Tools API): the specific schema to adopt for
  `/validate`'s claim outputs. Both reviewers underweighted this; it's
  free and structurally clean.

### 4.4 Two market-report claims to correct downstream

The original brief that drove the market research had two factual
errors that propagated:

- **"OpenClaw / Nov-2025 / 300+ skills"** is actually **ClawHavoc /
  Jan-Feb 2026 / 341→1184 skills / 346k stars / CVE-2026-22708**.
  Update any docs referencing the original framing.
- **Hermes "Pattern A/B"** terminology is **UNVERIFIED** — no primary
  source uses that naming. It's folk language. Treat as folklore;
  adopt the Hermes MCP-hygiene primitives directly under their own
  names rather than as Patterns A/B.

---

## 5 · Merged action queue (top to bottom)

This is the synthesis output. Each item lists which source(s) flagged it,
rough effort, leverage, risk, and where the work lands. Ordering is the
recommended priority for v0.5+.

| # | Action | Source(s) | Effort | Leverage | Risk | Lands |
|---|---|---|---|---|---|---|
| 1 | **Internal retrieval taint propagation** — taint jobs when retrieved chunk sources are tainted; bring `retrieve_knowledge` to parity with `recall_knowledge` | Codex | M | Very high | Medium | `modes/retrieval.py`, `agent/loop.py:55-62`, `modes/{grounded,speculative,debate}.py` |
| 2 | **Eval scaffold → ratchet** — distinguish SKIP vs PASS for non-`live` cases; add structural assertions (chunk-id validity, schema lint); pin grounded + taint cases | Claude + verification + Codex | S-M | Very high | Low | `evals/runner.py:24-49`, `evals/golden/*` |
| 3 | **`agent_scope` first-class** — replace flat string with `corpora` + `profiles` + prompt/policy attachment (skip minimal `scopes` table per Codex if THINK is imminent) | Claude + market + Codex | M-L | High | Medium | `memory/prompts.py:13-79`, `memory/knowledge.py:18-52`, migrations |
| 4 | **Step-level checkpoint/replay/fork for long modes** — debate especially; promote `checkpoint_state` from JSON blob to first-class step log | Codex | M | High | Medium | `modes/debate.py:98-176`, `types.py:60-104`, `memory/jobs.py:84-138` |
| 5 | **`/validate` URL/article critique only** — new `JobMode.VALIDATE`; reuse `fetch_url` + `sanitize_untrusted` + grounded-retrieval; artifact-first Discord output; defer video to v0.6+ | Claude + market + Codex | M | High | Medium | new mode + `tools/web.py` + adapter + maybe `claims` storage |
| 6 | **`work_id` propagation fix** — populate chunk rows' `work_id` from source row; fix retrieval diversity grouping | Codex | S | High | Low | `ingest/pipeline.py:48-60,107-120`, `modes/retrieval.py:156-171` |
| 7 | **Session memory across Discord threads** — `threads.conversation_state` JSON column with last 4 jobs' final_text + task; inject into volatile prompt block | Claude + Codex | S-M | Medium-high | Low | `threads` schema, `adapter/discord_adapter.py`, `agent/compose.py` |
| 8 | **Sanitizer cost attribution** — pass `job_id` through `sanitize_untrusted` → `model().generate` → `cost_ledger` | Codex | S | Medium | Low | `security/sanitize.py:35-68`, `memory/cost.py:38-72` |
| 9 | **Claim objects + span drilldown for grounded output** — start of the labeled-extrapolation UI; adopt `schema.org/ClaimReview` as wire format | Claude + market + Codex | M | Medium | Medium | `modes/grounded.py:148-168`, new `claims` table, render layer |
| 10 | **Bitemporal facts** — `valid_from` / `valid_until` / `recorded_at` / `invalidated_by` columns; queries gain point-in-time selector | market | M-L | Medium | Medium | `memory/facts.py`, migration `0006_bitemporal_facts.py` |
| 11 | **Stale-worker failure-write owner guard** — symmetric to v0.3.3 #23 | Codex | XS-S | Medium | Low | `jobs/runner.py:60-67`, `memory/jobs.py:141-176` |
| 12 | **Tainted `send_update` policy fix** — either match PLAN's escalation or update PLAN to reflect "tainted=just-a-flag" | Codex + PLAN | XS | Medium | Low | `tools/communicate.py:27-52`, `security/taint.py:19-27` |
| 13 | **Attachment temp-file concurrency** — switch fixed `attach{ext}` to `NamedTemporaryFile` or UUID-suffixed path | Codex | XS | Medium | Low | `tools/attachments.py:82-85` |
| 14 | **Tainted-fact quarantine** — mirror overflow-to-artifact for `remember` of tainted facts; `quarantined_facts` table; `botctl quarantine list/promote` | Claude | XS | Low (defensive) | Low | `tools/memory.py`, new table, `botctl` command |
| 15 | **Streaming response delivery** — Anthropic streaming + Discord edit-in-place; gate to `tainted=False` | Claude | S | Medium (perceived) | Low | `agent/model_adapter.py`, `adapter/discord_adapter.py` |
| 16 | **Jaeger LLM-span custom view** — static HTML over `traces` SQLite; per-job cost, taint propagation chain, retry cycles | Claude | S | Medium | Low | new `docs/observability.html` + `botctl traces` enhancement |
| 17 | **Proactive knowledge surfacing** — weekly cron picks random `knowledge_source`, posts synthesis to Discord | Claude | S | Variable | Low | `jobs/scheduler.py` + new mode hook |

Items 1-9 are the v0.5 recommended menu; 10-17 are v0.6+. The user's
original v0.5 backlog from `docs/NEXT_SESSION_DONNA.md` already had
`/validate` (here #5), session memory (#7), and `donna-update.timer`
(deploy hardening, not on this list because it's an ops decision not a
review finding). Track A items from `NEXT_SESSION_DONNA.md` (Tailscale,
Phoenix re-enable path, off-droplet backup verification) are unchanged
by this synthesis.

---

## 6 · What this means for v0.5 priorities

### 6.1 What changed

- **Internal retrieval taint propagation** is now the highest-priority
  v0.5 item, ahead of `/validate`. Reasoning: `/validate` will *create*
  tainted artifacts; without internal-retrieval taint, those artifacts
  can leak into grounded answers via `retrieve_knowledge` without
  consent escalation. Fix the leak before opening the firehose.
- **Eval ratchet** moves from "we should do this" to "do this before
  any model upgrade." Without it, the next Sonnet 4.7 / Opus 5.0 release
  has no number to move and no regression detection.
- **`agent_scope` first-classing** is now firmly v0.5, not v0.6. Codex's
  ❌-change verdict is the stronger reading; it's already constraining
  product shape across `memory/prompts.py`, `memory/knowledge.py`, and
  retrieval. Fixing this also unblocks the THINK migration's clean
  reading of `corpora` rows.

### 6.2 What didn't change

- `/validate` URL critique remains a v0.5 candidate (now #5 not #1).
- Session memory remains a high-leverage UX win.
- Track A deploy hardening (timer, Tailscale, backups) is unchanged.

### 6.3 What got actively de-prioritized

- **LangGraph migration**: not a v0.5 question. Maybe not a v1.0
  question. The schema/state issues come first; framework choice can
  follow.
- **Bitemporal facts as #1 steal**: market-report framing was too strong;
  defer to v0.6+ once eval ratchet exists to measure regressions.
- **Subprocess `run_python`**: already done; remove from any v0.5 plans
  that copy from PR #36 directly.

### 6.4 What's still aspirational, not present moat

- **Per-claim epistemic-status inline UI** (the empty-fifth-quadrant
  niche) — real long-term direction, not current capability. Item #9
  in the queue is the structural foundation; the rendering work follows.

---

## 7 · PR #36 status after this synthesis

PR #36 (`claude/donna-architecture-analysis-whxu4`) now contains:

- The original Claude review with corrections inline (filename remains
  `CODEX_REVIEW_DONNA_v0.4.0.md` for the historical record, with a
  prominent authorship-correction block at the top)
- The genuine Codex review at `CODEX_REVIEW_DONNA_v0.4.0_GPT5.md`
- This synthesis at `REVIEW_SYNTHESIS_v0.4.0.md`
- (TODO in the same PR) Updated `docs/KNOWN_ISSUES.md` with the merged
  action list

The PR is ready for merge once the KNOWN_ISSUES update lands. The
merge does not commit the user to any specific code fix — it only
documents the findings.

The recommended next session executes items #1-3 from the merged action
queue: internal-retrieval-taint, eval-ratchet, and `agent_scope`
first-classing. Each is a self-contained PR.
