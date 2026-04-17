# Known Issues

Findings from Codex adversarial review (2026-04-17). Each labeled with
status: **FIXED** (addressed in initial commits) vs **OPEN** (deferred with
mitigation plan).

## CRITICAL

### C1 · Taint bypass via read_artifact — **FIXED**
- **Was:** `read_artifact` on a tainted source returned raw content without
  setting `state.tainted`. Next memory write/code exec bypassed confirmation.
- **Fix:** Agent loop now propagates taint from any tool-result dict with
  `tainted: true`. `read_artifact` passes that flag explicitly. Tool docstring
  warns on every call.
- **Files:** `src/donna/agent/loop.py`, `src/donna/tools/artifacts.py`

### C2 · Lease expiry reclaim during long awaits — **FIXED**
- **Was:** Lease renewed only after a full tool batch. A 30-minute consent
  wait or long model call could expire the lease; another worker would
  reclaim the still-running job; both would race to checkpoint / mark DONE.
- **Fix:** Continuous heartbeat task (30s ticks) runs for the entire job
  lifetime. All checkpoint/final writes are `WHERE owner = ?` guarded;
  `LeaseLost` exception aborts the loop without corrupting state.
- **Files:** `src/donna/agent/loop.py`, `src/donna/memory/jobs.py`

### C3 · Parallel tool batch taint race — **FIXED**
- **Was:** `fetch_url` + `remember` in the same assistant turn → `remember`
  consent check ran against `state.tainted=False` before `fetch_url` flipped
  the flag. Consent bypass on the hot path.
- **Fix:** Agent loop pre-scans the whole tool batch before running any tool
  in it. If any member is taint-marking, the job is pessimistically tainted
  *before* the first tool starts. Consent for every sibling in the batch then
  evaluates against the correct state.
- **Files:** `src/donna/agent/loop.py`

## HIGH

### H1 · Grounded/speculative/debate modes were dead code — **FIXED**
- **Was:** Jobs with `mode=grounded/speculative/debate` ran through the generic
  tool loop; the dedicated mode handlers (validators, speculation policy,
  debate orchestrator) were never invoked.
- **Fix:** `run_job` now dispatches by `state.mode` — grounded/speculative/
  debate jobs are handled one-shot by their respective `modes/*.py` functions
  before the generic loop is considered.
- **Files:** `src/donna/agent/loop.py`

### H2 · Non-idempotent tool replay on crash-resume — **FIXED**
- **Was:** Checkpoint written only after a full tool batch. A crash mid-batch
  replayed every tool including `run_python` and any future L3 write.
- **Fix:** On resume, loop scans state.messages for already-present
  `tool_result` blocks; corresponding `tool_use_id`s are skipped on the
  replay. Non-idempotent tools are never re-executed.
- **Files:** `src/donna/agent/loop.py`

### H3 · Discord ask-reply thread misrouting — **FIXED**
- **Was:** Any user reply in any thread could satisfy the first unresolved
  `ask_user` future, even if from an unrelated job's thread.
- **Fix:** `OutgoingAsk` now records `posted_channel_id` when the adapter
  posts the question. Incoming replies only match asks with the same channel.
- **Files:** `src/donna/tools/communicate.py`, `src/donna/adapter/discord_adapter.py`

## MEDIUM

### Cost ledger clobber on checkpoint — **FIXED**
- **Was:** `record_llm_usage` incremented `jobs.cost_usd` authoritatively;
  later checkpoint writes overwrote it with stale in-memory `state.cost_usd`.
- **Fix:** `save_checkpoint` no longer writes `cost_usd`. Ledger is source
  of truth. On resume, in-memory cost is rehydrated from `jobs.cost_usd`.
- **Files:** `src/donna/agent/loop.py`, `src/donna/memory/jobs.py`

### Rate limiter infinite wait on oversized request — **FIXED**
- **Was:** A single request with `est_input > itpm` looped forever in 5s sleeps.
- **Fix:** `RateLimitLedger.reserve()` raises `OversizedRequestError` when
  an estimate exceeds the per-minute cap. Callers get a hard error they can
  handle/surface.
- **Files:** `src/donna/agent/rate_limiter.py`

### Retrieval temporal boost over-weighted recency — **FIXED**
- **Was:** `(year - 1980) * 0.001` recency boost grew to ~0.046 for recent
  chunks while RRF scores were ~0.016. Pool collapsed to "most recent."
- **Fix:** Recency boost is now scaled to the max fusion score in the pool
  (max ≈ 25% of top score). Saturates 1980 → 2025 into [0.0, 1.0].
- **Files:** `src/donna/modes/retrieval.py`

### Grounded `_supports` is weak — **OPEN**
- **Observation:** 2-token lexical overlap is too weak to be a meaningful
  factuality check. Plausible hallucinations can clear this bar.
- **Why deferred:** Doing this right needs a proper NLI model or a stricter
  verifier LLM call — both cost real money per grounded response. v1 ships
  the cheap check as a first line of defense; hardening requires a proper
  evaluation pass against a test corpus first.
- **Mitigation:** Grounded mode ships behind the explicit `allow_speculation=false`
  policy for living-person scopes. First real usage will surface which
  passes slip through, which is the right signal for tightening.
- **File:** `src/donna/security/validator.py:_supports`

### Ingestion pipeline within-batch duplicate embeds — **FIXED**
- **Was:** Dedup only checked DB, not within the current batch. Repeated
  chunks from reprints inside one source got embedded and billed.
- **Fix:** `ingest_text` now tracks `seen_fp_this_batch` as well as checking
  the DB before embedding.
- **Files:** `src/donna/ingest/pipeline.py`

## LOW

### Debate validator false positives on paraphrases — **FIXED**
- **Was:** 15-char literal-substring requirement flagged fair paraphrases
  and punctuation-normalized quotes.
- **Fix:** `validate_debate_turn` now normalizes punctuation and whitespace,
  accepts quoted spans ≥ 5 chars, and fuzzy 10-char normalized overlap.
- **Files:** `src/donna/security/validator.py`

### chunks_fts missing UPDATE trigger — **FIXED**
- **Was:** `chunks_ai` (INSERT) and `chunks_ad` (DELETE) existed, but no
  `chunks_au` (UPDATE). If chunk content is ever updated in place, FTS goes
  stale silently.
- **Fix:** Migration `0002_chunks_fts_update_trigger.py` adds the trigger.
- **Files:** `migrations/versions/0002_chunks_fts_update_trigger.py`

### sops entrypoint was a shipped no-op — **FIXED**
- **Was:** The entrypoint greps decrypted output for `KEY=VALUE` lines, but
  the configured file was YAML. The grep matched nothing; startup silently
  proceeded with plaintext env_file only.
- **Fix:** Entrypoint now uses Python+PyYAML to parse the decrypted YAML,
  export each valid env-name key as a shell-escaped `export K=V`, and source
  them. Also mounted the secrets file into bot+worker containers.
- **Files:** `scripts/entrypoint.sh`, `docker-compose.yml`

## Intentional deferrals (not bugs, scope cuts)

- No unit test for the lease-loss path — requires a multi-worker integration
  test harness. Manually verifiable.
- No live-API integration tests — gated on having real bot-ops API keys,
  which happens tomorrow.
- Debate summary can't be easily regression-tested (subjective content).
  Structural checks (cited scope, quoted text) are tested; quality is monitored
  via trace review.
- L3 power tools (`run_bash`, `execute_sql`, `send_email`, GitHub) not yet
  registered. When they are, they'll inherit the now-fixed taint propagation
  and consent escalation automatically.
