# Session Resume Prompt — Donna continuation

**This file exists so that after a session compact, or when starting a new
Claude Code session on the Donna repo, you can paste this prompt (or just
`@docs/SESSION_RESUME.md`) and get fully back into context in one move.**

---

## 0 · What to read, in order

Before anything else, read these files. Everything below assumes you have.

1. `README.md` — product identity + status
2. `CHANGELOG.md` — full version history, v0.1.0 → current
3. `docs/PLAN.md` — the architectural plan
4. `docs/KNOWN_ISSUES.md` — three Codex review passes, fix/defer status for every finding
5. `docs/CORPUS_BRIEF.md` — the bootstrap brief for the sibling corpus interpretation engine (separate session, monorepo package)
6. `docs/OPERATIONS.md` — production ops + DR
7. `docs/MORNING_START.md` + `docs/morning.html` — 12-step live-deploy walkthrough
8. `docs/review.html` — interactive Codex adversarial review viewer
9. `src/donna/agent/context.py` — the `JobContext` shared primitives
10. `src/donna/agent/loop.py` — mode-dispatching entrypoint

---

## 1 · Where we are

**Donna v0.3.0 is live in production on DigitalOcean.** Four smoke tests green
end-to-end against real APIs. Bot answering DMs as `Donna#3183`.

- **Branch:** `main`, clean working tree
- **Droplet:** `159.203.34.165` (Ubuntu 24.04 LTS), hardened (bot user, sshd
  key-only, ufw, fail2ban, unattended-upgrades, docker, sops, age)
- **Image:** `ghcr.io/globalcan/donna:latest` — published by GHA `build-and-push`
- **Secrets:** sops-encrypted `secrets/prod.enc.yaml` in repo, 2 age recipients
  (primary on laptop+droplet, backup offline); age private key at
  `/etc/bot/age.key` on droplet
- **DB:** `/data/donna/donna.db` on droplet (bind-mounted into containers),
  migrations 0001 → 0005 all applied
- **Tests:** 70/70 green on Python 3.14.3
- **Remote HEAD = local HEAD**

**Still open after Phase 2** (see `docs/KNOWN_ISSUES.md` §Phase 2):
- No off-droplet backups yet
- Auto-update timer not enabled (manual `docker compose pull && up -d`)
- Container UID 10001 vs host UID 1001 mismatch — worked around with chmod
- Phoenix observability disabled (upstream image broken 2026-04-23)
- `botctl` ergonomics: needs `/entrypoint.sh` prefix + full job IDs

Three Codex review passes absorbed:
- Pass-1 defect review (session `019d9bbf-a2e3-7a40-8bde-9ac5f5fe163e`) — all CRITICAL + HIGH + most MEDIUM fixed
- Pass-2 adversarial challenge (session `019d9bda-b31d-75d2-a365-985c3af87cb8`) — all 15 findings fixed or explicitly deferred with mitigation
- Hermes comparison (session `019db01c-a788-7902-b9f3-8ee6aee32b59`) — 3 mechanisms stolen (ModelRuntime registry, compaction audit, /model command)

**Architectural decisions locked in this session stack:**
- Foundation-first, agent-first, hand-rolled loop
- Anthropic-only v1, ModelRuntime registry for future providers
- SQLite single source of truth, sqlite-vec native retrieval
- Discord-only, solo allowlist
- Unified `JobContext` primitives across all 4 modes
- Taint tracking + dual-call Haiku on every untrusted input path
- Quoted-span grounded validator (verbatim ≥20 chars, case/whitespace insensitive)
- DB-persistent consent that survives restart
- Hermes Pattern A (cherry-pick mechanisms) over Pattern B (MCP server exposure); Pattern B deferred but codebase preserves the door
- **Corpus as separate monorepo package** — `src/corpus/` alongside `src/donna/`, same repo, same db file, hard internal API boundary, separate schema namespace `corpus_*`, separate migrations prefix, separate test/eval suite. See `docs/CORPUS_BRIEF.md` for the full bootstrap.

---

## 2 · What's next

Three tracks, pick what the user asks for:

### Track A — Stabilize the deploy (highest-leverage cleanup)

Small PRs that remove the hacks and improve ops ergonomics. Each is self-contained.

