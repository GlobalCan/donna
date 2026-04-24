# Codex Deep Dive — Donna v0.4.0 Architectural + Feature + Competitive Analysis

> **Purpose:** self-contained prompt for Codex (GPT-5.x) to do a thorough
> review of Donna's architecture, feature set, and positioning relative
> to the 2026-vintage personal-agent / agent-framework landscape. Output
> is a structured findings document the user can absorb into fix PRs.
>
> **How to invoke:** `codex exec --skip-git-repo-check < this-file.md`
> or paste into the Codex web UI as the opening turn.

---

## Your role

You are an adversarial reviewer. Your default is skepticism. You have
read 12+ agent frameworks, 5+ memory systems, 3+ RAG products, and
been in enough production agent codebases to know which architectural
decisions age well and which become anchors. Treat nothing in this
repo as correct-by-default.

The user is a solo operator who has built this bot over ~3 days in
multiple Claude Code sessions. They have already absorbed three
previous Codex passes (defect review, adversarial challenge, Hermes
comparison, round-2 same-class hunt) plus a self-run round. So the
low-hanging fruit is gone. What you are looking for is:

1. **Strategic mistakes** — not bugs. Decisions that constrain what
   Donna can become.
2. **Non-obvious wins** — things the codebase does better than most
   of the field and should be amplified.
3. **Missing features with real leverage** — what would 10x the
   utility for a ratio of effort that makes sense for a solo operator.
4. **Comparative blind spots** — what did other frameworks solve that
   Donna doesn't know it's missing.

## The repo

`GlobalCan/donna` — Python 3.14, SQLite + sqlite-vec + FTS5,
hand-rolled `anthropic` SDK (no framework), Discord-facing
(`discord.py`), deployed on DigitalOcean in Docker + sops+age secrets.
Solo-operator bot, no multi-tenant aspirations.

### Critical files to read first (roughly in dependency order)

- `README.md` — status + architecture overview
- `CHANGELOG.md` `[0.4.0]` — the full story of what just shipped
- `docs/PLAN.md` — the v1 architectural plan (some sections now historical)
- `docs/KNOWN_ISSUES.md` — adversarial rounds 1-3 + deferred items
- `docs/SESSION_RESUME.md` — full context snapshot
- `docs/THINK_BRIEF.md` — the sibling corpus-interpretation project
  (separate repo; architectural divergence doc)
- `src/donna/agent/context.py` — `JobContext`: unified primitives for
  every mode (chat / grounded / speculative / debate). Load-bearing.
- `src/donna/agent/loop.py` — mode dispatch
- `src/donna/agent/compose.py` — cache-aware prompt composition
- `src/donna/agent/compaction.py` — Haiku-summarization + audit artifact
- `src/donna/agent/model_adapter.py` — Anthropic SDK wrapper
- `src/donna/modes/{grounded,speculative,debate,retrieval}.py` — mode handlers
- `src/donna/security/{taint,consent,sanitize,validator}.py` — lethal
  trifecta defense
- `src/donna/tools/*.py` — the 17 registered v1 tools
- `src/donna/memory/*.py` — SQLite primitives (jobs, facts, artifacts,
  knowledge, cost, runtimes, prompts, schedules, threads)
- `src/donna/adapter/discord_adapter.py` — Discord adapter +
  `_split_for_discord` + `_post_overflow_pointer` (overflow-to-artifact
  security pattern)
- `src/donna/ingest/{chunk,embed,pipeline}.py` — corpus ingestion
- `src/donna/observability/{otel,watchdog,budget,trace_store}.py`
- `src/donna/cli/botctl.py` — ops CLI
- `migrations/versions/*.py` — 5 migrations, 0001 → 0005
- `tests/` — 37 test modules, 293 tests

### Prior Codex rounds

Read `docs/KNOWN_ISSUES.md` — it summarizes what each prior Codex pass
found and how it was addressed. Don't re-flag things that are already
fixed. Do re-evaluate whether the fixes are *correct* or just
*present*.

