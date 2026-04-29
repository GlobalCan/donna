# Codex Deep Dive — Donna v0.4.0 — GPT-5.4 Cross-Vendor Review

> Reviewer: OpenAI Codex CLI (GPT-5.4), session `019dda7e-df0d-73a0-98a7-b5d59ccb6ac9`,
> 2026-04-29. This is the genuine cross-vendor leg — independent of the
> Claude review at `docs/CODEX_REVIEW_DONNA_v0.4.0.md` (which is a Claude
> Opus 4.7 review under a misleading filename, retained for the historical
> record).
>
> Run command: `codex exec --skip-git-repo-check < codex_full_prompt.md`
> against HEAD `0149002` on `main`. Codex was given the Claude review's
> load-bearing claims, the market-research synthesis, and a prior verifier's
> verification table as context, then asked to produce its own deep-dive
> AND react explicitly to every load-bearing prior claim.
>
> Tokens used: 269,250. Wall time: 5min 43sec.

---

## 1. Executive summary

- **AGREE (§B.1.1):** Donna is stronger than its stated ambition. The core loop is disciplined, the DB-backed outbox is real, and `JobContext` is the right unifier for a solo operator. I would not move to LangGraph today. The stronger pressure is schema/product debt, not orchestration debt (`src/donna/agent/context.py:50-348`, `src/donna/agent/loop.py:21-92`).
- **AGREE (§B.1.2):** the grounded validator is the best thing in the repo. The `quoted_span` requirement plus tolerant normalization is materially better than public "citation" demos that only verify URL presence (`src/donna/security/validator.py:89-208`).
- **AGREE, EXTEND (§B.1.3):** overflow-to-artifact is excellent and worth naming as a pattern. It is not just UX; it is a containment primitive. But its security story is undermined by a separate taint gap on direct corpus retrievals (`src/donna/adapter/discord_adapter.py:369-469`, `src/donna/modes/retrieval.py:17-79`).
- **AGREE, EXTEND (§B.1.4):** Claude found two time-bombs, but there is a third bigger one: **tainted corpus material retrieved internally does not taint the job at all**. `recall_knowledge()` propagates taint; Donna's own internal `retrieve_knowledge()` path does not (`src/donna/tools/knowledge.py:54-87`, `src/donna/agent/loop.py:95-101`, `src/donna/modes/grounded.py:72-88`).
- **AGREE WITH NUANCE (§B.1.5):** hand-rolled remains correct through v1.0. The closing window is not "framework maturity"; it is Donna's own missing first-class state model for scopes/profiles/steps.
- **AGREE (§B.1.6):** `/validate` should split. URL/article critique fits Donna's primitives. Video/reel critique is a different ingest, cost, and failure regime.
- **AGREE, PARTIAL DISAGREE (§B.1.7):** THINK's EvidencePack boundary is right. I do not agree with an atomic rename/move of live `knowledge_*` tables on day one; dual-read/bridge is safer because grounded mode already depends on them live.
- **PARTIAL DISAGREE (§B.1.8):** "no eval harness" was overstated. The harness exists, but as shipped it is not a ratchet because default non-live grounded/speculative cases report PASS without exercising assertions (`evals/runner.py:41-49`). Expansion is still top-tier work.

## 2. Architectural scorecard

