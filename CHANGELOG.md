# Changelog

## [0.1.0] — 2026-04-17 — foundation build

Initial overnight build. Matches `docs/PLAN.md`. Not yet live-tested against
real Anthropic / Discord / Tavily / Voyage APIs — tomorrow's work.

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

### Deferred (see docs/PLAN.md)

- Live-API integration test (needs real keys)
- L2 domain packs (YouTube, finance, research, scraping)
- L3 power tools (bash, SQL, email, GitHub)
- L4 autonomous meta tools beyond `propose_heuristic`
- True multi-agent specialists + `delegate_to`
- Watchers, post-job reflections, self-scheduled follow-ups
- Full CaMeL architecture
- Slack adapter