## What I want you to examine

### Part 1 — Architectural decisions (rank each: ✅ keep, ⚠️ reconsider, ❌ change)

1. **Hand-rolled Anthropic SDK instead of LangGraph / CrewAI / Agent SDK / Pydantic AI.**
   Pro: transparency, no framework rug-pull risk. Con: re-implementing
   primitives. Has Donna hit the point where a framework would be
   strictly better?
2. **Unified `JobContext` across modes** (chat / grounded / speculative
   / debate). The alternative is per-mode classes. Does the unified
   shape constrain any future modes?
3. **Mode-dispatch at `agent/loop.py`** rather than first-class mode
   objects. Any hidden coupling?
4. **SQLite as the single source of truth** (jobs, facts, knowledge,
   outbox, consent, cost, traces). When does this fail? At what row
   count / concurrent-writer count?
5. **`agent_scope` as a flat string** (not a row in a scopes table, not
   a hierarchical structure). Limits the "multi-author composite
   persona" use case in THINK_BRIEF; acceptable?
6. **Discord-only** with no adapter abstraction. Is the `discord_adapter`
   cleanly separable from `agent/` for a future Slack/matrix/CLI
   adapter, or has discord.py bled into core paths?
7. **Outbox pattern** for Discord delivery (DB rows drained by a poll).
   Alternatives: in-process queue, webhook. Trade-offs under outage?
8. **Taint as a per-job boolean** rather than per-value. Does this
   over- or under-propagate? Where?
9. **Quoted-span validator — structural, not semantic** by design.
   `_verbatim_in` with smart-quote normalization. Is the 20-char
   floor defensible? Is normalization now too lenient?
10. **`ModelRuntime` registry — pricing as data.** Is the table the
    right shape to add OpenAI / Gemini / open-source models, or does
    it bake in Anthropic assumptions?
11. **Cache-aware prompt composition** (stable prefix + volatile suffix,
    `cache_control: ephemeral`). Is the split correct? Should anything
    else move in or out of the cached block?
12. **Overflow-to-artifact security pattern** — attacker-controlled
    tainted content compartmentalized into artifact storage rather
    than Discord scrollback. Novel, to our knowledge. Is this the
    right framing, or is it solving the wrong problem?
13. **Compaction-as-summarization with audit artifact.** Haiku summary
    replaces raw tail; original preserved in artifact. Any scenarios
    where summarization loses load-bearing context the agent needs
    later?

### Part 2 — Feature comparison vs the 2026 field

For each of these, evaluate Donna's position:

#### Agent frameworks

- **LangGraph** (v1.0+ in 2026) — explicit graph structure, checkpointing,
  community
- **CrewAI** — multi-agent role-based, growing adoption
- **Pydantic AI** — type-safe, structured outputs
- **OpenAI Agents SDK** — ecosystem lock-in, but mature
- **Claude Agent SDK** — newest, first-party, opinionated
- **Nous Hermes Agent** — open-source, 107k GitHub stars, MCP-native,
  skill marketplace (the source of `/model`, compaction lineage,
  `ModelRuntime` registry ideas — Donna has already absorbed 3 steals)

Donna's bet: hand-rolled. Is the bet still correct? What specific
capability do the frameworks offer that Donna would have to build
next if it wanted parity?

#### Memory / knowledge systems

- **Letta / MemGPT** — memory manager separate from agent, context
  assembly
- **Mem0** — memory-as-service, shallow but API design
- **Zep / Graphiti** — temporal KG, fact versioning
- **mnemostack** (OpenClaw) — 4-way parallel retrieval + RRF
- **Microsoft GraphRAG** — hierarchical community summaries
- **LightRAG** — dual-level retrieval
- **HippoRAG 2** — personalized PageRank over entity graphs