1. **`user: "1001:1001"` in `docker-compose.yml`** — makes container bot run as host's UID so the `chmod 644 /etc/bot/age.key` + `chmod 777 /data/donna` workarounds go away.
2. **`botctl` ergonomics** — show full job IDs (not `[:18]` truncation), accept prefix-match on `botctl job <id>`, ship a wrapper so `docker compose exec bot botctl` works without the `/entrypoint.sh` prefix.
3. **Phoenix re-enable** — pin to a known-working `arizephoenix/phoenix:version-X.Y.Z` tag and uncomment the service.
4. **Enable `donna-update.timer`** — one-shot sudo on the droplet (via DO console since `bot` has no sudo password). After this, `git push` → ~5 min → running.
5. **Backups** — at minimum DO snapshots (nightly, free-ish). Ideally litestream to DO Spaces (~$5/mo).

### Track B — Exercise more of the stack

Tests beyond the four smoke tests:

1. **Teach a real corpus** — `botctl teach author_twain huck.txt` against a Project Gutenberg public-domain book. Validates ingest → chunk → embed → knowledge_chunks pipeline end-to-end, which the smoke tests didn't hit.
2. **Grounded / speculative / debate modes** — smoke-test them. Chat mode's `_enqueue_final_text` fix likely needs to be replicated for the other three modes (flagged in Phase 1 CHANGELOG).
3. **`/schedule`** — set a daily morning brief via `/schedule`, confirm the scheduler + cron tick fires it overnight.

### Track C — Corpus package scaffolding

If/when the user wants to start the sibling corpus project, follow `docs/CORPUS_BRIEF.md` exactly. Intended to be a separate Claude session on the other laptop, not this session. Target: add `src/corpus/` with the Phase-0 research doc and skeleton.

### Track D — Personal-infra add-ons (nice-to-have)

On the droplet:
- **Tailscale** — exit node + subnet router, replaces public-port-22 exposure for SSH
- **ntfy.sh self-hosted** — push notifications to phone from any script
- **Uptime Kuma** — monitor external services + the bot itself
- **Gitea / Forgejo** — private git host
- **Caddy + static site** — personal blog/wiki with auto-TLS

---

## 3 · User preferences — remember these

- **Direct, no hedging.** If you think a choice is right or wrong, say so. No "both have merits" diplomacy.
- **No emojis in code** unless the user explicitly asks. Fine in Discord/UX output (bot emojis are part of the UX).
- **Chrome, never Edge** for anything browser-related.
- **Markdown bullet points** are the default shape for substantive answers — tables and clean hierarchies, not wall-of-text.
- **They're a strong engineer** — explain mechanisms, don't over-explain concepts. Skip "Python is a programming language"-style basics.
- **Security-first, solo-forever.** Don't propose multi-tenant, SaaS, or enterprise features.
- **Provenance > polish.** If a pillar / claim / fact has no evidence, they want it removed, not smoothed over.
- **Understanding > speed.** User values depth. Don't rush.
- **"Build as much as possible so we can hit the ground running tomorrow"** is a recurring pattern — when they say go, go hard.
- **They disagree with recommendations sometimes, and they're often right.** When they push back, genuinely reconsider. Don't just defend your prior position.

---

## 4 · Current repo state at a glance

- **64 source files** under `src/donna/`
- **10 test modules** (60 tests, all green)
- **4 migrations** in `migrations/versions/`:
  - `0001_initial_schema` — full v1 schema (15 tables)
  - `0002_chunks_fts_update_trigger` — chunks_fts UPDATE trigger Codex flagged missing
  - `0003_pending_consents` — persistent consent state
  - `0004_v1_1_hermes_inspired` — model_runtimes table + threads.model_tier_override + jobs.compaction_log
- **7 docs files:** PLAN, KNOWN_ISSUES, OPERATIONS, MORNING_START (+ morning.html), review.html, CORPUS_BRIEF, and now SESSION_RESUME (this file)

**Venv:** `.venv` at repo root, Python 3.14.3, all deps installed.
**DB:** `data/donna.db`, migrations at `0004 (head)`, `model_runtimes` seeded with Anthropic haiku/sonnet/opus.

---

## 5 · Critical files and what they do

### Agent core
- `src/donna/agent/context.py` — **JobContext** with shared primitives: `model_step`, `tool_step`, `maybe_compact`, `checkpoint`, `finalize`. Also `LeaseLost` exception, `_heartbeat_loop`, `_already_executed_tool_use_ids` helper.
- `src/donna/agent/loop.py` — thin entrypoint, dispatches by `JobMode` (chat/grounded/speculative/debate)
- `src/donna/agent/model_adapter.py` — Anthropic SDK wrapper, reads model_id + pricing from ModelRuntime registry
- `src/donna/agent/compose.py` — cache-aware prompt composition (stable prefix + bounded volatile suffix)
- `src/donna/agent/compaction.py` — preserves pre-compaction history as artifact before summarizing
- `src/donna/agent/rate_limiter.py` — shared rate-limit ledger, raises `OversizedRequestError`