| Decision | Codex verdict | Claude verdict | Agree? | Why if not |
|---|---|---:|---:|---|
| 1. Hand-rolled Anthropic SDK vs frameworks | ✅ keep to v1.0 | ✅ keep | Yes | Current pain is not loop complexity. It is schema/state shape. `AnthropicAdapter` is narrow and serviceable (`agent/model_adapter.py:39-204`). |
| 2. Unified `JobContext` across modes | ✅ keep | ✅ keep | Yes | This is the repo's backbone: lease-safe checkpointing, shared finalization, outbox atomicity (`agent/context.py:50-348`). |
| 3. Mode dispatch via `if/elif` in `loop.py` | ✅ keep | ✅ keep | Yes | At 4 modes this is fine. The issue is not dispatch syntax; it is missing per-mode persisted step state, especially debate (`agent/loop.py:21-37`, `modes/debate.py:82-176`). |
| 4. SQLite as single source of truth | ✅ keep | ✅ keep | Yes | Correct for solo/single-droplet. The real caveat is the explicit single-writer discipline already documented (`memory/db.py:1-10`). |
| 5. `agent_scope` flat string + scattered metadata | ❌ change | ⚠️ reconsider | Partial | Stronger than Claude. This is already constraining product shape: prompts, speculation policy, corpus partitioning, heuristics, and retrieval all key off the same opaque string (`memory/prompts.py:13-79`, `memory/knowledge.py:18-52`). |
| 6. Discord-only, no adapter abstraction | ✅ keep | ✅ keep | Yes | Correct for now. The adapter is thin enough, and more ingress paths would mostly add taint surface (`adapter/discord_adapter.py:1-585`). |
| 7. Outbox pattern | ✅ keep | ✅ keep | Yes | Correct and materially well-implemented (`agent/context.py:304-346`, `migrations/versions/0005_outbox_tables.py:30-74`). |
| 8. Taint as per-job boolean | ⚠️ reconsider soon | ⚠️ reconsider | Yes | Over-propagation is real, but under-propagation is the more urgent current problem because internal retrieval bypasses taint entirely. |
| 9. Quoted-span validator structural, not semantic | ✅ keep | ✅ keep | Yes | Correct v1 compromise. It is intentionally structural, and tests pin that limit (`security/validator.py:141-165`, `tests/test_validator_limits.py:1-23`). |
| 10. `ModelRuntime` registry, pricing as data | ✅ keep | ✅ keep | Yes | Good as a pricing/config registry. Not yet true multi-vendor execution abstraction; execution is still Anthropic-only (`memory/runtimes.py:38-92`, `agent/model_adapter.py:39-204`). |
| 11. Cache-aware prompt composition | ✅ keep | ✅ keep | Yes | Solid. Claude is right that chunk caching is the next obvious save. Current volatile retrieval block forfeits cache on every call (`agent/compose.py:71-86`). |
| 12. Overflow-to-artifact for tainted content | ✅ keep | ✅ keep | Yes | One of the repo's most original primitives (`adapter/discord_adapter.py:374-469`). |
| 13. Compaction-as-summarization with audit artifact | ⚠️ keep, but add step-state guardrails | ✅ keep | Partial | Chat path is sound. Debate path is not actually checkpointed per turn, so long expensive runs still lose work on failure (`agent/compaction.py:41-149`, `modes/debate.py:98-176`). |

**Load-bearing decision Claude missed:** `checkpoint_state` is an opaque JSON blob rather than a first-class step log. That is why replay/fork/eval drift and mid-debate recovery are all awkward. I would rate that **⚠️ reconsider** (`types.py:60-104`, `memory/jobs.py:84-138`).

## 3. Field positioning