Donna's knowledge layer is deliberately thin (it's what the sibling
Think project is for). But for the bits Donna has — `facts`,
`knowledge_sources`, `knowledge_chunks`, retrieval with diversity
constraints — what's missing that competitors have? (E.g. temporal
fact versioning is in Zep; Donna's facts table has `last_used_at`
but no explicit versioning.)

#### Personal-AI products

- **Poke, Friend Computer, Rewind, Day.ai, SANA** — commercial
  always-on assistants. Feature matrix?
- **Character.ai, Replika** — persona-based chatbots. What they get
  right about voice; what they miss (no grounding).
- **NotebookLM (Google)** — grounded QA over user-provided corpora.
  Directly competes with Donna's grounded mode. Architectural
  differences?
- **Perplexity** — live-web grounded answers with citations. Citation
  discipline comparison.

Donna's pitch is "solo-operator personal, strictly grounded to owned
corpora, debate mode for cross-author synthesis" — what features
from the above would make that pitch 10x more useful, and what
features would dilute it?

#### Security / prompt-injection defense

- **Simon Willison's lethal trifecta** framework — Donna explicitly
  addresses all three legs (private data + untrusted content +
  external comm). Adequate?
- **CaMeL (DSL + policy engine)** — research-grade; Donna chose
  taint-tracking + dual-call as a poor man's version. At what scale
  / attack sophistication does that calculus flip?
- **NVIDIA AI Red Team sandboxing guidance** — mandatory controls
  comparison

### Part 3 — Missing features ranked by leverage / effort

Rank your top 10 "should probably build this" items:

- Effort: XS (hours) / S (days) / M (week) / L (multi-week)
- Leverage: user-visible value
- Risk: how much could it break existing invariants

Examples of what I'm NOT looking for (already deferred with rationale):

- Full CaMeL
- pgvector migration
- Multi-tenant schema
- Second LLM vendor (Donna is honestly Anthropic-shaped)

### Part 3.5 — Evaluate a proposed feature: `/validate`

User-requested during the v0.4.0 signoff. Pattern: user sends an
article / reel / video / social post URL (or an attachment); Donna
returns a structured critique with:

