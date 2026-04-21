# Changelog

## [0.2.0] — 2026-04-20 — v1.1 hardening + Python 3.14 + Corpus brief

Three Codex review passes absorbed (defect, adversarial-challenge, Hermes
comparison). v1 foundation upgraded with ~20 additional hardening fixes.
Corpus architecture extraction planned and briefed but not yet built.

### Added

**Python 3.14 upgrade**
- `requires-python>=3.12`, actually running 3.14.3 in venv + `python:3.14-slim`
  Docker base image
- Dropped `voyageai` SDK dependency — SDK capped at Python <3.14 as of 2026-04.
  Replaced with direct httpx calls to Voyage's `/v1/embeddings` endpoint.
  Fewer deps, fewer version locks, same functionality.

**Pattern A Hermes steals (v1.1)**
- `model_runtimes` registry table + `memory/runtimes.py` — vendor abstraction
  as DATA. Adding OpenAI is `INSERT INTO model_runtimes ...` + new adapter
  class, not a rewrite. Seeded with three Anthropic tiers (haiku/sonnet/opus).
- `memory/cost.py::_pricing_for()` reads prices from registry — no more
  hardcoded pricing constants.
- `agent/model_adapter.py::resolve_model()` routes tier → model_id via
  registry with env-var fallback if table empty.
- `/model` Discord slash command + `threads.model_tier_override` column.
  Per-thread tier switch (fast/strong/heavy/clear). `_pick_tier()` priority:
  job-override → thread-override → default strong.
- `/models` slash command lists registered runtimes with pricing.
- Compaction audit trail: raw pre-compaction message tail saved as
  sha256-addressed artifact before summarization. `jobs.compaction_log` JSON
  column records every compaction event. Recoverable via `read_artifact`.

**Codex Pass-2 adversarial review fixes**
- **Unified execution** — new `src/donna/agent/context.py` with `JobContext`.
  Every mode (chat, grounded, speculative, debate) shares primitives:
  `model_step`, `tool_step`, `consent_wait`, `maybe_compact`, `checkpoint`,
  `finalize`. Prior two-headed split (generic loop + mode dispatch) replaced
  with single entrypoint that dispatches by `JobMode`.
- **Native sqlite-vec retrieval** — `memory/knowledge.py::semantic_search()`
  uses `vec_distance_cosine` scalar function in SQL. Python numpy fallback
  preserved if sqlite-vec fails to load.
- **Search snippet sanitization** — `tools/web.py::_sanitize_hits()` runs
  every search_web / search_news snippet through dual-call Haiku
  sanitization. Previously only fetch_url was sanitized.
- **Persistent consent** — migration 0003 adds `pending_consents` table.
  `security/consent.py` writes pending rows + transitions job to
  `paused_awaiting_consent`. Restarts can now resume, re-prompt, and never
  silently drop a consent request.
- **Quoted-span grounded validator** — `security/validator.py` now requires
  a verbatim `quoted_span` (≥20 chars, case/whitespace-insensitive) from a
  cited chunk per claim. Replaces the 2-word lexical overlap heuristic.
- **Attachment ingestion tool** — new `src/donna/tools/attachments.py` with
  `ingest_discord_attachment` — agent can consume Discord-attached
  PDFs/txt/md and route through ingestion pipeline. Tainted by default.
- **`propose_heuristic.reasoning` persisted** into
  `agent_heuristics.provenance`. Was silently dropped before.
- **Async facts.last_used_at** — `memory/facts.py` now fires the
  last_used_at update via `asyncio.create_task` on a fresh connection.
  Eliminates synchronous-write contention on the read path.
- **OTel + SQLite traces** — `observability/trace_store.py` adds a
  `SqliteSpanProcessor` that persists finished spans to the `traces` table.
  Previously the table had schema but no writer.
- **Stuck-job watchdog** — `observability/watchdog.py` DMs on:
  stuck-consent (>1h), stuck-running (>30m), failure-rate spikes (3+/hr).
  Wired into main.py alongside the budget watcher.
- **`botctl cache-hit-rate`** — reads cost_ledger, reports actual % of
  input tokens served from cache by tier over a window. Closes the
  measurement loop on prompt composition ordering.