- **C.1 taxonomy:** **EXTEND.** The "empty quadrant" is interesting, but Donna does **not** occupy it yet. Grounded mode renders a global footer badge, and speculative renders a global banner; neither renders per-claim inline status primitives (`modes/grounded.py:148-168`, `modes/speculative.py:74-80`).
- **C.2 agent primitive axis:** **PARTIAL DISAGREE.** "Graph control wins" is too abstract to be useful here. Donna's immediate gap is not graph control; it is first-class persisted state for scopes/profiles/steps.
- **Hosted vs self-host:** **AGREE.** Donna's single-droplet, SQLite, CLI-heavy posture is a good hedge for this product shape.
- **Memory persistence shape:** **PARTIAL DISAGREE.** Donna does not "fit only bitemporal" yet. Bitemporal facts are useful, but higher leverage first is: eval ratchet, scope/profile schema, session memory, and tainted-corpus policy.
- **Tool sandboxing:** **AGREE.** Donna belongs in the explicit-defender camp. The code consistently tries to push risk into structure, not vibe (`security/*`, `tools/exec_py.py:29-73`).
- **Provenance grain:** **AGREE, EXTEND.** Claim-level provenance remains underbuilt category-wide. Donna is closer than most, but still lacks stable claim objects/span drilldown; `quoted_span` lives inside the hidden JSON contract, not the rendered UI.
- **C.7 niche claim:** **PARTIAL DISAGREE.** As of HEAD `0149002`, Donna's defensible niche is better stated as: *solo-operator, grounded-to-owned-corpora, security-posture-first assistant with structural citation validation*. The "inline labeled extrapolation + bitemporal memory + trifecta partition" niche is still aspirational.
- **B.3 framework positioning:** LangGraph is the only framework worth periodic review; CrewAI / OpenAI Agents SDK are the wrong shape; Claude Agent SDK is interesting but not urgent; NotebookLM is the closest product comp on grounded Q&A; Perplexity Verify is a weaker provenance contract than Donna's current validator. I broadly agree with Claude here.

## 4. Top 10 recommended additions

| # | Codex | Claude | Same idea? |
|---|---|---|---|
| 1 | Real eval ratchet, not scaffold only | Eval harness | Yes |
| 2 | First-class scope/profile/corpus schema | Per-scope config table | Partial |
| 3 | Tainted-corpus propagation + quarantine | Tainted-fact quarantine | Partial |
| 4 | Session memory across Discord thread | Session memory | Yes |
| 5 | `/validate` URL mode only | `/validate` URL critique only | Yes |
| 6 | Step-level checkpoint/replay/fork for long modes | Pluggable checkpointing/replay | Yes |
| 7 | Fix work identity: durable `work_id`/source grouping | Not listed | No |
| 8 | Grounded retrieval block caching | Grounded chunk caching on retry | Yes, but broader |
| 9 | Claim objects/span drilldown for grounded output | Passage-cited drilldown | Yes |
| 10 | Bitemporal facts with invalidation | Not listed by Claude, in market report | No |

Disagreements and why:

- **Drop Claude's subprocess recommendation.** Already done in `tools/exec_py.py:39-73`.
- **Promote tainted-corpus policy above streaming.** Internal retrieval bypasses taint today, so safety posture is inconsistent (`agent/loop.py:55-62`, `modes/grounded.py:72-88`, `tools/knowledge.py:54-87`).
- **Add work identity normalization.** `ingest_text()` gives the source a surrogate `work_id`, but chunk rows get `work_id=None`, collapsing unrelated sources into the same diversity bucket (`ingest/pipeline.py:48-60`, `ingest/pipeline.py:107-120`, `modes/retrieval.py:156-171`).
- **Keep bitemporal facts lower than market report suggests.** Good idea, but not before Donna can measure regressions and preserve thread state.

## 5. `/validate` evaluation

1. **Two features:** **AGREE.** URL/article critique and video critique should not ship together. Claude is right.
2. **New `JobMode.VALIDATE`:** **AGREE.** Do not fake this as "chat with tools." It needs a constrained output contract, just like grounded mode.
3. **Artifact-first Discord shape:** **AGREE, EXTEND.** For `/validate`, I would always send a short summary plus a claim table artifact. This mode wants structured rows, not a long essay.
4. **Angle vs competitors:** **AGREE, EXTEND.** The real wedge is: *verify claims against your own corpus plus authoritative external sources with structurally verified quote evidence*. If you build it, use `ClaimReview` as the canonical external claim object early; Claude underweighted that.
5. **Video failure mode:** **AGREE, EXTEND.** The hardest failure is not only `yt-dlp` churn or GPU cost. It is clip-boundary context loss, subtitle quality variance, edits, overlays, sarcasm, and speaker attribution. Video critique will generate false certainty unless tightly scoped.
6. **Taint propagation:** **EXTEND.** Existing boolean taint is not enough for `/validate`. A critique will mix fetched evidence, model synthesis, and maybe prior Donna memory. With one job-wide boolean, you can gate writes, but you cannot label *which claims are externally sourced vs inferred*.