### Tools (17 registered, not 12 as earlier docs claimed)
- `src/donna/tools/registry.py` — `@tool` decorator + schema generation
- `src/donna/tools/web.py` — search_web, fetch_url, search_news (all dual-call sanitized)
- `src/donna/tools/memory.py` — remember, recall, forget
- `src/donna/tools/artifacts.py` — save, read (propagates taint from artifact metadata)
- `src/donna/tools/communicate.py` — ask_user, send_update (outbox queues)
- `src/donna/tools/exec_py.py` — run_python (sandboxed subprocess)
- `src/donna/tools/attachments.py` — ingest_discord_attachment (PDF/txt/md)
- `src/donna/tools/knowledge.py` — teach, recall_knowledge, list_knowledge, recall_heuristics, propose_heuristic

### Security
- `src/donna/security/taint.py` — TAINT_ESCALATED_TOOLS set + effective_confirmation()
- `src/donna/security/consent.py` — 4-mode consent with DB-persisted pending state
- `src/donna/security/sanitize.py` — dual-call Haiku sanitization for untrusted content
- `src/donna/security/validator.py` — grounded validator with quoted_span requirement, debate validator

### Memory
- `src/donna/memory/db.py` — connection management, WAL pragmas, sqlite-vec load
- `src/donna/memory/ids.py` — ID generation with typed prefixes
- `src/donna/memory/jobs.py` — lease-and-recovery with owner guards
- `src/donna/memory/knowledge.py` — native sqlite-vec retrieval with Python fallback
- `src/donna/memory/facts.py` — FTS5 facts + async last_used_at update
- `src/donna/memory/runtimes.py` — ModelRuntime registry queries
- `src/donna/memory/prompts.py` — versioned agent prompts + heuristics + reasoning persistence
- `src/donna/memory/threads.py` — threads + model_tier_override helpers

### Ingestion + retrieval
- `src/donna/ingest/chunk.py` — paragraph-aware chunker
- `src/donna/ingest/embed.py` — **direct HTTP to Voyage** (SDK dropped on 3.14)
- `src/donna/ingest/pipeline.py` — end-to-end ingest with within-batch dedup
- `src/donna/modes/retrieval.py` — hybrid RRF merge with diversity + temporal priors
- `src/donna/modes/grounded.py`, `speculative.py`, `debate.py` — mode handlers (both JobContext-based + legacy direct-call APIs retained for tests)

### Observability
- `src/donna/observability/otel.py` — OTLP setup + SqliteSpanProcessor wiring
- `src/donna/observability/trace_store.py` — persists spans to traces table
- `src/donna/observability/budget.py` — daily spend alerts
- `src/donna/observability/watchdog.py` — stuck-job/consent/failure-rate DM alerts

### Discord adapter
- `src/donna/adapter/discord_adapter.py` — gateway, outbox drain, reaction handling
- `src/donna/adapter/discord_ux.py` — slash commands including /model and /models

### Entry points
- `src/donna/main.py` — Discord adapter process
- `src/donna/worker.py` — job runner + scheduler
- `src/donna/cli/botctl.py` — ops CLI with cache-hit-rate command

---

## 6 · Known bugs and traps

### Architectural
- Still Anthropic-only in practice (registry exists but no OpenAI adapter yet). Docs already updated to drop "vendor-agnostic" claim.
- Grounded validator's quoted_span check is verbatim substring only — not semantic. Genuine paraphrases fail it. This is intentional for v1.1 (constrained transparency over lenient theater); revisit if real usage shows too many false refusals.
- `/data` path: Windows dev uses `./data`, Docker uses `/data`. Both work.

### Operational
- **OneDrive + venv is a known footgun.** User already hit this. Consider moving repo out of OneDrive or excluding `.venv/` and `data/` from sync.
- **Discord `MESSAGE_CONTENT` intent** — Codex-flagged as the #1 week-1 gotcha. Must be enabled in Discord dev portal before free-text DM replies work. Slash commands work regardless.
- **age key on droplet** must be `chown bot:bot && chmod 600` or sops decryption silently fails at container startup.
- **First GHA image push** — the GHCR image doesn't exist until the first push to main triggers the workflow. Either build locally on the droplet or push a commit first.