**Codex Pass-1 defect fixes (earlier)**
- C1 · Taint bypass via read_artifact — fixed via tool-result taint propagation
- C2 · Lease expiry reclaim during long awaits — continuous 30s heartbeat
  task + owner-guarded writes + LeaseLost exception
- C3 · Parallel tool batch taint race — pre-scan + pessimistic pre-taint
- H1 · Grounded/speculative/debate were dead code — wired through JobContext
  dispatch
- H2 · Non-idempotent tool replay on resume — tool_use_id dedup from prior
  message history
- H3 · Discord ask-reply thread misrouting — `posted_channel_id` on asks
- Cost ledger clobber on checkpoint — `save_checkpoint` no longer writes cost
- Rate limiter infinite wait on oversized request — `OversizedRequestError`
- Retrieval temporal boost skew — boost now scaled to pool's max RRF score
- Debate validator false positives — normalize punctuation, allow quoted
  spans ≥5 chars OR fuzzy 10-char normalized overlap
- chunks_fts UPDATE trigger (migration 0002)
- sops entrypoint YAML parsing (shipped deploy was a no-op grep for KEY=VALUE)
- Ingestion within-batch duplicate embedding

**Documentation & planning**
- `docs/review.html` — interactive Codex adversarial review viewer
  (filterable, color-coded by my take on each finding)
- `docs/morning.html` — interactive 12-step bring-up walkthrough
- `docs/KNOWN_ISSUES.md` — full fix/defer status for all three Codex passes
- `docs/CORPUS_BRIEF.md` — comprehensive bootstrap brief for a new session
  to build "corpus" — the corpus interpretation engine. Monorepo addition
  (`src/corpus/` alongside `src/donna/`), separate schema namespace, hard
  internal boundary. Based on the Hermes comparison + Codex's "this is a
  corpus interpretation engine, not memory" reframe. 19 sections, ~13k
  words, includes verbatim Codex insights from session 019db08b.

### Changed

- `requires-python` bumped language (still `>=3.12`, but 3.14 is now the
  production runtime)
- Docker base image `python:3.12-slim` → `python:3.14-slim`
- All four migrations (0001 → 0004) apply cleanly on a fresh database
- Every existing file + new file AST-clean, 60/60 tests green on Python 3.14

### Fixed (test-side)

- `tests/conftest.py::fresh_db` invokes alembic via `sys.executable -m alembic`
  so subprocess finds it without venv activation on Windows.
- `tests/test_adversarial_fixes`: import path for
  `_already_executed_tool_use_ids` updated after it moved to `context.py`.
- `tests/test_validator.test_valid_citation_passes`: updated to include
  `quoted_span` (new schema requirement).
- `tests/test_validator.test_debate_attack_without_quote_is_flagged`:
  updated to use vocabulary with no substantive overlap (validator
  correctly accepts paraphrases with shared 10-char substrings).
- `tests/test_challenge_fixes.test_botctl_has_cache_hit_rate`: inspect
  `callback.__name__` instead of `cmd.name` (Typer sets `.name=None` when
  the decorator uses function-name-derived CLI names).

### Deferred / open

- Live-API integration test (waiting on bot-ops accounts)
- Litestream backup setup (documented in OPERATIONS.md)
- Graph-RAG retrieval + oracle mode (becoming the "corpus" project, see
  `docs/CORPUS_BRIEF.md`)
- Stronger grounded validator than quoted_span (NLI sidecar / verifier-LLM
  call) — wait for real traces to show if hallucinations slip through
- L2 domain packs, L3 power tools, L4 autonomous meta-tools
- Multi-agent specialists, delegation
- Watchers, post-job reflections, self-scheduled triggers
- Second LLM vendor (registry ready; implementation is INSERT + adapter)
- Slack adapter

---

## [0.1.0] — 2026-04-17 — foundation build

Initial overnight build. Matches `docs/PLAN.md`. Not yet live-tested against
real Anthropic / Discord / Tavily / Voyage APIs.

### Added

**Scaffolding**
- Python 3.12 package with pyproject.toml (hatchling)
- Dockerfile (read-only rootfs, non-root `bot` user, tini, sops+age baked in)
- docker-compose.yml (bot + worker + phoenix, localhost-only ports)
- .github/workflows/build.yml (lint + test + build + sign + push to GHCR)
- scripts/harden-droplet.sh (Ubuntu 24.04 hardening)
- scripts/first-deploy.sh (post-harden bootstrap)
- scripts/entrypoint.sh (sops-decrypt-then-exec)
- .sops.yaml template
- alembic.ini + migrations/env.py + 0001_initial_schema (full v1 schema)