## 6. Deep-dive answers

1. **20-char floor:** **AGREE.** Keep it. I would not globalize configurability yet; the bigger gap is semantic support classification after repeated failure.
2. **Grounded retry prompt:** **AGREE, EXTEND.** The retry text is directionally right (`modes/grounded.py:112-141`). But after a second failure, Donna still renders the answer with "partial validation." For `bad_citation` / `quoted_span_not_in_chunk`, I would refuse rather than ship the prose.
3. **1900-char tainted overflow threshold:** **AGREE.** It is a good default. The safety rationale is coherent and implemented (`discord_adapter.py:41-55`).
4. **Compaction strategy:** **PARTIAL DISAGREE.** `N=20` is fine for chat, but Donna's most expensive mode, debate, does not checkpoint transcript state per turn at all. The compaction strategy is sound; the step-state coverage is not.
5. **Should `agent_scope` become first-class:** **AGREE, but go one step further.** If THINK is imminent, I would skip a minimal `scopes` table and go straight to `corpora`, `profiles`, and prompt/policy attachment.
6. **`facts` vs `knowledge_chunks`:** **AGREE WITH DIFFERENT EMPHASIS.** The bifurcation is right. The missing third thing is not primarily `core_memory`; it is interpreted corpus structures in THINK.

## 7. THINK separation review

1. **Boundary correct:** **AGREE.** EvidencePack-in / prose-out is the right seam. Donna should keep voice, taint policy, and UI rendering.
2. **`recall_knowledge` migration:** **AGREE, EXTEND.** Keep a Donna wrapper and move retrieval implementation into THINK gradually. But do not delete Donna retrieval paths until the internal grounded/speculative/debate callers have all moved.
3. **402-chunk Huck Finn migration:** **DISAGREE.** I would not do an atomic rename/move as the first step. Live grounded mode already depends on `knowledge_*`. Safer path: dual-read, mirror ingest into `think_*`, switch readers, then retire old tables.

## 8. Red flags

New red flags Claude missed:

- **Tainted corpus retrieval bypasses taint policy entirely.** Internal retrieval in chat/grounded/speculative/debate loads chunk content straight into prompt composition, but only the tool wrapper `recall_knowledge()` checks source taint. This is the biggest current security inconsistency (`agent/loop.py:55-62`, `modes/grounded.py:72-88`, `modes/speculative.py:45-55`, `modes/debate.py:104-111`, `tools/knowledge.py:54-87`).
- **Debate mode does not checkpoint transcript incrementally.** If the worker dies mid-debate, all prior turns are lost and rerun. That is the exact class of expensive recovery bug the architecture is otherwise designed to avoid (`modes/debate.py:98-176`).
- **Plan/implementation drift on tainted `send_update`.** The plan says tainted updates should require confirmation; the actual tool is `confirmation=never` and is not in `TAINT_ESCALATED_TOOLS` (`docs/PLAN.md:94,159`, `tools/communicate.py:27-52`, `security/taint.py:19-27`).
- **Attachment ingest has a temp-file race under concurrency.** `ingest_discord_attachment()` writes to a fixed `attach{ext}` path. Two concurrent ingests with the same extension can overwrite each other (`tools/attachments.py:82-85`).
- **Stale worker exception path can clobber job state.** `Worker._run_one()` writes `FAILED` without owner guard. A stale worker can mark a recovered/completed job failed (`jobs/runner.py:60-67`, `memory/jobs.py:141-176`).
- **`work_id` propagation is broken for default ingests.** Source rows get a surrogate `work_id`; chunk rows do not. Retrieval diversity then collapses unrelated `NULL work_id` sources into one bucket (`ingest/pipeline.py:48-60`, `ingest/pipeline.py:107-120`, `modes/retrieval.py:156-171`).
- **Sanitizer costs are not attributed to jobs.** `sanitize_untrusted()` does not pass `job_id` into model generation, so per-job cost accounting undercounts security work (`security/sanitize.py:35-68`, `memory/cost.py:38-72`).

