# Codex Deep Dive — Donna v0.4.0 — GPT-5.3-codex Cross-Vendor Review

> Reviewer: OpenAI Codex CLI (gpt-5.3-codex), session
> `019dda*`, 2026-04-29. Ran the same prompt as the GPT-5.5 review
> in [`CODEX_REVIEW_DONNA_v0.4.0_GPT5.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT5.md);
> distinct findings + comparison are in
> [`REVIEW_COMPARISON_GPT5_VARIANTS.md`](REVIEW_COMPARISON_GPT5_VARIANTS.md).
> The model self-titled this `GPT-5.4 Cross-Vendor Review` because the
> prompt's output-format spec used that label as a placeholder; the
> actual model is gpt-5.3-codex per the codex-cli session metadata.

## 1. Executive summary
- Broadly: I **agree with Claude’s thesis**, but I disagree on a few severities and on some “missing” framing (notably eval harness and `run_python`).
- The strongest architecture choices still hold: unified `JobContext` and atomic finalize+outbox are real quality differentiators ([context.py:304](/C:/dev/donna/src/donna/agent/context.py:304), [context.py:335](/C:/dev/donna/src/donna/agent/context.py:335)).
- Biggest current security gap is **internal retrieval taint bypass**: tool wrapper propagates taint, mode-internal retrieval does not ([knowledge.py:54](/C:/dev/donna/src/donna/tools/knowledge.py:54), [grounded.py:73](/C:/dev/donna/src/donna/modes/grounded.py:73), [speculative.py:49](/C:/dev/donna/src/donna/modes/speculative.py:49), [debate.py:104](/C:/dev/donna/src/donna/modes/debate.py:104)).
- Biggest product gap remains eval ratchet quality: scaffold exists, but default path still returns `True` for non-live grounded/speculative ([evals/runner.py:46](/C:/dev/donna/evals/runner.py:46), [evals/runner.py:49](/C:/dev/donna/evals/runner.py:49)).
- “Two workers corrupt state” is directionally right but imprecise: the sharper issue is **duplicate scheduler firing** plus some stale-worker write paths ([worker.py:34](/C:/dev/donna/src/donna/worker.py:34), [scheduler.py:40](/C:/dev/donna/src/donna/jobs/scheduler.py:40), [runner.py:66](/C:/dev/donna/src/donna/jobs/runner.py:66)).
- Strategic time-bomb: `agent_scope` remains a flat string controlling prompt/tool behavior without first-class scope policy object ([0001_initial_schema.py:50](/C:/dev/donna/migrations/versions/0001_initial_schema.py:50), [prompts.py:13](/C:/dev/donna/src/donna/memory/prompts.py:13)).
- Non-obvious moat call stands: quoted-span structural grounding + overflow compartmentalization are strong primitives ([validator.py:168](/C:/dev/donna/src/donna/security/validator.py:168), [discord_adapter.py:397](/C:/dev/donna/src/donna/adapter/discord_adapter.py:397)).

## 2. Architectural scorecard

| Decision | Codex verdict | Claude verdict | Agree? | Why if not |
|---|---|---|---|---|
| 1) Hand-rolled vs frameworks | ✅ keep (re-eval at v1.0) | ✅ | Yes | Current code quality is disciplined enough; framework swap is still premature. |
| 2) Unified `JobContext` | ✅ keep | ✅ | Yes | Still load-bearing ([context.py:50](/C:/dev/donna/src/donna/agent/context.py:50)). |
| 3) `if/elif` mode dispatch | ⚠️ reconsider | ✅ | **No** | At N=4 it works, but adding `/validate` + THINK integration makes registry-based mode objects worth doing ([loop.py:27](/C:/dev/donna/src/donna/agent/loop.py:27)). |
| 4) SQLite as source of truth | ✅ keep | ✅ | Yes | Right for solo; strengthen scheduler singleton discipline. |
| 5) `agent_scope` flat string | ❌ change | ⚠️ | **No** | I rate this higher severity: scope policy/prompt/permissions are too loosely coupled ([0001_initial_schema.py:50](/C:/dev/donna/migrations/versions/0001_initial_schema.py:50), [prompts.py:13](/C:/dev/donna/src/donna/memory/prompts.py:13)). |
| 6) Discord-only | ✅ keep | ✅ | Yes | Correct constraint for current operator model ([main.py:12](/C:/dev/donna/src/donna/main.py:12)). |
| 7) Outbox polling pattern | ✅ keep | ✅ | Yes | Durable and correct cross-process shape ([context.py:335](/C:/dev/donna/src/donna/agent/context.py:335), [discord_adapter.py:264](/C:/dev/donna/src/donna/adapter/discord_adapter.py:264)). |
| 8) Taint per-job boolean | ⚠️ reconsider sooner | ⚠️ | Partial | Agree on issue; I’d pull forward due internal retrieval bypass in current modes. |
| 9) Quoted-span structural validator | ✅ keep | ✅ | Yes | Good v1 tradeoff; add typed failure outcomes. |
| 10) `ModelRuntime` pricing registry | ✅ keep | ✅ | Yes | Solid abstraction-as-data choice ([runtimes.py:38](/C:/dev/donna/src/donna/memory/runtimes.py:38), [cost.py:20](/C:/dev/donna/src/donna/memory/cost.py:20)). |
| 11) Cache-aware composition | ⚠️ reconsider composition granularity | ✅ | **No** | Only stable prefix cached; retrieval chunks are always volatile ([compose.py:51](/C:/dev/donna/src/donna/agent/compose.py:51), [compose.py:71](/C:/dev/donna/src/donna/agent/compose.py:71)). |
| 12) Overflow-to-artifact | ✅ keep | ✅ | Yes | Strong pattern; keep and generalize ([discord_adapter.py:377](/C:/dev/donna/src/donna/adapter/discord_adapter.py:377)). |
| 13) Compaction summarization + audit artifact | ⚠️ keep with guardrails | ✅ | Partial | Drift/stranding risks are real (`last 20` refs, summary-of-summary) ([compaction.py:129](/C:/dev/donna/src/donna/agent/compaction.py:129)). |

**Load-bearing decisions Claude missed**
- Scheduler co-located in every worker process without leadership lock ([worker.py:34](/C:/dev/donna/src/donna/worker.py:34), [scheduler.py:40](/C:/dev/donna/src/donna/jobs/scheduler.py:40)).
- `checkpoint_state` as opaque JSON blob (harder replay/fork/eval introspection) ([types.py:75](/C:/dev/donna/src/donna/types.py:75), [jobs.py:84](/C:/dev/donna/src/donna/memory/jobs.py:84)).

## 3. Field positioning
- **C.1 taxonomy**: EXTEND. Useful framing, but “empty quadrant” is overstated; it’s better called “under-served,” not empty.
- **C.2 axes**: partial AGREE. Strongest axes for Donna are self-host + explicit security posture + claim-level provenance. I DISAGREE with “Donna tenets fit only bitemporal”; you can get most value with lighter invalidation metadata first.
- **C.3 steal list**: mixed. I AGREE on MCP hygiene and stricter schema boundaries; I DISAGREE on front-loading Graphiti/Mem0 taxonomy for solo v0.x.
- **C.4 avoid list**: mostly AGREE.
- **C.6 validation tools**: AGREE for `/validate` v1: Google Fact Check + Perplexity Sonar are practical defaults; Kagi optional.
- **C.7 niche claim**: EXTEND. Defensible niche is real, but not yet fully occupied until per-claim status rendering and stronger memory versioning ship.
- **C.8 caveats**: AGREE (especially correcting OpenClaw/ClawHavoc framing).

## 4. Top 10 recommended additions

| # | Codex | Claude | Same idea? |
|---|---|---|---|
| 1 | Fix internal retrieval taint propagation in mode paths (S, very high, low) | Eval harness | No |
| 2 | Make eval harness a real ratchet (`SKIP` vs `PASS`, structural assertions) (S, very high, low) | Subprocess `run_python` | No |
| 3 | Scheduler leadership lock + dedupe-safe firing (M, high, medium) | Grounded chunk caching on retry | No |
| 4 | Per-turn debate checkpoints (S-M, high, low) | Per-scope config table | Partial |
| 5 | First-class `scopes` table (policy + prompt binding) (M, high, medium) | Session memory | Partial |
| 6 | Session memory across jobs in thread (S, high UX, low) | Tainted-fact quarantine | Partial |
| 7 | Redact tainting-tool exception strings + notify on consent timeout (S, high, low) | Streaming Discord delivery | No |
| 8 | Cache retrieval block for grounded retries; typed retry outcomes (XS-S, medium-high, low) | `/validate` URL-only | Partial |
| 9 | Ship `/validate` URL mode as separate `JobMode` (M, high, medium) | Jaeger custom view | No |
| 10 | Tainted-fact quarantine and re-ingestion safeguards (XS-S, medium, low) | Proactive knowledge surfacing | No |

**Disagreement evidence**
- Claude B.4 #2 is obsolete: subprocess-isolated `run_python` is already present ([exec_py.py:45](/C:/dev/donna/src/donna/tools/exec_py.py:45)).
- Internal taint bypass is currently higher priority than several UX features ([grounded.py:73](/C:/dev/donna/src/donna/modes/grounded.py:73), [knowledge.py:54](/C:/dev/donna/src/donna/tools/knowledge.py:54)).
- Scheduler safety is under-addressed for multi-worker reality ([worker.py:46](/C:/dev/donna/src/donna/worker.py:46), [schedules.py:40](/C:/dev/donna/src/donna/memory/schedules.py:40)).

## 5. /validate evaluation
1. **Scope split (URL vs video)**: **AGREE**. Ship URL/article first; video has different ops/cost/failure profile.
2. **Architecture (`JobMode.VALIDATE`)**: **AGREE**. New mode is cleaner than ad-hoc chat orchestration.
3. **Discord output shape**: **EXTEND**. Artifact-first is right, but still post deterministic compact header in-channel (claims checked, support/refute/mixed counts, confidence bands).
4. **Competitive angle**: **AGREE**. Donna’s edge is structural quote verification plus private corpus blending.
5. **Video failure mode**: **AGREE**. Don’t put yt-dlp fragility in the droplet hot path initially.
6. **Taint propagation**: **EXTEND**. Keep Donna-owned taint wrapper, and force sanitize-before-reread on any critique artifact reuse.

## 6. Deep-dive answers
1. **20-char floor**: **AGREE**. Keep 20; make per-scope override only if needed.
2. **Grounded retry prompt**: **EXTEND**. Retry-once is good; add typed terminal status when second attempt fails (`malformed_json`, `bad_citation`, etc.).
3. **1900 tainted overflow threshold**: **AGREE**. Correct default.
4. **Compaction N=20**: **EXTEND**. Keep N=20; add hard cap on compaction generations and preserve more than last-20 artifact refs in lineage metadata.
5. **`agent_scope` first-class**: **AGREE** (strongly).
6. **`facts` vs `knowledge_chunks` split**: **AGREE**. Correct conceptual separation.

## 7. THINK separation review
1. **Boundary (`EvidencePack` in THINK, prose in Donna)**: **AGREE**.
2. **`recall_knowledge` migration to THINK**: **AGREE/EXTEND**. Move retrieval core to THINK but keep Donna wrapper for taint and consent policy enforcement.
3. **402-chunk Huck Finn migration**: **EXTEND**. Prefer dual-read/feature-flag migration before atomic rename cutover to reduce rollback pain.

## 8. Red flags
I am not re-listing Claude’s 10 baseline red flags; most are still present. New/additional red flags:

- **RF1 (critical): internal retrieval taint bypass in mode paths** ([grounded.py:73](/C:/dev/donna/src/donna/modes/grounded.py:73), [speculative.py:49](/C:/dev/donna/src/donna/modes/speculative.py:49), [debate.py:104](/C:/dev/donna/src/donna/modes/debate.py:104), [knowledge.py:65](/C:/dev/donna/src/donna/tools/knowledge.py:65)).
- **RF2 (high): scheduler duplicate fire risk with multiple workers** ([worker.py:46](/C:/dev/donna/src/donna/worker.py:46), [schedules.py:40](/C:/dev/donna/src/donna/memory/schedules.py:40)).
- **RF3 (high): debate has no mid-run checkpoint; crash drops transcript** ([debate.py:98](/C:/dev/donna/src/donna/modes/debate.py:98), [debate.py:66](/C:/dev/donna/src/donna/modes/debate.py:66)).
- **RF4 (high): stale-worker exception path can write terminal status without owner guard** ([runner.py:66](/C:/dev/donna/src/donna/jobs/runner.py:66)).
- **RF5 (medium): consent-denied / unknown-tool / disallowed-tool calls are not persisted to `tool_calls` (audit blind spot)** ([context.py:200](/C:/dev/donna/src/donna/agent/context.py:200), [context.py:208](/C:/dev/donna/src/donna/agent/context.py:208), [context.py:253](/C:/dev/donna/src/donna/agent/context.py:253)).
- **RF6 (medium): `_execute_one` and `_sanitize_hits` leak raw exception strings into model-visible payloads** ([context.py:239](/C:/dev/donna/src/donna/agent/context.py:239), [web.py:122](/C:/dev/donna/src/donna/tools/web.py:122)).
- **RF7 (medium): no cross-job conversational memory is not just schema absence; runtime ignores prior thread history entirely** ([context.py:372](/C:/dev/donna/src/donna/agent/context.py:372), [loop.py:47](/C:/dev/donna/src/donna/agent/loop.py:47)).

## 9. Non-obvious wins

| Claude # | Verdict | Note |
|---|---|---|
| 1 | AGREE | Quoted-span validator is excellent v1 rigor ([validator.py:141](/C:/dev/donna/src/donna/security/validator.py:141)). |
| 2 | AGREE | Overflow compartmentalization is strong and uncommon ([discord_adapter.py:397](/C:/dev/donna/src/donna/adapter/discord_adapter.py:397)). |
| 3 | AGREE | Atomic finalize + outbox insert is correct. |
| 4 | EXTEND | Lease/heartbeat mostly right; stale-worker failure path still needs owner guard ([runner.py:66](/C:/dev/donna/src/donna/jobs/runner.py:66)). |
| 5 | AGREE | Cost on resume sourced from DB is correct ([context.py:365](/C:/dev/donna/src/donna/agent/context.py:365)). |
| 6 | AGREE | Pre-scan taint is smart for static taint tools. |
| 7 | AGREE | Compaction audit artifact is strong. |
| 8 | DISAGREE | Not every untrusted ingress is equivalently sanitized before reuse (attachment ingest persists raw text; taint wrapper asymmetry exists). |
| 9 | AGREE | `botctl` surface is unusually complete for this stage. |
| 10 | AGREE | `JobCancelled` boundary handling is solid ([context.py:116](/C:/dev/donna/src/donna/agent/context.py:116)). |

**Additional wins**
- Owner-guarded checkpoint/status APIs are well-scoped primitives ([jobs.py:84](/C:/dev/donna/src/donna/memory/jobs.py:84), [jobs.py:141](/C:/dev/donna/src/donna/memory/jobs.py:141)).
- Prompt-cache invariants are heavily tested, which is rare in small agent repos.
- Artifact-based provenance plus CLI retrieval gives strong operability without a web UI.

## 10. Disagreements with Claude (consolidated)
- **B.2 #3**: I rate mode dispatch `if/elif` as **⚠️ reconsider**, not keep; growth pressure is now clear.
- **B.2 #5**: I rate flat `agent_scope` as **❌ change**, not mild reconsider.
- **B.2 #11**: I rate cache-aware composition as **incomplete** because retrieval blocks remain uncached.
- **B.2 #13**: I’m less confident than Claude; compaction still has drift/lineage constraints.
- **B.4 #2**: Claude recommendation is wrong/obsolete; subprocess isolation already shipped.
- **B.1 #8 framing**: “No eval harness” is inaccurate; scaffold exists but defaults to no-op pass for non-live grounded/speculative.
- **B.8 #8.1 wording**: I partially disagree with “would corrupt state”; the practical impact is duplicate scheduled jobs and some ownership-guard holes, not blanket corruption.
- **B.9 #8**: I disagree with “dual-call sanitization on every untrusted ingress path” as a blanket claim.

## 11. What Claude AND the market research missed
- **Audit gap on denied tool calls**: security reviews focused on approvals/timeouts, but not on denied-call observability gaps.
- **Scheduler singleton as architecture, not ops footnote**: this is a core correctness concern once second worker exists.
- **Conversation continuity is weaker than “no `conversation_state` column”**: runtime never hydrates thread history into prompt context at all.
- **Over-indexing on bitemporal substrate too early**: biggest leverage now is taint correctness + eval ratchet + mode reliability, not graph substrate migration.

## 12. Verification audit
- **Context**: current workspace is on `8ac3c26`, not `0149002`; I treated §D as a baseline and re-sampled.
- **D.1**:
  - `run_python` already isolated: **agree** with verifier ([exec_py.py:45](/C:/dev/donna/src/donna/tools/exec_py.py:45)).
  - Eval harness exists but is scaffold/no-op in default grounded/speculative path: **agree** ([evals/runner.py:46](/C:/dev/donna/evals/runner.py:46)).
- **D.2 sampled spot-checks (3+)**:
  - `JobContext.open` silent return: **confirmed** ([context.py:73](/C:/dev/donna/src/donna/agent/context.py:73)).
  - Compaction trims artifact refs to last 20 in prompt line: **confirmed** ([compaction.py:129](/C:/dev/donna/src/donna/agent/compaction.py:129)).
  - `_estimate_tokens` 4-char heuristic: **confirmed** ([model_adapter.py:207](/C:/dev/donna/src/donna/agent/model_adapter.py:207)).
  - No `conversation_state` in schema/runtime: **confirmed** ([0001_initial_schema.py:23](/C:/dev/donna/migrations/versions/0001_initial_schema.py:23)).
- **D.3**:
  - F1 exception leakage: **agree**.
  - F2 eval no-op pass behavior: **agree**.
  - F3 volatile retrieval block uncached generally: **agree**.
  - F4 pre-scan is registry/static-taint-driven: **agree**.

## 13. Action items merged from all three sources, ranked

| Rank | Action | Source(s) | Effort | Leverage | Risk | Where |
|---|---|---|---|---|---|---|
| 1 | Fix internal retrieval taint propagation for all mode-internal retrieval paths | Codex + §D fresh | S | Very high | Low | [grounded.py:73](/C:/dev/donna/src/donna/modes/grounded.py:73), [speculative.py:49](/C:/dev/donna/src/donna/modes/speculative.py:49), [debate.py:104](/C:/dev/donna/src/donna/modes/debate.py:104), [retrieval.py:17](/C:/dev/donna/src/donna/modes/retrieval.py:17) |
| 2 | Convert eval scaffold into ratchet (`SKIP` semantics + structural checks) | Claude + §D | S | Very high | Low | [evals/runner.py:41](/C:/dev/donna/evals/runner.py:41) |
| 3 | Add scheduler leadership lock / single scheduler invariant | Codex + market reliability concerns | M | High | Medium | [worker.py:33](/C:/dev/donna/src/donna/worker.py:33), [scheduler.py:35](/C:/dev/donna/src/donna/jobs/scheduler.py:35), [schedules.py:40](/C:/dev/donna/src/donna/memory/schedules.py:40) |
| 4 | Owner-guard failed-status path in worker exception handling | Codex §D | XS | High | Low | [runner.py:66](/C:/dev/donna/src/donna/jobs/runner.py:66), [jobs.py:141](/C:/dev/donna/src/donna/memory/jobs.py:141) |
| 5 | Per-turn debate checkpoints and resumable transcript state | Codex + Claude | S-M | High | Low | [debate.py:98](/C:/dev/donna/src/donna/modes/debate.py:98) |
| 6 | First-class `scopes` table (policy + prompt + mode flags) | Claude + Codex | M | High | Medium | [0001_initial_schema.py:50](/C:/dev/donna/migrations/versions/0001_initial_schema.py:50), [prompts.py:13](/C:/dev/donna/src/donna/memory/prompts.py:13) |
| 7 | Add cross-job thread memory (`threads.conversation_state` + injection into prompt volatile block) | Claude + Codex | S | High UX | Low | [threads.py:10](/C:/dev/donna/src/donna/memory/threads.py:10), [compose.py:54](/C:/dev/donna/src/donna/agent/compose.py:54) |
| 8 | Redact tainting-tool exception text and make consent timeout user-visible | Claude + §D F1 | XS-S | High | Low | [context.py:237](/C:/dev/donna/src/donna/agent/context.py:237), [web.py:122](/C:/dev/donna/src/donna/tools/web.py:122), [consent.py:132](/C:/dev/donna/src/donna/security/consent.py:132) |
| 9 | Grounded retry improvements: typed failure class + cache retrieved chunks across retry | Claude + §D F3 | XS-S | Medium-high | Low | [grounded.py:113](/C:/dev/donna/src/donna/modes/grounded.py:113), [compose.py:71](/C:/dev/donna/src/donna/agent/compose.py:71) |
| 10 | Ship `/validate` URL mode only (artifact-first output, strict taint handling) | Claude + market §C.6 + Codex | M | High product | Medium | [loop.py:27](/C:/dev/donna/src/donna/agent/loop.py:27), [discord_adapter.py:397](/C:/dev/donna/src/donna/adapter/discord_adapter.py:397) |

REVIEW_COMPLETE