- Claims extracted (each paired with an original quote)
- Verifiability assessment (cross-check against authoritative web
  sources + the user's ingested corpora)
- Red flags: emotional framing, missing context, logical fallacies,
  selective presentation
- Counter-evidence from user's ingested corpora (grounded-retrieval step)
- Source credibility signals (domain reputation, author track record)
- Suggested follow-up questions / what the content *didn't* cover

Reuses existing primitives: `fetch_url`, `ingest_discord_attachment`,
dual-call Haiku sanitize, grounded retrieval pipeline,
overflow-to-artifact for long critiques. New infra required: a
video/reel transcript fetcher (yt-dlp + Whisper locally OR
AssemblyAI/Deepgram service) and a new `validate` mode handler +
system prompt.

Evaluate:

1. **Is this the right scope?** Or is it actually two features
   (web-article critique + video transcript critique) that should
   ship separately?
2. **Is the architecture sound?** Should it be a new `mode` parallel
   to grounded/speculative/debate, or a set of tools the chat agent
   can orchestrate, or a `botctl validate` CLI command?
3. **What's the right output shape for Discord?** A single long
   message that triggers overflow-to-artifact? Separate messages per
   section? A generated PDF artifact?
4. **How does it compare to competitors?** Ground News, NewsGuard,
   Kagi Assistant, Perplexity Verify, Full Fact, Factmata — what
   does each do that Donna's version should match or beat for a
   solo operator?
5. **What's the failure mode for videos/reels?** yt-dlp gets broken
   by platform changes every few months. AssemblyAI/Deepgram cost
   $0.30-$1 per hour of audio. What's the right balance for a
   $6/month droplet bot that a solo operator uses ~daily?
6. **How does taint propagate?** The content being validated is by
   definition untrusted (it's the object of critique). The critique
   itself references that content. Does the overflow-to-artifact
   tainted-content compartmentalization extend cleanly here, or do
   we need a new pattern?

### Part 4 — Specific deep-dive questions

1. **Is the `quoted_span` 20-char floor correct?** Should it be
   configurable per-scope? Lengthen to 40? Remove in favor of
   NLI-verifier sidecar?
2. **Is the retry prompt on grounded-validation-fail doing the right
   thing?** Or should grounded mode have *two* retries, or escalate
   to a different prompt structure, or just accept the partial
   validation + flag it to the user?
3. **Is the overflow-to-artifact threshold for tainted content
   (1900 chars, 1 part)** too tight? Too loose? Context: a
   `fetch_url` summary is often 500–1500 chars, well under the cap.
4. **Is the compaction strategy sound?** Haiku-summarize every N=20
   tool calls. Anthropic's native prompt cache could be an
   alternative (if the model has seen the same history recently,
   re-feed it with cache markers). Trade-offs?
5. **Should `agent_scope` become first-class** (a `scopes` table with
   metadata) rather than a flat string? This would enable per-scope
   `speculation_allowed` without having to seed an `agent_prompts`
   row first (which today is a footgun — `botctl teach` doesn't
   create one).
6. **`facts` vs `knowledge_chunks` separation** — is this the right
   bifurcation? One is operational memory (things the agent learned
   during a job), the other is curated corpus (things the user
   taught via `teach`). Is the boundary clean?

### Part 5 — THINK separation sanity check

The user started extracting corpus-interpretation into a sibling
`GlobalCan/Think` repo during this session stack. Read
`docs/THINK_BRIEF.md`. Questions:

1. Is the Donna ↔ Think boundary drawn correctly (Think returns
   `EvidencePack`, Donna composes prose)?
2. Should `tools/knowledge.py::recall_knowledge` move to Think and
   become Think's public entry, or stay in Donna as a thin wrapper?
3. What's the right migration story for the existing 402-chunk Huck
   Finn corpus sitting in Donna's `knowledge_sources` +
   `knowledge_chunks` tables? Keep it in Donna's SQLite but accessed
   via Think's API? Or migrate to a `think_*` namespace inside the
   same file?

## Output shape — what to produce

A single Markdown document with these sections:

```
# Codex Deep Dive — Donna v0.4.0

## 1. Executive summary
5-8 bullets: top strategic observations

## 2. Architectural scorecard
Table: decision | ✅ keep / ⚠️ reconsider / ❌ change | why

## 3. Field positioning
Narrative on where Donna sits vs LangGraph / CrewAI / Hermes /
Letta / MemGPT / Mem0 / GraphRAG / LightRAG / NotebookLM /
Perplexity / Poke / Rewind. What's Donna's defensible niche?

## 4. Top 10 recommended additions
Ranked by leverage/effort. Each: what, why, how.

## 5. Deep-dive answers
Responses to Part 4's six questions.

## 6. Think separation review
Part 5 answers.

## 7. Red flags
Things the user should know are wrong NOW but haven't surfaced live
yet.

## 8. Non-obvious wins
Things Donna does better than the field that the user should amplify.
```

## Rules for your review

1. **Read the code before judging.** Don't opine on a pattern without
   citing the actual file:line it lives at.
2. **Distinguish decisions from bugs.** A decision you'd have made
   differently is not a bug.
3. **Respect the solo-operator constraint.** Don't recommend "add a
   team to do X." Donna has one person.
4. **Respect the Codex ancestry.** If you find yourself about to flag
   something, check `docs/KNOWN_ISSUES.md` first — you or a prior
   Codex may have already argued about it.
5. **Quantify when you can.** "Cost will increase N%" > "cost will
   increase."
6. **Be specific.** "Refactor `JobContext`" is useless without
   specifics; "Move `maybe_compact` out of `JobContext` because X"
   is useful.

Good luck. The user values depth over speed. Take the time the
analysis requires.