## 9. Non-obvious wins

| # | Verdict | Note |
|---|---|---|
| 1 | AGREE | `quoted_span` validator is the marquee feature (`security/validator.py:89-208`). |
| 2 | AGREE | Overflow-to-artifact is genuinely novel at this scale (`adapter/discord_adapter.py:397-469`). |
| 3 | AGREE | Atomic finalize + outbox insert is exactly right (`agent/context.py:304-346`). |
| 4 | AGREE, EXTEND | Lease renewal + owner-guarded writes are strong. The stale-failure path in `Worker._run_one()` still needs the same discipline. |
| 5 | AGREE, EXTEND | Resume-authoritative cost is right (`agent/context.py:362-373`). But sanitizer spend is not attached to jobs. |
| 6 | AGREE, EXTEND | Pre-scan taint is subtle and correct for static taint tools; D.3 F4 is also right that it is registry-driven, not data-driven (`agent/context.py:163-171`). |
| 7 | AGREE | Haiku compaction with audit artifact is a strong pattern (`agent/compaction.py:41-149`). |
| 8 | DISAGREE | "Dual-call sanitization on every untrusted ingress path" is too strong. Attachment ingest goes straight into corpus, and internal retrieval of tainted corpus bypasses taint propagation (`tools/attachments.py:119-137`, `modes/retrieval.py:17-79`). |
| 9 | AGREE | `botctl` is a real product surface, not an afterthought (`cli/botctl.py:1-540`). |
| 10 | AGREE | `JobCancelled` at iteration boundaries is correctly minimal and effective (`agent/context.py:115-128`, `agent/loop.py:47-50`). |

Additional wins:

- **Source-of-truth honesty.** README and plan are unusually explicit about what is and is not vendor-agnostic, multi-tenant, or autonomous.
- **Constraint-first tests.** The tests do not only check happy paths; they pin known limitations intentionally (`tests/test_validator_limits.py:1-23`).

## 10. Disagreements with Claude (consolidated)

- **§B.1.8 / §B.4.1:** "No eval harness" is wrong. A scaffold exists in `evals/runner.py:24-49`; the correct critique is that it is not yet a real ratchet.
- **§B.4.2:** subprocess-isolated `run_python` was already done before Claude wrote the review (`tools/exec_py.py:39-73`).
- **§B.2.5:** Claude's "reconsider" on `agent_scope` is too soft. It is already the main schema/product constraint (`memory/prompts.py:13-79`, `memory/knowledge.py:18-52`).
- **§B.6.4:** Compaction is not simply "right, watch drift after 3 compactions." Debate mode currently lacks the per-step checkpointing that makes compaction strategy matter for long expensive runs (`modes/debate.py:98-176`).
- **§B.7.3:** I disagree with atomic live migration of Huck Finn into `think_*` at wrapper-flip time. The safer sequence is bridge, dual-read, then cut over.
- **§B.9.8:** Claude overstated sanitizer coverage. Not every untrusted ingress path is dual-call sanitized in the sense that matters for downstream taint semantics.
- **Missed by Claude entirely:** internal tainted-corpus retrieval bypass, `work_id` null-collapse, sanitizer job-cost undercount, fixed-path attachment temp race, and stale unguarded failure writes.

## 11. What Claude AND the market research missed

- **Donna's current moat is narrower than the market report claims.** The "inline per-claim epistemic marker" niche is not implemented yet. Donna has structural validation, not yet a claim-object UI.
- **The most important current security hole is inside Donna's own retrieval path, not its tool boundary.** Both prior reviews over-focused on tool taint.
- **The most important current quality bug is identity, not embeddings.** `work_id` inconsistency quietly damages retrieval diversity and corpus composition.
- **The most important current observability blind spot is hidden security spend.** Sanitizer calls are real model work but not job-attributed.
- **The real "framework pressure" is replayability.** If Donna ever wants fork/replay/evals that mean anything, step state must stop living only in opaque checkpoint JSON blobs.