**Data model**
- 15 SQLite tables: threads, messages, jobs, tool_calls, traces, facts
  (+FTS5 triggers), artifacts, permission_grants, schedules,
  knowledge_sources, knowledge_chunks (+FTS5 triggers), agent_heuristics,
  agent_examples, agent_prompts (versioned), cost_ledger
- WAL + busy_timeout + two-process contract (bot=enqueue-only, worker=sole lease owner)
- sqlite-vec loaded for vector search

**Agent core**
- `Agent` class-ready design (v1 single orchestrator instance)
- ~250-line agent loop with lease/heartbeat/checkpoint, parallel tool calls,
  context compaction at N=20, model tier routing
- Cache-aware system prompt composition (stable prefix + bounded volatile suffix)
- Orchestrator system prompt + sanitize prompt (stored as .md files)
- Rate-limit ledger shared across concurrent jobs (RPM/ITPM/OTPM per tier)
- Anthropic adapter with prompt caching, retry, 429 handling, cost recording

**Tools (v1, 12 registered)**
- `search_web`, `fetch_url`, `search_news` (Tavily-backed, taint-marking)
- `save_artifact`, `read_artifact`, `list_artifacts` (sha256 dedupe)
- `remember`, `recall`, `forget` (facts + FTS5)
- `ask_user`, `send_update` (outbox queues drained by Discord adapter)
- `run_python` (subprocess-isolated, always-confirm)
- Knowledge: `teach`, `recall_knowledge`, `recall_examples`, `recall_heuristics`,
  `propose_heuristic`, `list_knowledge`

**Security**
- Lethal-trifecta defense: taint tracking + dual-call Haiku sanitization of
  untrusted content + policy-escalated confirmation
- 3-mode consent system (never / once_per_job / always / high_impact_always)
- Grounding validator (citation-required schema + lexical entailment check)
- Debate turn validator (quote-to-attack requirement)

**Observability**
- OpenTelemetry via OTLP gRPC (GenAI semantic conventions + Donna extensions:
  agent.job.tainted, agent.taint.source_tool, etc.)
- Phoenix configured with PHOENIX_DEFAULT_RETENTION_POLICY_DAYS=30
- Cost ledger with per-model pricing, daily rollup, Discord DM alerts at soft
  thresholds ($5/$15/$30)

**Jobs & scheduling**
- Durable job runner with lease + heartbeat + checkpoint + idempotency flags
- MAX_CONCURRENT_JOBS=3 semaphore
- Cron scheduler (v1's only proactive trigger) via croniter

**Modes**
- Grounded (strict citation + refusal on zero retrieval + 1 regenerate-retry)
- Speculative (opt-in per scope, 🔮-labeled, banned-phrasing check)
- Debate (orchestrator-wears-hats, per-scope retrieval isolation, neutral summary)

**Ingestion**
- Paragraph-aware chunker (~500t / 80t overlap)
- Fingerprint dedupe on ingestion
- Voyage-3 batched embeddings
- Hybrid retrieval: semantic + FTS5 via RRF merge, temporal priors, diversity
  constraints (max 2/work, max 3/source_type)

**Discord adapter**
- discord.py 2.5+ with MESSAGE_CONTENT intent
- Slash commands: /status, /cancel, /history, /budget, /ask, /speculate,
  /debate, /schedule, /schedules, /heuristics, /approve_heuristic
- Reaction approvals (✅/❌) for consent prompts
- Outbox queue drainers for updates, asks, consent
- Threads per job; rate-limited progress pings (1/5s)

**CLI**
- `botctl` (Typer + Rich) with: jobs, job, cost, teach, heuristics, migrate,
  schedule add/list/disable, traces prune

**Tests**
- Registry shape
- Grounding + debate validators
- Chunker behavior
- Rate limiter basics
- Memory primitives (job lifecycle, FTS search)
- Taint policy
- Retrieval diversity

**Golden evals**
- Grounded refusal on empty retrieval
- Speculation policy enforcement
- Debate quote-to-attack requirement
