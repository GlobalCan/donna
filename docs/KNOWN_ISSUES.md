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
| P1-3 | Chat mode's `final_text` orphaned — agent's answer never delivered to Discord | **FIXED** | `agent/loop.py::_enqueue_final_text` writes to `outbox_updates` on mode exit |

### Open follow-ups from Phase 1 (not blocking)

- **Wikipedia 403 on fetch_url** — `DonnaBot/0.1 (+personal)` UA is policy-compliant but Wikipedia has gotten stricter. Agent falls back to Tavily + non-Wikipedia source, so not blocking. Fix: beef up UA string with contact URL.
- **1500-char truncation on send_update** — long-form summaries get cut mid-sentence. Real fix: save long outputs as artifact, update the agent prompt to send a pointer + short excerpt rather than full text.
- **Other modes likely have the same orphaned-final-text hole.** Chat mode was fixed in `_run_chat`; grounded/speculative/debate each have their own exit path. Will surface when those modes' smoke tests run.

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
