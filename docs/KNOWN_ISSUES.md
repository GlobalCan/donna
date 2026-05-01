# Known Issues

Two passes of Codex review have been addressed. The full review texts live
in `docs/review.html` (interactive) and session IDs noted below.

## Codex Pass 2 — Adversarial Challenge Review (2026-04-17)

Session `019d9bda-b31d-75d2-a365-985c3af87cb8`. Challenge-style review of the
whole architecture, not defect-focused.

| # | Challenge | Status | Implementation |
|---|---|---|---|
| 1 | Hand-rolled loop atrophy risk | **Acknowledged · partial mitigation** | Unified `JobContext` (#2) collapses the worst of it; full framework swap deferred |
| 2 | Two-headed execution (mode dispatch split) | **FIXED** | `src/donna/agent/context.py`, `loop.py`, `modes/*.py` — all modes share `JobContext` primitives |
| 3 | SQLite brute-force Python vector scan | **FIXED** | `memory/knowledge.py` — uses `vec_distance_cosine` in SQL, streams O(limit) |
| 4 | Unsanitized `search_web` / `search_news` snippets | **FIXED** | `tools/web.py` — `_sanitize_hits` dual-calls every snippet |
| 5 | Pending consent lost on restart | **FIXED** | migration `0003`, `security/consent.py` persist + resume |
| 6 | "Vendor-agnostic" claim was a lie | **FIXED (docs)** | `README.md` — claim dropped, honest about Anthropic-shaped boundary |
| 7 | 512MB worker fragile under retrieval | **FIXED** (via #3) | retrieval no longer loads every embedding into Python |
| 8 | `agent_scope` mislabeled as multi-user path | **FIXED (docs)** | `README.md` — clarified as per-persona, not multi-tenant |
| 9 | Cron rationale should be "operator-authored" | **FIXED (docs)** | `README.md` — updated framing |
| 10 | No cache-hit measurement | **FIXED** | `botctl cache-hit-rate` — reads cost_ledger, reports % served from cache |
| 11 | Grounded `_supports()` was theater | **FIXED** | `security/validator.py` — requires verbatim `quoted_span` (≥20 chars), substring of cited chunk |
| 12 | sops+age DR was hope-based | **FIXED (docs)** | `docs/OPERATIONS.md` — 2-recipient age, litestream, quarterly drill |
| 13 | Observability debugger-only, not ops | **FIXED** | `observability/watchdog.py` (stuck jobs / consent / failure alerts); `trace_store.py` (wire `traces` table) |
| 14 | `ingest_discord_attachment` missing; `propose_heuristic` reasoning dropped | **FIXED** | `tools/attachments.py`; `memory/prompts.py` persists reasoning in provenance |
| 15 | Unify execution into single job graph | **FIXED** (substantively) | Same as #2 — `JobContext` IS the unified primitive |

### Still open (deferred, not forgotten)

- **Grounded validator stronger still.** v1 uses verbatim `quoted_span` ≥20 chars — the "constrained transparency" model Codex recommended. If hallucinations still slip through in real use, upgrade to a per-chunk NLI sidecar or verifier-LLM call. Watch actual traces first.
- **Full LangGraph / framework swap.** Codex's contrarian recommendation. Valid argument but it's a rewrite, not a change. Revisit if v1.1 complexity becomes unmanageable.
- **Cache-hit-rate target.** Metric is exposed; we need real usage to know what's achievable.
- **Litestream setup.** Documented in OPERATIONS.md but not yet provisioned. Week-2 task.

## v1.1 — Hermes Agent adversarial comparison (2026-04-20)

Compared Donna against Nous Research's Hermes Agent (107k stars). Real Codex (GPT-5.4, session `019db01c-a788-7902-b9f3-8ee6aee32b59`) gave a comparative challenge review. Three specific mechanisms stolen into v1.1 — all additive, no refactor:

| # | Hermes steal | Status | Implementation |
|---|---|---|---|
| H-1 | **`ModelRuntime` registry** — provider/model/pricing as DATA, not slogan | **FIXED** | migration `0004`; `memory/runtimes.py`; `agent/model_adapter.py::resolve_model()`; `memory/cost.py::_pricing_for()` |
| H-2 | **Session lineage for compaction** — raw pre-compaction history preserved as artifact; job.compaction_log column | **FIXED** | `agent/compaction.py` saves JSON tail → artifact before summarizing; updates `jobs.compaction_log` JSON |
| H-3 | **`/model` operational command** — per-thread tier switch | **FIXED** | `threads.model_tier_override`; `discord_ux.py::/model` + `/models`; `loop.py::_pick_tier()` consults override |

Adding OpenAI later is now `INSERT INTO model_runtimes ... ; class OpenAIAdapter(Model): ...` — no change to the loop, no change to cost tracking.

### Hermes ideas explicitly NOT adopted (wrong for Donna's threat model)

- **Autonomous skill creation** — security theater for a single-operator bot; contradicts structural taint
- **18-platform messaging gateway** — Discord-only is the feature, not the limitation (fewer ingress paths = fewer attack surfaces)
- **agentskills.io hub consumption** — supply chain = OpenClaw's 300-malicious-skills redux
- **Modal/Daytona serverless backends** — the $6 droplet works; add complexity only when forced
- **Atropos RL trajectory training** — Hermes is research-angled; Donna is personal
- **Open plugin system** — Donna's trust boundary depends on every tool being code-reviewed

### Pattern B (MCP server exposure) — evaluated, deferred

Would expose Donna's primitives (`ask_scope`, `teach`, `recall_knowledge`, `debate`) as MCP tools so any agent (Hermes, Claude Desktop, other MCP clients) could consume them. Current code already supports this path cleanly (mode direct-call APIs preserved, tools standalone-callable). Required ~2 additional weeks (side-channel consent, per-client auth, taint propagation protocol, audit lineage) to match current end-to-end trust model. Addable later when a real second client exists — no door-closing decisions made now.

## Codex Pass 1 — Initial Defect Review (earlier 2026-04-17)

All CRITICAL + HIGH + MEDIUM fixed in the first fix pass.

| Finding | Status |
|---|---|
| C1 · Taint bypass via read_artifact | **FIXED** |
| C2 · Lease expiry reclaim during long awaits | **FIXED** (continuous heartbeat + owner-guarded writes) |
| C3 · Parallel tool batch taint race | **FIXED** (pre-scan batch for taint) |
| H1 · Grounded/speculative/debate were dead code | **FIXED** (re-refactored by Pass 2 #2) |
| H2 · Non-idempotent tool replay on resume | **FIXED** (tool_use_id dedup) |
| H3 · Discord ask-reply thread misrouting | **FIXED** |
| MEDIUM · Cost ledger clobber on checkpoint | **FIXED** |
| MEDIUM · Rate limiter infinite wait on oversized request | **FIXED** |
| MEDIUM · Retrieval temporal boost over-weighted | **FIXED** |
| MEDIUM · Grounded `_supports` weak | **FIXED** (by Pass 2 #11 — `quoted_span`) |
| LOW · Debate validator false positives | **FIXED** |
| LOW · chunks_fts missing UPDATE trigger | **FIXED** |
| LOW · sops entrypoint was a no-op | **FIXED** |
| LOW · Ingestion double-embed duplicates | **FIXED** |

## Intentional deferrals (architecture, not bugs)

- **Full CaMeL** — overkill for solo bot. Taint tracking + dual-call on all untrusted paths (fetch + search + attachments + read_artifact propagation) is v1's ceiling.
- **Multi-vendor model adapter** — v1 is honestly Anthropic-shaped. When we add OpenAI, we'll define an internal content/tool IR first (Codex's recommendation).
- **Multi-tenant schema** — not a goal. `agent_scope` is for personas only.
- **Live-API integration tests** — wait for real bot-ops keys.
- **PostgreSQL / pgvector migration** — trigger is real scale pain, not arrival.

## "Anything else logical" pass (not flagged by Codex, fixed proactively)

- `facts.last_used_at` was mutated synchronously on the read path. Moved to a fire-and-forget asyncio task on a separate connection so `recall()` doesn't block on a write (`memory/facts.py`).
- `traces` table had schema but no writer. Added `SqliteSpanProcessor` (`observability/trace_store.py`).

## Phase 1 live-run pass (2026-04-22)

First end-to-end run against real APIs surfaced three real bugs the in-process
test suite couldn't catch. All fixed in v0.2.1 (see CHANGELOG).

| # | Bug | Status | Where |
|---|---|---|---|
| P1-1 | `bot.loop.create_task` pre-start fails on discord.py 2.x | **FIXED** | `main.py` — `asyncio.create_task` inside async `_run()` |
| P1-2 | Cross-process outbox (in-memory asyncio.Queue) — updates/asks/consent lost between bot + worker processes | **FIXED** | migration `0005`, `tools/communicate.py`, `security/consent.py`, `adapter/discord_adapter.py` — SQLite is now the outbox |
| P1-3 | Chat mode's `final_text` orphaned — agent's answer never delivered to Discord | **FIXED** | `agent/loop.py::_enqueue_final_text` writes to `outbox_updates` on mode exit (superseded by P1-4 unification) |
| P1-4 | Grounded / speculative / debate modes had the same orphaned-final-text hole flagged in P1-3's deferral | **FIXED** | `agent/context.py::JobContext.finalize()` now writes `outbox_updates` atomically with the DONE status flip. Removed the chat-only `_enqueue_final_text` helper; every mode inherits delivery. Also closes a latent chat-mode double-delivery bug on finalize-retry (outbox write was in a separate transaction from DONE flip). |

### Open follow-ups from Phase 1 (not blocking)

- ~~**Wikipedia 403 on fetch_url** — `DonnaBot/0.1 (+personal)` UA is policy-compliant but Wikipedia has gotten stricter. Agent falls back to Tavily + non-Wikipedia source, so not blocking. Fix: beef up UA string with contact URL.~~ **FIXED** — `src/donna/tools/web.py::fetch_url` sends `Donna/0.2 (+https://github.com/GlobalCan/donna; solo-operator personal AI assistant) httpx` plus browser-typical Accept headers. Re-verify with a live fetch if 403s reappear.
- ~~**1500-char truncation on send_update** — long-form summaries get cut mid-sentence.~~ **FIXED** on `claude/load-up-setup-7XtVU` via a two-tier delivery:
  1. `_split_for_discord` breaks text at paragraph / sentence / newline boundaries into `(i/N)` multi-part messages — up to **3 parts inline for clean text**, **1 part for tainted**.
  2. Anything longer gets routed through `_post_overflow_pointer` — the full text is saved as an artifact (tagged `overflow` + `tainted` when applicable, inherits the taint flag), and Discord gets a short preview + `botctl artifact-show <id>` pointer. Security rationale: attacker-controlled output doesn't flood Discord scrollback; viewing the full content requires an explicit operator fetch.
  The `send_update` tool keeps its 1500-char cap — progress pings are meant to be terse. Job-level `final_text` uses the overflow pattern end-to-end.

## Phase 2 production deploy pass (2026-04-23)

First real deploy to the DigitalOcean droplet surfaced a batch of
production-only bugs the Phase 1 localhost run couldn't catch. All resolved or
tracked as follow-ups; v0.3.0 shipped with the fixes.

### Deploy pipeline

| # | Bug | Status | Where |
|---|---|---|---|
| P2-1 | `harden-droplet.sh` step [5/9] races with unattended-upgrades' dpkg lock, aborts, leaves sshd hardened + bot with no sudo password (catch-22 recovery) | **FIXED** | `scripts/harden-droplet.sh` — replaced `dpkg-reconfigure` with direct `20auto-upgrades` write, added `wait_for_apt_lock` helper |
| P2-2 | CI was red for 10+ consecutive runs; `ghcr.io/globalcan/donna:latest` never actually existed | **FIXED** | 133 ruff errors cleaned in one pass; image now publishing |
| P2-3 | `sops -e` against `.sops.yaml` path_regex fails on Windows sops 3.12 (works on Linux sops 3.9) | **DEFERRED — workaround** | `ren .sops.yaml .sops.yaml.bak` + explicit `--age <recipients>` to encrypt; restore the file after. Follow-up: path_regex slash-separator agnostic |
| P2-4 | Docs' `sops -e file > out` command matches path_regex against INPUT not output; always misses the rule | **FIXED** | `docs/MORNING_START.md` §6, `secrets/README.md` — use `--filename-override` |
| P2-5 | Plaintext-secrets example used dotenv (`KEY=VALUE`) while entrypoint parses YAML (`KEY: VALUE`) | **FIXED** | same as P2-4 |
| P2-6 | `entrypoint.sh` swallowed sops errors and silent-success'd empty-keys into an env-less container | **FIXED** | `scripts/entrypoint.sh` — captures exports, validates non-empty mapping + ≥1 `[A-Z_]+` key, aborts with FATAL on any failure |

### Image / Dockerfile

| # | Bug | Status | Where |
|---|---|---|---|
| P2-7 | `ModuleNotFoundError: No module named 'yaml'` — PyYAML not in deps; entrypoint's YAML parser can't load | **FIXED** | `pyproject.toml` — added `pyyaml>=6.0` |
| P2-8 | `alembic upgrade head` failed with `No 'script_location' key` — `alembic.ini` + `migrations/` not in image | **FIXED** | `Dockerfile` — added `COPY alembic.ini` + `COPY migrations/` |
| P2-9 | Container `bot` UID (10001) mismatches host `bot` UID (1001); `/etc/bot/age.key` and `/data/donna` unreachable from container | **MITIGATED — hacks in place** | Host-side `chmod 644 /etc/bot/age.key` + `chmod 777 /data/donna`. Follow-up: add `user: "1001:1001"` to `docker-compose.yml` |
| P2-10 | `arizephoenix/phoenix:latest` shipped broken upstream (their own `ModuleNotFoundError`) | **DISABLED — temp** | Phoenix service commented out in `docker-compose.yml`. Bot/worker log unreachable-endpoint warnings. Follow-up: pin to a known-working tag |

### `.env` / runtime

| # | Bug | Status | Where |
|---|---|---|---|
| P2-11 | `.env.example` ships `DONNA_DATA_DIR=./data`, which the container resolves to the read-only rootfs | **FIXED — prod .env set to `/data`** | Follow-up: flip the default; have dev mode override |
| P2-12 | `docker compose exec bot botctl` bypasses entrypoint; inline comments in `.env` become the env var value; pydantic int parsing fails | **WORKAROUND** | Use `docker compose exec bot /entrypoint.sh botctl …`. Follow-up: ship `botctl` wrapper or strip comments on `.env` creation |
| P2-13 | Bot's async drain tasks died during early DB-unreachable period and didn't auto-restart | **FIXED — restart recovers** | `docker compose restart bot` revived them. Follow-up: make drain tasks self-restart on transient `OperationalError` |
| P2-14 | `botctl jobs` truncates IDs to 18 chars; `botctl job <truncated>` returns "not found" | **OPEN** | `src/donna/cli/botctl.py:53` — `j.id[:18]`. Follow-up: accept prefix match in `get_job` or widen display |

### Security

| # | Bug | Status | Where |
|---|---|---|---|
| P2-15 | Original backup age key private half was shown in a chat transcript during the "offline backup" walkthrough | **FIXED — rotated** | `.sops.yaml` — swapped backup recipient to a freshly-generated keypair |

### Open follow-ups from Phase 2 (not blocking)

- **No off-droplet backups.** Current state is "one SQLite file on one droplet." DO droplet snapshots would cover OS-level loss; nightly rsync to laptop + OneDrive would cover age-key loss. Not configured yet.
- **`donna-update.timer` not enabled.** Systemd unit was created by `harden-droplet.sh` but never `systemctl enable --now`'d. Every deploy is manual `git pull && docker compose pull && up -d` until this is flipped.
- **`user: "1001:1001"` in compose.** P2-9 workaround.
- **`botctl` ergonomics.** P2-12 + P2-14 both want resolving.
- **Phoenix re-enable with pinned tag.** P2-10.
- **`.sops.yaml` path_regex slash-agnostic.** P2-3.

## v0.3.1 — Codex review absorbed + Phase 2 cleanup pass (2026-04-23)

Same-day follow-up after v0.3.0 went live. Codex (GPT-5.4) adversarial review
identified three latent bugs; all fixed and validated against the running droplet.

### Codex latent bugs — FIXED in v0.3.1

| # | Bug | Status | Where |
|---|---|---|---|
| C-1 | Discord adapter drainers spawned with bare `asyncio.create_task` and dropped handles; one transient exception silently kills task and container stays "up" but deaf | **FIXED** | `discord_adapter.py::_supervise` wraps each drainer in restart loop with capped exponential backoff |
| C-2 | `/cancel` flips DB status but agent loop never polls; jobs run to natural end_turn through model + tool steps anyway | **FIXED** | `agent/context.py::JobCancelled` + `check_cancelled()`; modes call at iteration boundaries; validated live |
| C-3 | `botctl jobs --since` declared but unused; watchdog directs operators to a lying flag during incidents | **FIXED** | `memory/jobs.py::recent_jobs(since=)` + `cli/botctl.py::_parse_since`; validated 1h/24h/all |

### Phase 2 follow-ups previously OPEN — now FIXED in v0.3.1

| # | Bug | Status |
|---|---|---|
| P2-9 | Container `bot` UID 10001 vs host UID 1001 — chmod hacks needed | **FIXED** by PR #7 (`user: "1001:1001"` override) + one-time `docker run alpine chown` migration to fix existing files |
| P2-10 | Phoenix `:latest` broken upstream | **PARTIAL** — pinned 14.9.0 in PR #8 ALSO broken; re-disabled in PR #9 entirely. New OPEN: pick a working older tag or swap to Tempo/Jaeger |
| P2-12 | `docker compose exec bot botctl` bypasses entrypoint, fails on `.env` comments | **FIXED** by PR #7 (Dockerfile shadows botctl with shell wrapper that forwards through entrypoint; `.env.example` scrubbed of inline comments) |
| P2-13 | Bot drain tasks die during transient DB issues, don't auto-restart | **FIXED** by PR #9 (`_supervise` with backoff) |
| P2-14 | `botctl jobs` truncates IDs incompatible with `botctl job <id>` | **FIXED** by PR #7 (full IDs shown; prefix-match accepted in `botctl job`) |

### Smoke tests passing live against droplet (2026-04-23)

- Basic DM round-trip — green
- Web-tool summarize Wikipedia — green
- Prompt-injection taint test — green (`tainted=⚠️` flag on web jobs)
- Consent ✅/❌ flow — green (real `save_artifact` tool ran, markdown report
  persisted to `/data/donna/artifacts/<sha256>.blob` with intact DB row)
- `/cancel` via DB flip → agent halted within one iteration after 18 tool
  calls — green
- `botctl jobs --since` returns correct counts for 1h/24h/all — green
- Multi-tool agent loop survived 19 tool calls in one job — green
- Slash commands in DMs — pending Discord CDN propagation post-PR-#10
  (~1h after merge first time)

### Backups — FIXED in v0.3.2 (2026-04-23)

Codex priority-#1 finding closed. Three-layer setup, ~$0.30/mo marginal
cost (see `docs/OPERATIONS.md` §Disaster recovery for install + restore):

- **Layer 1: DO snapshots** — web-console-configured, daily, 4-week retention
- **Layer 2: droplet cron** — `scripts/donna-backup.sh` @ 03:00 UTC, uses
  `python3 -c 'sqlite3.Connection.backup()'` for WAL-safe snapshot so bot user
  never needs sudo. Tarballs snapshot + artifacts into
  `/home/bot/backups/donna-<stamp>.tar.gz` + `donna-latest.tar.gz` symlink;
  7-day local retention
- **Layer 3: laptop Task Scheduler** — `scripts/donna-fetch-backup.ps1`
  @ 06:00 local, scps latest into `%USERPROFILE%\OneDrive\Donna-Backups\`;
  OneDrive cloud sync auto-replicates to a 4th location; 30-day retention

Validated live 2026-04-23: droplet dry-run produced 224KB tarball, laptop
manual pull landed in OneDrive folder, scheduled task registered with next
run 06:00 local.

## v0.3.3 — Codex adversarial round 2 + Jaeger swap (2026-04-24)

Second targeted Codex (GPT-5.4) adversarial scan after the two FTS5
injection fixes in v0.3.2. Nine findings, all legitimate, all fixed same
day. Plus Phoenix → Jaeger swap (broken upstream).

### Codex adversarial round 2 — ALL 9 FIXED

| # | Category | Finding | PR | Severity |
|---|---|---|---|---|
| 1 | FTS5 sibling | `facts.search_facts_fts` had same injection as `keyword_search` | #19 | high |
| 2 | Untrusted content | `fetch_url` no content-type / size guard | #20 | high |
| 3 | Untrusted content | `ingest_discord_attachment` no byte/page/char cap | #20 | high |
| 4 | Taint propagation | `recall` taint nested in `results[]`, JobContext misses it | #21 | high |
| 5 | Taint propagation | `teach` / `propose_heuristic` missing from `TAINT_ESCALATED_TOOLS` | #21 | high |
| 6 | Crash safety | `validate_grounded` assumes dict from `json.loads` | #22 | med |
| 7 | Crash safety | `debate.run_debate_in_context` `int(rounds)` unguarded | #22 | med |
| 8 | State machine | `consent.check` wait loop ignores `/cancel` | #22 | med |
| 9 | ReDoS | `_has_substring_overlap` O(n*m) on unbounded text | #22 | med |
| 10 | Ownership | `_persist_pending` no owner guard on writes | #23 | med |

(#10 was Codex's final one, deferred one round because "bigger" — landed
in v0.3.3 alongside the rest.)

### Phoenix → Jaeger (PR #25)

`arizephoenix/phoenix:14.x` ships a broken image upstream. Swapped to
`jaegertracing/all-in-one:1.60` — same OTLP-gRPC port (4317), hostname
rename is the only real change. UI at `:16686` via SSH tunnel. Tradeoff
documented: Jaeger is generic distributed tracing (not LLM-native),
in-memory storage by default (audit spans still land in `traces` SQLite
table). Phoenix re-enable path documented in `docker-compose.yml` for
when they fix their image.

### Added — backup verifier (PR #24)

`scripts/donna-verify-backup.sh` — lightweight restore drill. Extract
tarball, `PRAGMA integrity_check` + `foreign_key_check`, row counts on
core tables, SHA-256 verify every artifact blob against its filename.
Validated live against a 2.6MB tarball with 402 Huck Finn chunks: all
green.

### Validated live (2026-04-24)

- Three-layer backup + verify loop on real prod data (Huck Finn corpus)
- Grounded mode with `?`-terminated query runs to completion (FTS5 fix)
- Jaeger UI responds 200 on `:16686`; bot trace export clean
- Slash commands visible in Discord DM post-PR-#10 CDN propagation
- 102 tests green on Py 3.12 (CI) / locally

### Still open

- **Full quarterly restore drill** — tarball verifier covers the "data
  is restorable" case weekly; full throwaway-droplet drill (boot bot +
  DM test) remains quarterly. Needs Discord-token juggling (~5 min
  downtime).
- **Tailscale** for narrowing public port 22 — lockout risk if
  misconfigured; weekend task with DO console as recovery
- **Auto-update timer** — unblock requires full restore drill per Codex
  rule. Currently manual deploys.
- **Phoenix re-enable path** documented; one-line swap back if their
  image is fixed
- ~~**`botctl forget-artifact <id>`** — currently manual SQL DELETE + `rm`~~ **FIXED** on `claude/load-up-setup-7XtVU` (`src/donna/cli/botctl.py::forget_artifact` + `tests/test_botctl_forget_artifact.py`). 1:1 row/blob assumption pinned by UNIQUE-sha256 invariant test; dangling `knowledge_sources.source_ref` gets a warning, not a block.
- **Speculative / debate modes** never smoke-tested in prod
- **`botctl teach`** ingest pipeline validated via direct CLI; Discord-
  initiated `/teach` slash command not yet exercised

### Deferred from Codex round-2 review (2026-04-24)

Two of Codex's round-2 findings were real but deferred; see CHANGELOG
[0.3.4] for the five shipped same-night.

- **#3: FTS5 tokenizer drops identifier punctuation.** Queries like
  `C++`, `BRK.B`, `node.js`, `gpt-4o` lose their punctuation through
  `fts_sanitize` (tokenizes via `\w+`). The sanitizer's behavior is
  *consistent* with FTS5's default `unicode61` tokenizer (both sides
  strip the same punctuation), so searches still match documents that
  contain the same words. But literal-punctuation queries can't be
  expressed as exact-match — a search for `C++` matches anything with
  `c` in it. Fix requires an FTS5 tokenizer swap (migration work),
  not a sanitizer change. Defer until a real user query gets false
  hits in prod.
- **#6: `test_debate_rounds_coercion` is a tautology.** The crash-
  guards test reimplements the coercion logic inline rather than
  calling `run_debate_in_context`. Any future regression in
  `debate.py` wouldn't trip the test. Rewrite as a JobContext-stub
  test driving the real entrypoint. Non-urgent — the fix is valid,
  only the test binding is weak.

## v0.4.0 — Cross-vendor review pass (2026-04-29)

Three reviewer passes + one market research synthesis against HEAD
`0149002`. Full triangulation in
[`REVIEW_SYNTHESIS_v0.4.0.md`](REVIEW_SYNTHESIS_v0.4.0.md). Individual
reviews:

- [`CODEX_REVIEW_DONNA_v0.4.0.md`](CODEX_REVIEW_DONNA_v0.4.0.md) — Claude Opus 4.7 leg
- [`CODEX_REVIEW_DONNA_v0.4.0_GPT5.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT5.md) — GPT-5 leg (default, ChatGPT auth)
- [`CODEX_REVIEW_DONNA_v0.4.0_GPT53CODEX.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT53CODEX.md) — GPT-5.3-codex leg (API mode); surfaced 2 net-new findings
- [`CODEX_REVIEW_DONNA_v0.4.0_GPT55PRO.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT55PRO.md) — GPT-5.5-pro attempt (TRUNCATED, OpenAI quota hit at 296K tokens)
- [`REVIEW_COMPARISON_GPT5_VARIANTS.md`](REVIEW_COMPARISON_GPT5_VARIANTS.md) — three-model side-by-side

### Codex (GPT-5) cross-vendor red flags — NEW

GPT-5 (default, ChatGPT auth) independently surfaced seven red flags
Claude missed. All spot-checked against current code in the synthesis
pass.

| # | Severity | Finding | Where |
|---|---|---|---|
| C-RF-1 | **CRITICAL** | Internal retrieval bypasses taint propagation. `recall_knowledge` checks `knowledge_sources.tainted`; internal `retrieve_knowledge` calls in every mode don't | `agent/loop.py:55-62`, `modes/grounded.py:73`, `modes/speculative.py:45-55`, `modes/debate.py:104-111`, `tools/knowledge.py:54-87` |
| C-RF-2 | **HIGH** | Debate mode lacks per-turn checkpoint. Worker crash mid-debate loses every prior turn | `modes/debate.py:98-176` |
| C-RF-3 | **HIGH** | `work_id` not propagated from source to chunk rows. Retrieval diversity collapses unrelated NULL-`work_id` sources into one bucket | `ingest/pipeline.py:48-60,107-120`, `modes/retrieval.py:156-171` |
| C-RF-4 | MED | Plan/implementation drift on tainted `send_update`. PLAN says tainted updates need confirmation; tool has no escalation flag | `docs/PLAN.md:94,159`, `tools/communicate.py:27-52`, `security/taint.py:19-27` |
| C-RF-5 | MED | Attachment ingest temp-file race. Fixed `attach{ext}` path; concurrent ingests with same extension collide | `tools/attachments.py:82-85` |
| C-RF-6 | MED | Stale-worker exception path writes `FAILED` without owner guard. Symmetric to v0.3.3 #23 fix that was missed here | `jobs/runner.py:60-67`, `memory/jobs.py:141-176` |
| C-RF-7 | MED | Sanitizer model spend not attributed to jobs. Per-job cost in `botctl cost` undercounts by `sanitize_untrusted` calls | `security/sanitize.py:35-68`, `memory/cost.py:38-72` |

Plus one architectural call Claude's scorecard missed:

- **`checkpoint_state` opaque JSON blob, not first-class step state**.
  `types.py:60-104` + `memory/jobs.py:84-138`. Why replay/fork/eval
  drift and mid-debate recovery are all awkward. ⚠️ reconsider when the
  step-state work in C-RF-2 lands.

### Codex (GPT-5.3-codex) cross-vendor red flags — NET-NEW vs GPT-5

GPT-5.3-codex on a second pass against the same prompt independently
surfaced two findings that neither Claude nor GPT-5 caught:

| # | Severity | Finding | Where |
|---|---|---|---|
| C53-RF-1 | **HIGH** | **Scheduler duplicate-fire across multiple workers.** Each worker process starts its own scheduler thread with no leadership lock; two workers fire same cron tick twice. Sharper concrete bug behind Claude §8.1 generic worker-leadership concern | `worker.py:46`, `jobs/scheduler.py:35`, `memory/schedules.py:40` |
| C53-RF-2 | MED | **Denied / unknown / disallowed tool calls not audited.** When tool call rejected (consent denied, unknown tool, not allowlisted), error block returns to model but no row inserted in `tool_calls`. Operator can't audit attempted bypasses | `agent/context.py:200,208,253` |

GPT-5.3-codex also raised the severity on three findings GPT-5 had
softer reads on:

- Mode dispatch (`if/elif` in `loop.py`): ⚠️ reconsider (vs GPT-5's ✅)
- Cache-aware composition: ⚠️ "incomplete" (vs GPT-5's ✅ keep with concern)
- `agent_scope` flat string: ❌ change (vs Claude's ⚠️; GPT-5 also said ❌)

### Claude (Opus 4.7) red flags — verified by Codex spot-check

10 red flags from Claude's review. All confirmed real against current
code. Index of the file:line citations is the table in
[`REVIEW_SYNTHESIS_v0.4.0.md`](REVIEW_SYNTHESIS_v0.4.0.md) §1.3.

### Claude claims that were factually wrong

| Claim | Reality |
|---|---|
| §4 #2 "build subprocess-isolated `run_python`" | Already shipped at `tools/exec_py.py:39-73` (`asyncio.create_subprocess_exec(sys.executable, "-I", "-B", ...)` + scrubbed env + 30s timeout + 64KB cap). DROP. |
| §4 #1 / §1.8 "no evaluation harness" | Scaffold exists at `evals/runner.py` + 3 golden YAMLs. Correct framing: "scaffold exists, isn't a ratchet" — `_run_one()` returns `True` for non-`live` cases without exercising assertions (`evals/runner.py:41-49`). |

### Verification-pass fresh findings (2026-04-28, prior to Codex pass)

- **F1: `_execute_one` exception leakage.** Same shape as Claude §8.3.
  Tools with `taints_job=True` can have attacker-controlled bytes in
  their exception strings; `agent/context.py:237-241` substitutes
  `str(e)` into both audit row and tool_result. Fix: fixed-string
  error messages on tainting tools.
- **F2: Eval harness scaffold reports PASS without assertions.**
  `_run_one` returns `True` when `cap in ("grounded","speculative")`
  and not `live`. Mark as SKIP not PASS, or add structural checks.
- **F3: Volatile-block tokenization affects all retrieval, not just
  retry.** `compose.py` puts chunks in volatile block for all modes;
  fix at compose layer once.
- **F4: Taint pre-scan is registry-driven, not input-driven.**
  `context.py:163-171` works because all current taint is static.
  Future dynamic-taint tools would slip past pre-scan in same parallel
  batch.

### Action queue — ranked merge of all sources (status as of v0.4.2)

Top 19 items in the merged queue live in
[`REVIEW_SYNTHESIS_v0.4.0.md`](REVIEW_SYNTHESIS_v0.4.0.md) §5. **8 of 19
shipped between v0.4.1 and v0.4.2.** Status:

1. ✅ **Internal retrieval taint propagation** (C-RF-1) — v0.4.1 PR #37
2. ✅ **Eval scaffold → ratchet** — v0.4.1 PR #38
3. ⏸ **`agent_scope` first-class** — deferred (M-L; schema decision)
4. ⏸ **Scheduler leadership lock** (C53-RF-1) — deferred (multi-worker
   not real yet for solo bot)
5. ⏸ **Step-level checkpoint/replay/fork** — deferred (M; design call)
6. ⏸ **`/validate` URL critique only** — **NEXT IN QUEUE** when operator
   says go (~3-4 days)
7. ✅ **`work_id` propagation fix** — v0.4.1 PR #39
8. ✅ **Session memory across Discord threads** — **v0.4.2 Bundle 1**
9. ✅ **Sanitizer cost attribution** — v0.4.1 PR #42
10. ⏸ **Claim objects + span drilldown for grounded UI** — fold into #6

Items 11-19 status:

- ⏸ Bitemporal facts (#11) — defer (no use case yet)
- ✅ Stale-worker FAILED-write owner guard — v0.4.1 PR #40
- ✅ **Denied-tool audit gap** (C53-RF-2) — v0.4.1 PR #41
- ✅ **`send_update` policy fix** — v0.4.2 Bundle 1 (PLAN.md updated to
  match audit-flag-only design)
- ✅ Attachment temp-file race — v0.4.1 PR #40
- ⏸ Tainted-fact quarantine — defer (low-leverage defensive)
- ⏸ Streaming Discord delivery — defer (perceived-latency win, not real)
- ⏸ Jaeger LLM-span custom view — defer (debugging luxury)
- ⏸ Proactive knowledge surfacing — fold into scheduled-tasks work

### Bundle 1 — operator production friction (v0.4.2, 2026-04-30)

Beyond the cross-vendor review queue, the operator reported four daily
annoyances after using the bot in real life:

| # | Symptom | Fix | PR |
|---|---|---|---|
| B1-1 | Mobile (iOS) Discord answers were wall-of-text | `_DISCORD_MSG_LIMIT` 1900→1400 + `_normalize_for_mobile` (collapse blanks, strip trailing whitespace, tabs→spaces) | #45 |
| B1-2 | "No memory" — every `/ask` was a fresh context | Wired the existing `messages` table: writes in `JobContext.finalize` for clean+thread, reads in `compose_system` via new `session_history` kwarg, capped at last 8 messages, tainted jobs skip writes | #45 |
| B1-3 | Operator didn't know `/schedule` existed (shipped v0.2.0, never live-validated) | `/schedule` + `/schedules` rendering improvements + `docs/SCHEDULER_SMOKE_TEST.md` runbook | #45 |
| B1-4 | `send_update` PLAN spec drift (queue #14) | PLAN.md updated to match the audit-flag-only design | #45 |

15 new tests in `tests/test_bundle1_feels_like_it_works.py`. 359 / 359
pass.

### v0.4.3 follow-ups — bugs surfaced by the live smoke test (2026-04-30)

The Bundle 1 smoke runbook didn't just make the scheduler discoverable
— running it for the first time uncovered three latent shipping bugs
that had been present since v0.2.0 and v0.4.2 respectively:

| # | Symptom | Fix | PR |
|---|---|---|---|
| V43-1 | **Scheduler delivery silently broken since v0.2.0.** Jobs ran to `status=done` but no Discord message arrived. `Scheduler._fire` created jobs with `thread_id=NULL`, the adapter's `_resolve_channel_for_job` returned None, and `_post_update` returned False — replies piled up undeliverable in `outbox_updates`. The `schedules` table didn't even have a column to remember the originating channel. | Migration `0006_schedules_thread_id`; `/schedule` captures current channel via `get_or_create_thread`; `Scheduler._fire` propagates `thread_id` to `insert_job`; `botctl schedule add --discord-channel` for CLI parity; bonus UX hint when operator forgets cron field spaces (`*****` vs `* * * * *`). | #47 |
| V43-2 | **Plain-DM session memory wrote duplicate user rows.** `_handle_new_task` inserted a user message at intake; `JobContext.finalize` wrote it again at completion. Pre-fix every plain DM produced 3 message rows (user/user/assistant), and the second job's `session_history` saw the current task as a prior turn — confusing the model. | Drop the adapter's intake `threads_mod.insert_message` call; finalize is the sole writer (matching how `/ask`, `/speculate`, `/debate` already worked). 3 new tests in `test_plain_dm_memory_dedup.py`. | #48 |
| V43-3 | **Migrations didn't auto-run on container restart.** Entrypoint just decrypted secrets and exec'd the command, so any deploy that included a schema migration silently no-op'd until an operator manually ran `alembic upgrade head`. Discovered when the v0.4.3 deploy didn't pick up migration 0006. | `entrypoint.sh` runs `alembic upgrade head` for `DONNA_PROCESS_ROLE` ∈ {bot, worker} before exec'ing the service. Idempotent (locks via SQLite, second-runner sees "already at head"). Container fails to start on migration error rather than running with a stale schema. | #48 |

**Validation:** scheduler smoke test passed end-to-end against the
fixed image; `• SCHED_OK` arrived in DM after the schedule was created
via `/schedule * * * * *`. 366 tests pass, ruff clean.

### v0.5.0 follow-ups — Slack adapter retool (2026-05-01)

The platform migration from Discord to Slack shipped clean (4/4 critical
smoke tests green) but surfaced or left several issues for v0.5.1:

| # | Symptom / gap | Status | Notes |
|---|---|---|---|
| V50-1 | **`not_in_channel` infinite retry storm.** When the bot tries to deliver an outbox row to a channel it isn't a member of, `_post_update` returns False, the row stays, and the drainer retries every ~1.5s **forever**. Hit during smoke when a stale outbox row from a pre-rename `/ask` test couldn't deliver to its originating channel. Operator had to manually `DELETE FROM outbox_updates` to stop the spam. | Open | Should detect non-retryable Slack errors (`not_in_channel`, `channel_not_found`, `is_archived`, `account_inactive`) and either drop the row or move to a dead-letter table. v0.5.1. |
| V50-2 | **Channel-target scheduling untested live.** Feature shipped (`schedules.target_channel_id` + modal channel selector) but only DM-target validated in the v0.5.0 smoke. | Open | Requires inviting Donna to a channel via Integrations → Add apps. Will validate when next adding a real `#morning-brief`-style channel. |
| V50-3 | **`@donna` channel mentions untested live.** Same root cause (channel invite gate). The `app_mention` event handler is shipped but unexercised in prod. | Open | Validate alongside V50-2. |
| V50-4 | **Slack reserves bare slash command names.** Workspace rejected `/ask`, `/status`, `/history`, etc. as "invalid name" even with no other apps installed. Forced `/donna_*` prefix on all 12 commands. | Worked-around | Slightly more typing for the operator. Acceptable trade-off for solo-bot. |
| V50-5 | **Slack "Reinstall to Workspace" doesn't always rotate the bot token.** Operator hit this when trying to rotate after accidentally pasting tokens in chat. Real rotation requires "Revoke All OAuth Tokens" → reinstall. | Documented | Caught in WAKE_UP doc; operator successfully rotated via the explicit-revoke path. |
| V50-6 | **Slack DM autocomplete only shows partial slash command list.** Operator's DM with Donna autocompletes `/donna_ask` only; channel autocomplete shows all 12. All commands work in DM regardless — Slack's UI just truncates the suggestions panel. Cosmetic. | Wontfix-by-Donna | Slack-side UX choice. |
| V50-7 | **Validator footer renders `:warning:` as text in Slack.** The `⚠️ partial validation` badge sometimes shows as `:warning: partial validation` due to Slack's emoji shortcode handling adjacent to formatting. | Open | Cosmetic. Either substitute Unicode emoji directly or use Block Kit emoji elements explicitly. v0.5.1 polish. |
| V50-8 | **Dual-field memory deferred.** Codex's recommended next iteration: persist `raw_content` (audit) + `safe_summary` (prompt-side rendering) for tainted assistant rows, instead of storing the raw and rendering with a wrapper as v0.4.4 does. | Deferred | v0.5.1 product work. |
| V50-9 | **`secrets/prod.enc.yaml` updated on droplet but not pushed to GitHub.** Droplet's deploy key is read-only by design; sops edit committed locally but `git push` fails. | Documented | Operator can flip deploy key writable, push, flip back. Not blocking — runtime reads from local file via bind mount. |

**Validation:** v0.5.0 smoke 4/4 green in operator's personal Slack workspace. DM intake, `/donna_ask` grounded with citations, `/donna_schedule` modal + delivery, Block Kit consent buttons all work. 373 tests pass, ruff clean.

### Market-research factual corrections

Two items in the original brief that drove the market research pass
were wrong; downstream docs should correct:

- "OpenClaw / Nov-2025 / 300+ skills" → **ClawHavoc / Jan-Feb 2026 /
  341→1184 skills / 346k stars / CVE-2026-22708**
- Hermes "Pattern A/B" terminology → **UNVERIFIED**, no primary source.
  Treat as folklore; adopt Hermes MCP-hygiene primitives directly.

### Newly closed by this pass

- **PR #36 framing:** Claude review under misleading filename. File
  retained as historical record; corrections block added at top
  pointing to genuine Codex review and synthesis.
- **§4 #2 subprocess `run_python` recommendation:** marked OBSOLETE;
  not work to do.