## 12. Verification audit

- **D.1:** **AGREE.** The prior verifier correctly called out Claude's two factual misses: `run_python` isolation already exists, and the eval harness exists but is mostly a scaffold.
- **D.2 sampled spot-checks:** I sampled `JobContext.open` silent return (`agent/context.py:73-76`), compaction artifact-ref trimming (`agent/compaction.py:125-130`), and `_estimate_tokens` 4-chars/token (`agent/model_adapter.py:207-215`). All three are accurately represented. I also confirmed `conversation_state` is absent by repo search.
- **D.3 F1:** **AGREE.** Exception leakage in `_execute_one()` is real and broader than web snippet leakage (`agent/context.py:233-241`).
- **D.3 F2:** **AGREE.** The eval harness currently over-reports PASS in default mode (`evals/runner.py:41-49`).
- **D.3 F3:** **AGREE.** Volatile retrieval blocks affect all retrieval modes, not only grounded retry (`agent/compose.py:71-86`).
- **D.3 F4:** **AGREE.** Pre-scan taint is static-registry-based today (`agent/context.py:163-171`).
- **What the verifier still missed:** the direct tainted-corpus retrieval gap, stale unguarded failure writes, attachment temp-path collision, broken chunk `work_id` propagation, and sanitizer job-cost under-attribution.

## 13. Action items merged from all three sources, ranked

| # | Action | Source(s) | Effort | Leverage | Risk | Landing area |
|---|---|---|---|---|---|---|
| 1 | Make internal retrieval taint-aware; taint jobs when retrieved chunk sources are tainted | Codex | M | Very high | Medium | `modes/retrieval.py`, `agent/loop.py`, `modes/grounded.py`, `modes/speculative.py`, `modes/debate.py` |
| 2 | Turn eval scaffold into a real regression ratchet with SKIP/PASS distinction and structural assertions | Claude + D + Codex | S-M | Very high | Low | `evals/runner.py`, `evals/golden/*` |
| 3 | Replace flat `agent_scope` scatter with first-class corpus/profile config | Claude + market + Codex | M-L | High | Medium | `memory/prompts.py`, `memory/knowledge.py`, migrations |
| 4 | Add incremental checkpoint/replay/fork for debate and other long modes | Market + Codex | M | High | Medium | `modes/debate.py`, `types.py`, `memory/jobs.py` |
| 5 | Ship `/validate` for URL/article critique only | Claude + market + Codex | M | High | Medium | new mode + `tools/web.py` + Discord UX |
| 6 | Fix `work_id` propagation and retrieval grouping semantics | Codex | S | High | Low | `ingest/pipeline.py:48-60,107-120`, `modes/retrieval.py:156-171` |
| 7 | Add session memory across Discord threads | Claude + Codex | S-M | Medium-high | Low | `threads` schema, adapter intake, loop composition |
| 8 | Attribute sanitizer spend to jobs and surface it in cost tooling | Codex | S | Medium | Low | `security/sanitize.py`, `memory/cost.py`, maybe traces |
| 9 | Add claim objects/span drilldown to grounded output | Market + Claude + Codex | M | Medium | Medium | `modes/grounded.py`, maybe new `claims` storage |
| 10 | Add bitemporal fact invalidation, not deletion-only memory | Market | M-L | Medium | Medium | `memory/facts.py`, migration `0006_*` |
| 11 | Guard stale-worker failure writes with owner checks | Codex | XS-S | Medium | Low | `jobs/runner.py:60-67`, `memory/jobs.py:141-176` |
| 12 | Fix tainted `send_update` policy drift | Codex + PLAN | XS | Medium | Low | `tools/communicate.py`, `security/taint.py` |
| 13 | Fix attachment temp-file concurrency collision | Codex | XS | Medium | Low | `tools/attachments.py:82-85` |

REVIEW_COMPLETE