### In tests
- `tests/conftest.py::fresh_db` uses `sys.executable -m alembic` for subprocess — don't change to bare `["alembic", ...]` without restoring PATH handling.
- Deprecation warnings on `datetime` adapter from Python 3.12+/sqlite3 are harmless but visible. Not fixed because they're upstream-noisy.

---

## 7 · What Codex told us (verbatim, preserve for future decisions)

From Pass-2 adversarial review (session `019d9bda-b31d-75d2-a365-985c3af87cb8`):

> "Agent-first + mode dispatch is two architectures in one entrypoint. The bypass paths do not share loop mechanics like consent, compaction, tool budgeting, or crash-resume semantics."

We fixed this with unified JobContext in commit `5348c43`.

> "SQLite-vec is loaded but actual retrieval is brute-force numpy over all scoped rows."

We fixed this in commit `5348c43` by using `vec_distance_cosine` scalar function.

> "`_supports()` is too weak to be a meaningful factuality check."

We fixed this with verbatim `quoted_span` validator in commit `5348c43`.

From Hermes comparison (session `019db01c-a788-7902-b9f3-8ee6aee32b59`):

> "Donna should steal Hermes's `provider runtime resolution` mechanism: map `(provider, model)` to API mode, credentials, base URL, context limits, and pricing without contaminating the agent loop."

Done in commit `8d98a5c` via `model_runtimes` table.

From Corpus architectural consultation (session `019db08b-9636-7d83-90bd-7ef5e477770d`):

> "Corpus is a corpus interpretation engine, not memory."

This framing is the foundation of `docs/CORPUS_BRIEF.md` and the planned separation.

> "The graph is not 'the retriever.' The graph is the planner and organizer. Chunks remain the evidence substrate."

Documented in CORPUS_BRIEF §7 as Canon/Corpus's layered retrieval model.

> "I would not model the primitive as scope = persona. I would model: corpus, source, author, work, chunk, claim, concept, pillar, alignment, interpretation profile. A persona is then a view over attributed knowledge, not the root object."

This is the critical architectural reframe — Donna v1's `agent_scope` is flat; Corpus will have proper attribution.

---

## 8 · Decisions made but not yet implemented

- **Corpus extraction as monorepo package.** Structure fully spec'd in CORPUS_BRIEF.md. Not yet scaffolded. Separate Claude Code session will tackle it.
- **GitHub repo transfer to bot-ops account.** User planned for Phase 1 morning. Repo is currently under `GlobalCan`.
- **Litestream backup setup.** Documented in OPERATIONS.md, not yet provisioned on a real droplet.
- **`/compress` Discord command.** Mentioned as optional Hermes-inspired polish; not yet built.
- **Move repo out of OneDrive.** Recommended but not executed.

---

## 9 · Preferences for continuation

If the user asks you to:

- **"Status"** or **"where are we"** → give a short current-state snapshot (latest commit, tests, next step)
- **"Let's continue"** with no specifics → propose the three tracks from §2 and ask which
- **"Go"** after a prior plan → execute aggressively, commit+push at logical breakpoints
- **"Ask Codex"** → use `codex exec --skip-git-repo-check < prompt.txt` via Bash (not the codex:rescue subagent — user has called out the distinction)
- **"Build ___ (something)"** → check if it's in `docs/KNOWN_ISSUES.md` "deferred" list, scope appropriately, plan first then execute

If they say something cryptic or short, assume they mean the most recent natural continuation. Don't ask clarifying questions on obvious context.

---

## 10 · Verification checklist when resuming

Before taking action in a fresh session, quickly verify:

```bash
cd /c/Users/rchan/OneDrive/Desktop/donna
git status --short                   # should be clean
git log --oneline -3                 # see recent work
git rev-parse HEAD                   # local
git rev-parse origin/main            # should equal HEAD
.venv/Scripts/python --version       # should be 3.14.3
.venv/Scripts/python -m pytest -q    # should be 60 passed
```

If any of those fail, stop and investigate before continuing.

---

## 11 · If you're a brand new Claude session

This repo is the result of 2 days of intense design + implementation with one user. They have been part of every architectural decision. They trust Codex's adversarial reviews; they push back on you when you're wrong; they prefer direct discussion to diplomatic hedging.

Don't be precious about prior decisions — if you think something is wrong, say so. The user would rather argue and land on the right answer than have you defend bad code you didn't write.

Start by reading this file, `CHANGELOG.md`, `docs/PLAN.md`, and `docs/KNOWN_ISSUES.md` in full. Then ask the user what they want to work on.

Good luck.
