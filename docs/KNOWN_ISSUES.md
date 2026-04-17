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
