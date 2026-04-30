# Changelog

## [Unreleased] — 2026-04-30 — Bundle 1: Donna feels like she works

Operator-reported production friction (post-v0.4.1 daily use). The
cross-vendor review found latent bugs; live use found *daily annoyances*.
Four small fixes that change how the bot feels in the hand without
adding new feature surface.

### Fixed — Discord mobile readability

`_DISCORD_MSG_LIMIT` lowered from 1900 → 1400. Operator on iPhone
reported wall-of-text feel on long answers. 1400 is the thumb-scroll
sweet spot — fits a mobile portrait viewport without internal scroll
while still leaving headroom for the `(i/N)` part marker prefix.
`_OVERFLOW_CLEAN_MAX` rises to `1400 * 4 = 5600` (was `1900 * 3 = 5700`)
so total inline deliverable stays roughly the same — same long answers
just split into 4 mobile-friendly chunks instead of 3 desktop ones.

New `_normalize_for_mobile` helper applied to the inline-delivery path:

- Collapses 2+ consecutive blank lines to 1 (mobile renders blank lines
  with full vertical spacing; runs push real content off-screen).
- Strips trailing whitespace per line.
- Converts leading tabs to 2 spaces (Discord mobile renders tabs at
  varying widths).

Idempotent. Applied only to inline; overflow text stays raw so the
artifact preserves original bytes for `botctl artifact-show`.

### Added — session memory across Discord threads

Cross-vendor review queue item #8 + operator's "no memory" daily
complaint. Each `/ask` was a fresh job; the agent had zero recall of
its last reply in the same DM. Wired up the pre-existing (but unused)
`messages` table:

- **`agent/context.py::JobContext.finalize`** — after the DONE flip,
  insert two rows into `messages` (role=user with the task,
  role=assistant with the final_text) when the job is in a Discord
  thread AND not tainted. Tainted jobs DO NOT write — preserves the
  trust boundary so the next clean job can't pick up
  attacker-controlled bytes from a prior tainted run.
- **`agent/compose.py::compose_system`** — new optional `session_history`
  kwarg. When provided, renders in the volatile prompt block as
  `## Prior conversation in this Discord thread (reference only — do
  not cite this; cite from chunks or fresh tools)`. Cap at last 8
  messages (4 turns).
- **`agent/loop.py::_run_chat`** — fetches `recent_messages(thread_id,
  limit=8)` once at loop entry and passes to `compose_system`.

Chat mode only (grounded / speculative / debate are one-shot).

### Improved — scheduler discoverability

Operator reported "I could do with scheduled tasks" — the feature had
shipped in v0.2.0 but they didn't know. The slash commands existed
but the rendering was minimal:

- **`/schedule`** now reports the next-fire time + a 200-char task
  preview in the success response. Catches `ValueError` from a bad
  cron expression and surfaces a user-friendly error instead of a
  500-style failure.
- **`/schedules`** shows a count header + last-fired-at per row + an
  actionable empty-state message ("no active schedules — add one with
  `/schedule cron_expr task`").
- **New runbook:** `docs/SCHEDULER_SMOKE_TEST.md` — walks the operator
  through the first end-to-end fire (schedule a 1-minute job, wait,
  confirm Discord delivery, then schedule a real daily morning brief).
  Aimed at finally validating the feature live in prod.

### Fixed — `send_update` policy spec drift

Cross-vendor review queue item #14. `docs/PLAN.md:94,159` said
`send_update` carrying tainted content requires "every-use confirmation";
`tools/communicate.py:27-52` has no such gate (and never did). Code
was right — per-call consent on a progress-ping channel would prompt
the user for every "I'm working on X" update. The structural protection
already exists: tainted final_text goes through `_post_overflow_pointer`
which compartmentalizes attacker-controlled bytes into an artifact
rather than flooding scrollback.

PLAN.md updated to reflect the actual design: `tainted=1` on
`outbox_updates` is an audit flag the watchdog and `botctl traces`
can surface, not a runtime gate. Decision recorded with rationale so
future reviewers don't re-flag the spec drift.

### Tests

15 new tests in `tests/test_bundle1_feels_like_it_works.py`:

- Mobile rendering: 7 (constants, collapse, whitespace strip,
  idempotence, empty input)
- Session memory: 6 (finalize writes for clean+thread; skips for
  tainted; skips for no-thread; compose injects + omits + caps at 8)
- Scheduler discoverability: 2 (list shape, invalid-cron raises)

359 / 359 pass. Ruff clean.

## [0.4.1] — 2026-04-30 — Cross-vendor review v0.5 menu, items #1, #2, #7, #9, #11, #12, #13, #15

Six fix PRs landing the cross-vendor review's lower-effort items
(`docs/REVIEW_SYNTHESIS_v0.4.0.md` action queue). 51 new tests; 344
passing in total (was 293 baseline). Ruff clean. No code regressions.

The headline item was **#1 internal retrieval taint propagation**
(CRITICAL — flagged independently by Claude + Codex GPT-5 + Codex
GPT-5.3-codex). Each remaining fix is small, contained, and shipped
with regression-pinning tests.

### Fixed — internal retrieval bypassed taint policy (#37, queue #1)

`tools.knowledge.recall_knowledge` (the agent-callable wrapper)
propagated `tainted=True` when any returned chunk's
`knowledge_sources.tainted=1`, but every mode handler called
`modes.retrieval.retrieve_knowledge` directly — bypassing the wrapper.
A tainted corpus chunk would shape grounded answers without firing
consent gates on downstream `remember` / `run_python` / write tools.

- **`modes/retrieval.py::retrieve_knowledge`** — taint check moved
  in-core. Single SELECT against `knowledge_sources.tainted`. Returns
  `tainted: bool` on the result dict. Single source of truth.
- **`tools/knowledge.py::recall_knowledge`** — simplified to delegate.
- **`agent/loop.py::_load_scoped_context`** — return shape extended to
  `(chunks, examples, anchors, tainted)`. Chat-mode propagates per
  iteration.
- **`modes/{grounded,speculative,debate}.py`** — each handler inspects
  `retrieval.get("tainted")` and flips `ctx.state.tainted = True`
  (with `otel.set_attr("agent.job.tainted", True)`).

10 new tests in `tests/test_internal_retrieval_taint.py` cover all four
direct-call paths plus the wrapper.

### Added — eval scaffold → ratchet (#38, queue #2)

The previous `evals/runner.py::_run_one` returned `True` for non-`live`
grounded/speculative cases without exercising any assertion, making the
eval suite a fake CI gate. Rewritten:

- **Tri-state status** — `Result(status, reason, case_id, capability)`
  with `PASS` / `FAIL` / `SKIP`. SKIP reserved for cases that genuinely
  need a live model.
- **`schema_lint()`** runs first. Missing keys, wrong types, unknown
  capability all map to FAIL.
- **`load_goldens()`** raises on YAML parse errors and non-mapping
  top-level documents.
- **New offline-runnable capabilities** — `grounded_refusal` (empty
  corpus → no chunks → refusal trigger) and `taint_propagation` (seed
  source + chunks; assert `retrieve_knowledge.tainted` matches expect).
- **2 new goldens** — `04_taint_propagation_internal_retrieval.yaml`
  (pins #37's fix) and `05_taint_clean_corpus.yaml`. Existing
  `03_debate_quote_requirement.yaml` was silently never triggering the
  validator (the prior fixture shared "efficiency" with the prior
  content, satisfying the validator's fuzzy-overlap escape) — fixed.
- **`tests/test_evals_smoke.py`** — pytest wrapper that loads every
  golden, dispatches via `run_one_async`, asserts no FAILs. Makes the
  eval suite a real CI gate.
- **`tests/test_eval_runner.py`** — runner unit tests covering tri-state,
  schema_lint, load_goldens, and dispatcher behavior.
- **`evals/README.md`** — new schema doc + capability matrix.

23 new tests.

### Fixed — `work_id` propagation to chunks (#39, queue #7)

`ingest/pipeline.py::ingest_text` gave the source row a surrogate
`work_id` (the artifact ID) when caller didn't supply one, but chunk
rows got the raw caller value (None). Result: chunks across unrelated
default ingests all carried `work_id=NULL`, and `_apply_diversity` in
`modes/retrieval.py` collapsed them under a single `__none__` bucket
— silently losing diversity across mixed corpora.

Two-line fix: resolve `work_id` once at the top, use the same value
for source AND every chunk.

4 new tests in `tests/test_work_id_propagation.py`.

### Fixed — stale-worker FAILED-write owner guard (#40, queue #12)

`Worker._run_one`'s exception handler in `jobs/runner.py` wrote
`FAILED` status without an owner guard. A stale worker (lease reclaimed
by another worker but exception handler still firing) could clobber a
recovered/completed job's status. Symmetric to the v0.3.3 #23 owner
guard on `consent._persist_pending`. Threading `self.worker_id` through
to `set_status` (which already accepts the parameter) closes the gap.

### Fixed — attachment temp-file race under concurrency (#40, queue #15)

`tools/attachments.py` wrote attachments to a fixed `attach{ext}` path.
Two concurrent ingests with the same extension overwrote each other.
Append `uuid4().hex[:12]` to the filename. Existing `finally` unlink
keeps `tmp/` tidy. 4 tests for both fixes.

### Added — audit denied / unknown / disallowed tool calls (#41, queue #13)

Net-new finding from Codex GPT-5.3-codex (neither Claude nor GPT-5
caught it). When `_execute_one` rejected a tool call (consent denied,
tool not registered, not allowlisted), it returned an error block to
the model but did NOT insert a row into `tool_calls`. Operators had no
audit trail for attempted bypasses.

New `JobContext._audit_rejection()` helper. Inserts a `tool_calls` row
with one of three new status values:

| Status | Meaning |
|---|---|
| `unknown_tool` | Model called a tool not in REGISTRY |
| `not_allowlisted` | Tool exists but `scope` not in `entry.agents` |
| `denied:<reason>` | Consent gate said no — `<reason>` from the gate |

Best-effort: a logging failure is caught + logged but doesn't break
the agent loop. 5 new tests including a negative DB-explosion test.

### Fixed — sanitizer cost not attributed to jobs (#42, queue #9)

`security/sanitize.py::sanitize_untrusted` called `model().generate()`
without passing `job_id`. The cost ledger therefore couldn't attribute
the Haiku-sanitize spend to the calling job — invisible blind spot in
`botctl cost`. On a heavily-tainted day, per-job cost undercounted by
the exact sanitizer spend.

Threaded `job_id` through:

```
sanitize_untrusted(..., job_id=...)
  → model().generate(..., job_id=...)
    → cost_ledger.record_llm_usage(job_id=...)
```

`tools/web.py::search_web` / `search_news` / `fetch_url` accept
`job_id` (auto-injected by `JobContext._execute_one`'s inspect-based
arg threading) and pass through. 5 new tests.

### Cleanup (#43)

Re-applied the ruff I001 import-order fix on `tests/test_internal_retrieval_taint.py` that PR #37's squash merge had inadvertently dropped from main. One-line.

### Test summary

| Source | Tests added |
|---|---|
| #37 internal retrieval taint | +10 |
| #38 eval ratchet | +23 |
| #39 work_id propagation | +4 |
| #40 small fixes (stale-worker + attachment race) | +4 |
| #41 audit denied tool calls | +5 |
| #42 sanitizer cost attribution | +5 |
| **Total** | **+51** |

344 / 344 pass. Ruff clean across `src/`, `tests/`, and `evals/`.

### What's still open from the merged action queue

| # | Item | Effort | Status |
|---|---|---|---|
| 3 | `agent_scope` first-class | M-L | Schema decision needed |
| 4 | Scheduler leadership lock | M | Architecture decision needed |
| 5 | Step-level checkpoint/replay/fork | M | Design decision needed |
| 6 | `/validate` URL critique | M | v0.5 user-facing feature |
| 8 | Session memory across Discord threads | S-M | UX design needed |
| 10 | Claim objects + span drilldown | M | UX foundation for #6 |
| 11 | Bitemporal facts | M-L | Market-driven, defer |
| 14 | `send_update` policy fix | XS | Policy decision needed |

## [0.4.0] — 2026-04-24 — Unified mode delivery + round-3 adversarial sweep + grounded end-to-end

Started as a single deferred-follow-up fix (grounded/speculative/debate
answers never reached Discord after chat-mode's delivery patch from v0.2.1)
and expanded into five merged PRs spanning unified mode delivery,
adversarial coverage expansion, CLI surface completion, security-driven
overflow delivery, and grounded parser robustness. Closed the loop with
a live end-to-end grounded smoke test on the DO droplet — clean prose,
✅ validated, multi-chunk citation. PRs #28, #29, #30, #31, #32.

### Fixed — mode delivery unified (P1-4)

Commit c623ab1 had flagged this two days earlier: *"Grounded/speculative/
debate modes likely have the same orphaned-final-text hole and will need
the same treatment."* Confirmed live on prod via smoke test — a grounded
`/ask` against `author_twain` produced `📌 queued` and silence; job row
showed `status=done` with `final_text` populated, but outbox empty.

- **`agent/context.py::JobContext.finalize()`** — outbox insert is now
  atomic with the DONE status flip inside a single transaction. Every
  mode (chat, grounded, speculative, debate) delivers by setting
  `ctx.state.final_text + done = True` and letting the context manager
  finalize. No per-mode enqueue needed.
- **`agent/loop.py`** — removed the chat-only `_enqueue_final_text`
  helper + its manual call. Chat rides the same path.
- **Side benefit:** closes a latent chat double-delivery bug. Previous
  design wrote outbox in a separate transaction from DONE; lease-lost
  retry could deliver twice. Atomic-in-finalize prevents this.

### Fixed — mode resume double-execution (regression from the above)

A subtle second-order bug from the delivery unification: if a worker
reaches `done=True`, checkpoints, then dies before finalize runs, the
next worker reclaims the lease and re-enters the mode handler. Chat had
the `while not ctx.state.done` guard; grounded/speculative/debate did
not. On resume they'd re-run retrieval + the full model call, potentially
producing a *different* answer. Debate was the worst case (N scopes ×
M rounds LLM calls + a summary call).

- **Added `if ctx.state.done: return` at each mode entry** in
  `modes/grounded.py`, `modes/speculative.py`, `modes/debate.py`.
- Context manager still finalizes on exit, delivering the pre-existing
  `final_text` verbatim.

### Fixed — 1500-char truncation on long outputs

Previously every outbox row and every `_post_update` call truncated to
1500 chars. Long grounded answers, any debate transcript, and detailed
speculative outputs got chopped mid-sentence. Replaced with:

- **`agent/context.py::JobContext.finalize`** — 20k sanity cap on the
  outbox row (bounded storage, not bounded rendering)
- **`adapter/discord_adapter.py::_split_for_discord`** — new helper
  that breaks long text at paragraph, sentence, or newline boundaries
  (in that preference order), falling back to a hard cut. Each chunk
  ≤ 1900 chars to leave Discord-limit headroom.
- **`_post_update`** — splits long text and posts with `(i/N)` markers,
  250ms between parts to stay under Discord's 5-msg-per-5s rate cap.
- `tools/communicate.py::send_update` still caps at 1500 — those are
  progress pings per its docstring, not final answers.

### Fixed — grounded render (raw JSON → prose)

Live smoke after merging PR #28 surfaced the latent UX bug: the grounded
mode returns a JSON schema (`claims[].citations`, `quoted_span`) designed
for the validator, and the whole blob was being sent to Discord. The
human-readable `prose` field was buried at the bottom.

- **`modes/grounded.py::_format_output`** — parses the JSON and prefers
  `prose` as the user-visible body. Falls back to raw on parse failure
  (model used inline-marker style), non-dict root, or missing/blank prose.
- **`modes/grounded.py::_extract_prose`** — new helper for the parse
  logic, tested independently.
- On validation failure, claim-by-claim issues still append to the
  output so operators can audit — but the raw JSON stays out of the
  user's DM.
- **`modes/speculative.py`** — minor: phrasing-flag list was rendering
  as a Python list repr (`['thinks that']`); joined with commas.

### Fixed — taint-propagation gap in list tools

Same-class audit after Codex round-2 #4 (`recall`, `recall_knowledge`):
list_* tools returned per-row `tainted` flags but no top-level key.
`JobContext._execute_one` only inspects top-level, so a list that
included tainted artifacts / sources slipped through without escalating
the job's confirmation gates.

Attack shape: fetch_url → save_artifact creates a tainted artifact.
Model calls list_artifacts — sees attacker-controlled name/tags. No
taint propagates. Model then calls `remember` / `run_python` without
the tainted-job gate firing.

- **`tools/artifacts.py::list_artifacts`** — sets `result["tainted"] = True`
  when any listed artifact is tainted.
- **`tools/knowledge.py::list_knowledge`** — same for knowledge sources.

### Fixed — debate payload scope validation

`_debate_core`'s `len(scopes) < 2` guard counts list length, not semantic
validity. Payload with `scope_a=""` / `scope_b=None` / `scope_c=42`
passed the guard, and debate ran with `retrieve_knowledge(scope="")`
returning zero chunks — low-quality failure mode that *looked* like a
valid debate but was pure extrapolation.

- **`modes/debate.py::run_debate_in_context`** — filters
  `[s for s in raw_scopes if isinstance(s, str) and s.strip()]` at entry.
  `_debate_core`'s existing guard then catches genuine <2-scope cases
  and delivers the formatted error via finalize.

### Added — `botctl forget-artifact <id>`

Flagged in v0.3.3 open list. Wraps the manual SQL DELETE + `rm` dance in
one command with interactive confirm + dangling-knowledge-source warning.

- Tests pin the UNIQUE-sha256 schema invariant behind the 1:1 row/blob
  assumption.

### Added — `botctl heuristics` sub-app

Was: top-level `heuristics <scope>` that only listed. Operators had to
hand-SQL `UPDATE agent_heuristics SET status = 'active'` to approve a
proposed rule.

- **`botctl heuristics list|approve|retire <arg>`** as a typer sub-app.
- `memory/prompts.py::retire_heuristic` + `get_heuristic` helpers.
- Breaking change for `list` (was bare `botctl heuristics <scope>`).
  No automation depended on the old form.

### Added — `botctl jobs` debate task rendering

Debate tasks are JSON payloads that rendered as hideous truncated JSON
in the `jobs` table. Now rendered as `scope_a vs scope_b: topic`.

### Hardened — sanitize_untrusted short-circuit

Empty / whitespace-only input to the dual-call Haiku sanitizer now
short-circuits to `[no substantive content]` without calling the model.
Anthropic's API rejects empty user messages with a 400; this was a
latent failure mode waiting to happen.

### Wikipedia UA — docs close

`tools/web.py::fetch_url` already ships `Donna/0.2 (+GitHub URL)` and
browser-typical Accept headers. KNOWN_ISSUES still listed the original
`DonnaBot/0.1 (+personal)` 403 symptom as open; updated to reflect the
fix is live.

### Added — compaction + scheduler + cost-ledger coverage (PR #30)

Three modules that existed without dedicated tests now have invariant
pinning:

- **`agent/compaction.py`** — 12 tests: short-message guards, initial
  task preserved, audit artifact written before summary replaces tail,
  `jobs.compaction_log` accumulates JSON across compactions, audit-save
  failure degrades cleanly (no crash, no fake audit line), artifact_refs
  trimmed to last 20, tail capped at 40k before Haiku, `default=str`
  survives tool_use / tool_result content blocks.
- **`jobs/scheduler.py`** — 6 tests + real fix: bad `cron_expr` that
  slips past insert-time validation (data corruption / manual SQL)
  caused the scheduler to infinite-retry every 60s forever.
  `croniter.is_valid()` check at the top of `_fire` now auto-disables
  with a distinct `scheduler.disabling_bad_cron` log event.
- **`memory/cost.py`** — 9 tests including concurrency: 10 concurrent
  `record_llm_usage` calls sum correctly, no missed increment, no
  cross-job leak. SQLite WAL's single-writer serialization makes this
  race-free at the statement level; test pins the invariant before a
  future multi-writer backend silently regresses cost accuracy.

### Added — compose_system cache invariants (PR #30)

17 tests for `agent/compose.py` — prompt caching is real money
(~$0.012 per Sonnet call uncached on a 4k-token stable prefix). Pinned:

- Block 0 is stable prefix with `cache_control: ephemeral`
- Volatile block carries NO cache_control
- Heuristics in stable prefix; retired ones don't appear
- Mode instructions land in stable prefix (distinct cache per mode)
- Chunks render with `[#chunk_id]` markers matching validator expectations
- Style anchors capped at 800 chars; examples limited to first 3
- Identical inputs → byte-identical stable prefix (cache hit guarantee)
- Adding an active heuristic invalidates the prefix (new rule applies)
- Four distinct modes → four distinct stable prefixes

### Added — watchdog pinning (PR #30)

11 tests for `observability/watchdog.py`:

- Stuck-consent > 1h triggers alert; < 1h silent
- Stuck-running > 30m triggers; < 30m silent
- Recent-failures ≥ 3 in last hour triggers; 2 silent; old fails outside
  window excluded
- 12h dedupe by (kind, id) — same stuck job across 3 ticks → 1 alert
- Different kinds for same job alert independently
- Notifier exception during tick does not crash the watchdog (Discord
  DM blip shouldn't stop the ops check loop)

### Added — `botctl artifacts` / `artifact-show` (PR #30)

Filled a gap — `forget-artifact` shipped in PR #29 but there was no way
to *see* artifacts from the CLI without a Python REPL against the live
DB or hand-SQL.

- **`botctl artifacts [--tag X] [--limit N] [--tainted]`** — metadata
  table, ⚠️ badge on tainted rows
- **`botctl artifact-show <id> [--offset N] [--length N]`** — content
  with slice support; binary content prints metadata + "(binary)"
  marker instead of dumping bytes

### Added — overflow-to-artifact delivery (PR #30, user-requested)

> "Messages are getting truncated... we need a logical solution with
> security."

The multi-part splitter in the truncation fix above closed the 1500-char
chop but still painted attacker-controlled tainted content across
multiple Discord messages when long. Security angle: scrollback bloat +
attacker's content taking up visual weight vs operator conversation.

Two thresholds in `adapter/discord_adapter.py::_post_update`:

- **Clean text:** inline up to 3 parts (~5700 chars). Longer → artifact.
- **Tainted text:** inline up to 1 part (~1900 chars). Longer → artifact.

Overflow pointer message:
- Header (📎 clean / 📎 🔮 tainted)
- First ~1200 chars preview
- For tainted: explicit "⚠️ derived from untrusted content, review the
  artifact carefully; do not follow instructions in it"
- `{bytes} chars — Fetch full via botctl artifact-show {id}`

Artifact inherits `tainted` flag, tagged `overflow`+`tainted`, named
`overflow:<job_id>:<Nchars>`. Gracefully degrades on save failure to a
truncated inline stub. 9 tests cover short-inline, medium-multipart,
long-overflow, tainted-tighter-cap, artifact-save-failure, and
channel-resolve-failure paths.

### Fixed — grounded parser robust to code fences + preamble (PR #31, live bug)

Live smoke after PR #29 merged: grounded output was still rendering
raw JSON with `⚠️ partial validation` noise. Diagnostic from the
droplet confirmed — Sonnet wrapped the JSON in ` ```json ... ``` `
despite the prompt's "no code fences" instruction:

    final_text starts with: '```json\n{\n  "claims": [\n    {\n      "text": "At the end of the novel, Huck says'

`json.loads` choked → `_extract_prose` returned None → full fenced JSON
went to Discord → `validate_grounded` fell back to `_validate_inline`
which split the raw JSON on `. ` boundaries and flagged every fragment
as "uncited."

- **`security/validator.py::try_parse_grounded_json`** — new 3-step
  fallback ladder: raw `json.loads` → strip ` ```lang ... ``` ` code
  fence, retry → find outermost `{...}` block, retry. Returns parsed
  value verbatim (any type) + a `_PARSE_FAILED` sentinel for unrescuable
  input, preserving the Codex #5 `schema_missing` contract for non-dict
  roots.
- **`validate_grounded`** — when parse fails on JSON-looking input
  (starts with `{` or ` ``` `), reports one clean `malformed_json`
  issue instead of the inline-fallback noise parade.
- **`modes/grounded.py::_extract_prose`** — same helper; fenced prose
  is now recovered.

14 tests in `test_grounded_parse_robust.py` covering every fallback +
preserved schema_missing contract + end-to-end format output.

### Fixed — smart-quote validator false rejections (PR #32, live bug)

Follow-up to PR #31. Code-fence fix landed, grounded rendered clean
prose — but validation came back `⚠️ partial validation ·
quoted_span_not_in_chunk` on both claims. Two possible causes: LLM
emits curly apostrophes (U+2019 `'`) where Gutenberg source has
straight ones (U+0027 `'`), OR the model paraphrased the `quoted_span`
field while rendering prose with correct verbatim text.

- **`security/validator.py::_normalize`** — NEW helper. Unicode NFC,
  curly quotes → ASCII, en/em/non-breaking dash → ASCII -, horizontal
  ellipsis → three dots, lowercase + whitespace-collapse.
- **`_verbatim_in`** — uses `_normalize` on both span and chunk.
  Content-strict (real paraphrases still fail), rendering-tolerant.
- **`modes/grounded.py`** — retry prompt on validation failure is
  significantly more emphatic: "LITERAL COPY-PASTE of characters...
  NOT a paraphrase, NOT a summary, NOT rewording for clarity. If you
  cannot find a ≥20-char literal substring that supports the claim,
  OMIT THE CLAIM ENTIRELY."
- **`log.info('grounded.model_response', preview=...)`** — raw
  response preview (300 chars) logged on every grounded call + retry.
  Future diagnostics: `docker compose logs worker | grep grounded.model_response`.

12 tests in `test_verbatim_normalization.py` covering each normalization
type + combined + still-rejects-paraphrase.

### Tests — expanded contract coverage

Total **293 passing** (+186 from the v0.3.3 baseline of 107; +91 new
test files).

### Validated live (2026-04-24)

- **Grounded mode end-to-end** against the 402-chunk Huck Finn corpus
  — clean prose, multi-chunk citation (`chk_..._qi` for the ending +
  `chk_...in` for Chapter 1's "Civilizing Huck"), `✅ validated ·
  sources: Huck Finn`, no JSON leak, no `⚠️ partial validation`.
- `botctl artifacts --limit 5` — lists mixed clean + tainted artifacts
  with ⚠️ badge on tainted rows.

### Still needs live Discord smoke

- `/speculate` against a scope with `speculation_allowed=1`
- `/debate` (multi-turn transcript + long-output overflow path)
- Overflow-to-artifact path with a deliberately long `/ask` query
- `botctl heuristics approve/retire` against real proposed heuristics
- `botctl forget-artifact` against a non-test artifact

## [0.3.3] — 2026-04-24 — Codex adversarial round 2 + Jaeger trace backend

Continuation of v0.3.2 same day. A second Codex (GPT-5.4) adversarial scan,
targeted specifically at the "same-class" latent-bug hunt: given two FTS5
injections we'd just found, what else of the same pattern was lurking?
Nine findings, all legitimate, all fixed in the same session. Phoenix
was also retired (broken upstream) and replaced with Jaeger. Ten PRs
merged (#15, #19, #20, #21, #22, #23, #24, #25, plus two docs-wrap).

### Fixed — Codex adversarial round 2

All nine of Codex's findings are closed. Four categories:

#### FTS5 syntax injection (same class, second site)
- **`memory.facts.search_facts_fts`** (PR #19) — identical latent bug to the
  one PR #15 fixed in `keyword_search`, just a different table. The `recall`
  tool hits this path on every LLM-initiated memory lookup; any natural-
  language `recall("…?")` query would have crashed the agent loop with
  `sqlite3.OperationalError: fts5: syntax error`. Fix extracted the
  shared helper to `memory/fts.py::fts_sanitize`.

#### Untrusted-content materialization caps
- **`tools.web.fetch_url`** (PR #20) — no content-type or size guard.
  Model-chosen URL pointing at a binary or HTML bomb would download
  fully, pass through `markdownify` + dual-call sanitize before anything
  noticed. Fix: stream with `httpx.AsyncClient.stream()`, content-type
  whitelist (text/*, json, xml, rss, atom, ld+json), 5MB cap with
  mid-stream abort, `truncated: bool` in the return shape.
- **`tools.attachments.ingest_discord_attachment`** (PR #20) — same
  vulnerability class. 10MB download cap, 500-page PDF cap via
  `reader.pages[:500]`, 1M-char text cap. Returns `pages_read` +
  `truncated_chars`.

#### Taint-propagation completeness
- **`tools.memory.recall`** (PR #21) — was returning `{"results": [...tainted...]}` with
  taint nested inside each result. `JobContext._execute_one` only checks
  top-level `result.get("tainted")`, so tainted facts silently bypassed
  the "escalate subsequent writes" guarantee. Fix: surface
  `any_tainted = any(r.get("tainted") for r in results)` at the top.
- **`security.taint.TAINT_ESCALATED_TOOLS`** (PR #21) — was missing `teach`
  and `propose_heuristic`. Tainted jobs could write to the corpus /
  propose reasoning rules without the always-confirm gate. Both added;
  persistence-of-damage is higher than `remember` because they poison
  grounded-mode answers and the heuristic layer.

#### Crash safety in validators + state loops
- **`security.validator.validate_grounded`** (PR #22) — `json.loads("[]")`
  or `json.loads('"hello"')` returned non-dicts; the following
  `data.get("claims", [])` crashed with `AttributeError`. Now returns
  `schema_missing` validation issue.
- **`modes.debate`** (PR #22) — `int(payload.get("rounds", 3))` crashed
  on `{"rounds": []}` / `{"rounds": "abc"}`. Wrap in
  `try/except (TypeError, ValueError)` → fallback 3.
- **`security.consent.check`** (PR #22) — wait loop ignored
  `jobs.status = 'cancelled'`. User running `/cancel` during consent
  saw the bot keep polling for approval up to the 30-min timeout. Now
  joins against `jobs` and exits in one poll interval.
- **`security.validator._has_substring_overlap`** (PR #22) — O(n*m)
  scan on unbounded model debate-turn text. Capped both inputs at
  50k chars; wall-clock verified bounded (<1s on 200k inputs).

#### State-machine ownership guards
- **`security.consent._persist_pending`** (PR #23) — writes `pending_consents`
  + flips `jobs.status` without owner guard. Stale worker (lost lease)
  could insert spurious consent rows and reset status for jobs owned
  by a different worker now. Fix: `consent.check` takes optional
  `worker_id` keyword; `_persist_pending` guards both writes inside
  a single transaction on `jobs.owner = ?`; mismatch returns `None`
  → `ConsentResult(approved=False, reason="lease_lost")`.
  `JobContext._execute_one` passes `self.worker_id` through.

### Added — Observability swap

- **Phoenix → Jaeger** (PR #25) — `arizephoenix/phoenix:14.x` ships a
  broken image upstream (`ModuleNotFoundError: No module named 'phoenix'`).
  Swapped to `jaegertracing/all-in-one:1.60`. Same OTLP-gRPC port (4317)
  so exporter code is unchanged — only the hostname moves. UI at
  `:16686`, port-forward via SSH. Tradeoff documented: Jaeger is a
  generic distributed-tracing UI (not LLM-native like Phoenix was);
  in-memory storage by default (audit spans still land in the `traces`
  SQLite table via `SqliteSpanProcessor`).

### Added — Ops tooling

- **`scripts/donna-verify-backup.sh`** (PR #24) — lightweight
  restore-drill. Extracts a backup tarball to a temp dir, runs
  `PRAGMA integrity_check` + `PRAGMA foreign_key_check`, counts rows
  on core tables, SHA-256-verifies every artifact blob against its
  sha-named filename. Validated live against a 2.6MB tarball with
  402 Huck Finn chunks: 8/8 blobs OK, integrity ok. Recommended
  crontab entry (3:15 UTC daily, 15 min after the nightly backup)
  included in `docs/OPERATIONS.md`.

### Changed — Renames + doc hygiene

- **CORPUS → Think** — the sibling corpus-interpretation-engine
  project was called "Corpus" in earlier design docs and Codex
  sessions. Renamed throughout to free "corpus" as the data-concept
  word (an author's body of work). `docs/CORPUS_BRIEF.md` →
  `docs/THINK_BRIEF.md`, module/CLI/schema/migration prefixes all
  flipped.
- **Think-is-standalone** (PR #18) — clarified that Donna consumes
  Think's query API but does NOT host Think's runtime. Think has
  its own CLI, job model, tests, LLM calls. Must be runnable when
  Donna's container is down.

### Validated live (2026-04-24)

- Full backup→verify loop on real prod data: 2.6MB tarball with 402
  Huck Finn chunks + 8 artifact blobs round-trips cleanly
- Grounded mode with `?`-terminated query no longer crashes (PR #15/#19
  live)
- Jaeger UI responds 200 on `:16686` after redeploy
- Bot logs stop emitting "Failed to export traces to phoenix:4317"
  warnings after Jaeger redeploy (clean trace export path)
- 102 tests green locally (was 60 start of week)

### Still open (reordered)

1. Full throwaway-droplet restore drill — quarterly task; needs
   Discord-token-juggling coordination (~5 min downtime)
2. Tailscale for port-22 egress — lockout risk if misconfigured;
   needs careful setup
3. `donna-update.timer` enable — per Codex rule, only after a real
   restore drill
4. Phoenix re-enable path (if they ever fix the image) documented
   in `docker-compose.yml`; swap back is a hostname change

## [0.3.2] — 2026-04-23 — Off-droplet backups live

Closes Codex's priority-#1 finding ("single-disk failure = total loss") same
day as v0.3.1. Three-layer backup setup, ~$0.30/mo marginal cost, validated
end-to-end against the live droplet. No source changes — two new scripts
plus ops docs.

### Added — Backup tooling

- **`scripts/donna-backup.sh`** (PR #12) — runs on the droplet as `bot` via
  crontab @ 03:00 UTC. Uses `python3 -c 'sqlite3.Connection.backup()'` so
  the bot user never needs sudo (harden-droplet.sh creates bot with
  `--disabled-password` so `sudo` in-group prompts but never authorizes).
  Same SQLite online-backup API as `sqlite3 src ".backup dst"`, safe while
  the bot writes via WAL. Tarballs snapshot + `/data/donna/artifacts/*`
  blobs into `/home/bot/backups/donna-<UTC-stamp>.tar.gz`, maintains
  `donna-latest.tar.gz` symlink, 7-day local retention via `find -mtime`.

- **`scripts/donna-fetch-backup.ps1`** (PRs #12 + #13) — runs on the laptop
  via Windows Task Scheduler @ 06:00 local. `scp -i id_ed25519_droplet`
  pulls `donna-latest.tar.gz` into `%USERPROFILE%\OneDrive\Donna-Backups\`,
  so OneDrive cloud sync auto-replicates to a 4th location. 30-day local
  retention. Uses built-in Windows OpenSSH `scp` (no rsync/WSL). PR #13
  fixed a PowerShell 7-ism (`Get-Date -AsUTC` doesn't exist in the PS 5.1
  that Windows ships with).

- **DO snapshots** (user-configured, web console) — daily frequency, 4-week
  retention. $0.30/mo. Covers droplet death.

### Changed — Docs

- **`docs/OPERATIONS.md`** (PR #12) — replaced the "honest story" DR
  placeholder with the concrete three-layer install playbook plus a working
  restore-from-tarball recipe. Litestream demoted from "recommended" to
  "optional later" (current ~24h RPO is fine for a personal assistant;
  adding litestream is belt-and-suspenders when sub-minute RPO is needed).

- **`docs/KNOWN_ISSUES.md`** — flipped "Off-droplet backups" out of the
  still-open list; added `Backups — FIXED in v0.3.2` block with install
  + validation summary.

- **`docs/SESSION_RESUME.md`** — §1 updated with backup layers and restore
  recipe pointer; "still open" list no longer leads with the existential
  single-disk-failure risk.

### Validated

Live against the running droplet on 2026-04-23:

- `scripts/donna-backup.sh` dry-run → 224KB tarball + symlink
- `scripts/donna-fetch-backup.ps1` manual run → 224KB tarball landed in
  `%USERPROFILE%\OneDrive\Donna-Backups\`
- `schtasks /Create` registered "Donna Backup Fetch" with next run
  06:00 local next morning

### Still open (reordered now that backups exist)

1. Quarterly restore drill (throwaway droplet → restore from OneDrive
   tarball → boot → DM "hello")
2. Phoenix re-enable with a confirmed-working tag
3. `donna-update.timer` — unblocked by backups + drainer supervision;
   do restore drill first
4. Tailscale
5. `botctl teach` ingest pipeline never exercised in prod
6. Grounded / speculative / debate modes never smoke-tested in prod

## [0.3.1] — 2026-04-23 — Post-deploy hardening + Codex adversarial fixes

Same-day follow-up after v0.3.0 went live. Codex (GPT-5.4) adversarial review
surfaced three latent bugs; all fixed and validated end-to-end against the
running droplet. Five PRs merged.

### Fixed — Codex adversarial findings

- **Drainers no longer die silently** (PR #9 / Codex latent bug #1) — the
  three Discord adapter drain tasks (`_drain_updates`, `_drain_consent`,
  `_drain_asks`) used to be spawned with bare `asyncio.create_task(...)`
  with the handles dropped. A single transient DB or `fetch_channel` error
  killed the task while the container stayed "up." We hit this live during
  the deploy when the DB was briefly unreachable; recovery required a
  container restart. New `_supervise(name, factory)` wraps each drainer in
  a restart loop with capped exponential backoff (1→30s); `CancelledError`
  exits cleanly for graceful shutdown.

- **`/cancel` actually cancels** (PR #9 / Codex latent bug #2) — `/cancel`
  used to flip `jobs.status` to `CANCELLED` but no code path in the agent
  loop or modes ever polled for it. Jobs kept executing through model and
  tool steps until natural `end_turn`. New `JobCancelled` exception +
  `JobContext.check_cancelled()` reads `jobs.status` and raises if
  CANCELLED. `JobContext.open()` catches it, checkpoints partial state,
  exits without finalizing to DONE. Modes call `check_cancelled()` at
  natural step boundaries (chat: top of each iter; grounded: before
  retrieval + regen; speculative: before retrieval; debate: before each
  turn). Validated live: a research job at 18 tool calls + $0.20 spent
  was halted within one iteration after a DB-flip cancel.

- **`botctl jobs --since` actually filters** (PR #9 / Codex latent bug #3)
  — `since: str = typer.Option("1d", ...)` was declared but never used;
  `recent_jobs(conn, limit=limit)` ignored it. Watchdog DM tells users to
  run `botctl jobs --since 1h` during incidents — our own incident
  tooling was lying. `recent_jobs` now accepts `since: timedelta | None`;
  `botctl jobs --since` parses `30m | 3h | 1d | 1w | all` via a new
  `_parse_since` helper. Validated: `--since 1h` returns empty, `--since
  24h` returns 18 rows, `--since all` returns full history.

### Fixed — runtime hygiene

- **Container UID matches host bot** (PR #7) — `user: "1001:1001"` in
  `docker-compose.yml` (configurable via `DONNA_UID`/`DONNA_GID`) so
  bind-mounted files (`/etc/bot/age.key`, `/data/donna/*`) are accessible
  without host-side `chmod 644`/`chmod 777` workarounds. Migration cost on
  the live droplet: one `docker run --rm -v /data/donna:/data alpine
  chown -R 1001:1001 /data` to fix existing files written by the old uid
  10001 container.

- **`docker compose exec bot botctl` works without entrypoint prefix**
  (PR #7) — Dockerfile shadows the pip-installed `/usr/local/bin/botctl`
  with a tiny shell wrapper that forwards through `/entrypoint.sh`, so
  exec'd commands always run sops-decrypt-and-export first. Plus
  `.env.example` scrubbed of inline `# comments` so cp-then-edit yields
  a clean dotenv that `pydantic_settings` can parse.

- **`botctl jobs` shows full job IDs + `botctl job <prefix>` works** (PR
  #7) — `j.id[:18]` truncation removed; `_resolve_job` does exact match
  first then unambiguous prefix match (`WHERE id LIKE 'prefix%' LIMIT 2`).
  Ambiguous prefix → warn + miss; one match → resolve; zero → not found.

- **Slash commands now sync globally** (PR #10) — `setup_hook` only
  sync'd to the configured guild. DMs aren't in any guild, so the entire
  command tree was invisible in DMs — Donna's primary surface. Always do
  a global sync now; if `DISCORD_GUILD_ID` is set, additionally
  `copy_global_to(guild)` and sync there for instant dev-guild updates.
  First post-deploy propagation can take ~1h on Discord's CDN.

### Disabled — upstream

- **Phoenix observability** (PR #9) — `arizephoenix/phoenix:14.9.0` ALSO
  shipped broken (same `ModuleNotFoundError: No module named 'phoenix'`
  as `:latest` from 2026-04-23). Whole 14.x manifest seems bad. Service
  commented out in `docker-compose.yml`; bot/worker continue to function,
  OTLP exporter just logs unreachable warnings. Re-enable in a follow-up
  with a confirmed-working tag (try 13.x or older) or swap to Tempo /
  Jaeger.

### Image / Dockerfile (PR #5, #7)

- `COPY alembic.ini` + `COPY migrations/` so `alembic upgrade head` works
  in the container at first deploy
- `pyyaml>=6.0` added to `pyproject.toml` (entrypoint's inline yaml
  parser needs it; not a transitive dep on python:3.14-slim)
- botctl wrapper as described above

### Smoke tests passing live (2026-04-23)

All against the production droplet, real Anthropic / Discord / Tavily APIs:

- Basic DM round-trip
- Web-tool summarize (Wikipedia → reply)
- Prompt injection / taint propagation (`tainted=⚠️` flag set on web jobs)
- Consent ✅/❌ flow (validated end-to-end: react ✅ → `save_artifact`
  tool ran → markdown report persisted to `/data/donna/artifacts/` with
  matching DB row; metadata sha256-addressed and intact)
- `/cancel` agent-loop check (DB flip → halted within one iteration)
- `botctl jobs --since` filter (1h/24h/all all return correct counts)
- Multi-tool agent loop (19 tool calls in one job: 4 search_web + 7
  fetch_url + 5 send_update + 1 save_artifact + 2 errored — all traced)

### Open follow-ups

- **Off-droplet backups** still not configured (Codex priority 1; user
  explicitly deferred but should revisit before production usage scales)
- **Phoenix re-enable** with a confirmed-working tag
- **Auto-update timer** (`donna-update.timer`) not enabled — manual
  `git pull && docker compose pull && up -d` for now
- **Tailscale** for SSH narrowing (defer until backups + supervision land)
- **`botctl forget-artifact <id>`** subcommand — currently manual SQL +
  `rm` to delete an artifact (we cleaned up an orca research blob this
  way during validation)
- **Slash commands in DMs may take ~1h to appear** after first deploy of
  PR #10 due to Discord's global-command CDN cache; subsequent deploys
  faster

---

## [0.3.0] — 2026-04-23 — Phase 2 production deploy

First real deployment to the DigitalOcean droplet. `ghcr.io/globalcan/donna:latest` is live; bot answering DMs at
`Donna#3183` with sops-encrypted secrets, SQLite at `/data/donna/donna.db`, and
the four `docs/LIVE_RUN_SETUP.md` smoke tests green end-to-end. Phase 2 surfaced
a batch of production-only bugs that the offline suite + Phase 1 localhost run
couldn't catch.

### Fixed — deploy pipeline

- **`scripts/harden-droplet.sh` dpkg-lock race** — `dpkg-reconfigure
  --priority=low unattended-upgrades` in step [4/9] kicked off an immediate
  upgrade run that held `/var/lib/dpkg/lock-frontend` for ~2 min, which then
  blocked step [5/9]'s docker installer. With `set -eo pipefail` the whole
  script aborted, leaving sshd already hardened to `AllowUsers bot` but `bot`
  with no password → catch-22 until droplet rebuild. Fix: replace the
  `dpkg-reconfigure` with a direct write of `/etc/apt/apt.conf.d/20auto-upgrades`
  (same end state, no upgrade-run side effect), plus a defensive
  `wait_for_apt_lock` helper before each apt/dpkg call.
- **`.sops.yaml` creation rule on Windows sops 3.12** — sops 3.12 under Windows
  fails to match the `secrets/.*\.enc\.yaml$` path_regex against the
  `--filename-override secrets/prod.enc.yaml` argument even though 3.9.1 on
  Linux matches it fine. Documented a `rename .sops.yaml .sops.yaml.bak`
  bypass using explicit `--age` recipients for encryption. Follow-up: make the
  path_regex slash-separator agnostic.
- **Docs: `sops -e file > out` command was wrong** — sops matches the
  path_regex against the INPUT filename, not the shell-redirected output.
  `sops -e /tmp/plain.yaml > secrets/prod.enc.yaml` will always miss the rule.
  Correct form uses `--filename-override secrets/prod.enc.yaml`. Fixed in
  `docs/MORNING_START.md` and `secrets/README.md`.
- **Docs: plaintext secrets example used dotenv syntax** — `MORNING_START.md`
  and `secrets/README.md` showed `KEY=VALUE`, but `scripts/entrypoint.sh`
  parses the decrypted content with `yaml.safe_load` (KEY: VALUE). Encrypting
  dotenv → decrypted silently → no env vars exported → bot crashed with
  confusing missing-config errors.
- **`scripts/entrypoint.sh` silent-on-failure** — on sops decrypt error,
  non-mapping YAML input, or zero parsed keys, the old version printed
  "secrets decrypted" anyway and `exec`'d the command with an empty env.
  Hardened: captures exports, validates non-empty mapping with ≥1 `[A-Z_]+`
  key, exits 1 with a clear message on any failure before `eval`.

### Fixed — image / Dockerfile

- **PyYAML not in pyproject.toml** — `entrypoint.sh`'s inline python parser
  imports `yaml`, but PyYAML isn't a direct or transitive dep. Container
  crashed with `ModuleNotFoundError: No module named 'yaml'`. Added
  `pyyaml>=6.0`.
- **`alembic.ini` + `migrations/` missing from image** — Dockerfile only
  copied `src/` + `pyproject.toml`, so first `docker compose exec bot alembic
  upgrade head` on droplet died with `No 'script_location' key found in
  configuration`. Added two `COPY` directives.
- **Container `bot` UID (10001) vs host `bot` UID (1001) mismatch** — the
  0600 `/etc/bot/age.key` file and `/data/donna` directory (both on host,
  owned by host bot) were unreadable/unwritable from the container. Temporary
  host-side fixes: `chmod 644 /etc/bot/age.key`, `chmod 777 /data/donna`.
  Proper fix pending in a follow-up: add `user: "1001:1001"` to
  `docker-compose.yml`.

### Fixed — `.env` / secrets

- **`DONNA_DATA_DIR` default was `./data`** — `.env.example` ships with
  `DONNA_DATA_DIR=./data` (correct for local dev). On the droplet without a
  prod override, alembic inside the container resolved to `/app/data` —
  which is on the read-only rootfs. Must set `DONNA_DATA_DIR=/data` in the
  prod `.env`. Follow-up: flip the default to `/data` and have dev mode
  override instead.
- **Inline comments in `.env` broke `docker compose exec` env** — the main
  container process reads secrets via entrypoint's `export`, so it's fine.
  But `docker compose exec bot botctl` bypasses the entrypoint, falling back
  to compose's `env_file: .env` parse, which captures the inline comment
  (`DISCORD_ALLOWED_USER_ID=   # your own...`) as the string value and
  pydantic rejects it. Workaround: `docker compose exec bot /entrypoint.sh
  botctl …`. Follow-up: either strip comments on `.env` creation or ship a
  `botctl` wrapper that calls entrypoint.

### Fixed — upstream

- **`arizephoenix/phoenix:latest` was broken upstream** (2026-04-23) — started
  with `ModuleNotFoundError: No module named 'phoenix'` from their own
  python3.13. Temporarily commented out the phoenix service in
  `docker-compose.yml`; bot/worker log OTLP-exporter warnings but continue to
  function. Re-enable with a pinned working tag in a follow-up.

### Security / ops

- **Rotated one age recipient** — while walking through the offline-backup
  workflow, the original backup key's private half ended up in a chat
  transcript. No longer "offline" under sole control, so we generated a new
  recipient and swapped it in `.sops.yaml`. No encrypted artifacts existed
  yet, so it was a clean cut-over.
- **CI un-bricked** — 133 ruff errors accumulated over v0.2.x were preventing
  `build-and-push` from firing on any main push (image had never been
  published). Cleaned in one pass (114 auto-fix + 19 manual), 70 tests still
  green, image now publishing on merge.

### Added — new follow-up backlog

Tracked in `docs/KNOWN_ISSUES.md`:

- `user: "1001:1001"` in `docker-compose.yml` (remove chmod hacks)
- `botctl jobs` shows truncated IDs incompatible with `botctl job <id>`
- `botctl` needs to work via `docker compose exec bot` without the
  `/entrypoint.sh` prefix
- Pin phoenix to a known-working tag and re-enable
- Enable `donna-update.timer` so `git push` to main auto-deploys within 5 min
- Backups: not yet configured. Current state is "one SQLite file on one
  droplet"; single-point-of-failure until litestream or snapshot cron lands.

### Smoke tests (all green, 2026-04-23)

Per `docs/LIVE_RUN_SETUP.md`:

- **Basic DM** — bot responds
- **Web-tool summarize** — "summarize this: en.wikipedia.org/wiki/Mark_Twain"
  → fetch + sanitize + summarize via Anthropic, reply delivered
- **Taint / prompt injection** — injection attempt in the prompt → bot
  summarizes cleanly, does NOT leak "PWNED", `botctl jobs` shows `tainted ⚠️`
  on the job
- **Consent + recall** — "remember that my favorite color is blue" → ✅
  reaction approval → DB-persisted → subsequent "what's my favorite color?"
  recalls "blue" via the `recall` tool

---

## [0.2.1] — 2026-04-22 — Phase 1 live-run fixes

First end-to-end live run surfaced three real bugs the in-process test suite
couldn't catch. All four smoke tests in `docs/LIVE_RUN_SETUP.md` now pass
against real Anthropic / Discord / Tavily / Voyage APIs.

### Fixed

- **`main.py` discord.py 2.x compat** — `bot.loop.create_task(...)` was
  called before `await bot.start(...)`; discord.py 2.x won't bind `.loop`
  until start. Swapped to `asyncio.create_task` inside the already-async
  `_run()` frame. Both scheduled coros already `await bot.wait_until_ready()`
  so no ordering change.
- **Cross-process outbox** — `send_update`, `ask_user`, and consent all
  used in-memory `asyncio.Queue`, invisible across the `donna.main` /
  `donna.worker` process boundary. Jobs completed successfully but nothing
  reached Discord. Consent was half-fixed in 0003 (pending_consents table)
  but the decision itself still flowed through an in-memory `Future`.
  SQLite is now the single source of truth:
  - migration `0005_outbox_tables` adds `outbox_updates`, `outbox_asks`,
    and extends `pending_consents` with `approved` / `decided_at` /
    `posted_channel_id` / `posted_message_id`.
  - `tools/communicate.py` — `send_update` INSERTs a row; `ask_user`
    INSERTs then polls the reply column.
  - `security/consent.py::check()` — polls `pending_consents.approved`
    instead of awaiting a Future.
  - `adapter/discord_adapter.py` — three drain tasks poll DB, post to
    Discord, UPDATE/DELETE rows. In-memory `_consent_msgs` / `_ask_msgs`
    dicts removed; reactions match by `posted_message_id`, replies by
    `posted_channel_id`.
- **Chat mode's final answer delivered** — `_run_chat` captured the LLM's
  `end_turn` text as `ctx.state.final_text` and called `finalize()`, but
  nothing ever pushed that text to Discord. The orchestrator prompt
  describes `send_update` as progress-pings, not as the terminal-answer
  mechanism. Added `_enqueue_final_text(ctx)` at the end of `_run_chat`
  to insert the answer into `outbox_updates` for the bot to drain.
  Grounded/speculative/debate modes likely have the same hole; deferred
  until their smoke tests surface it.

### Tests

- `tests/test_outbox.py` — 8 new tests covering DB-backed send_update,
  ask_user reply-polling, ask_user timeout cleanup, consent approval
  polling, migration 0005 schema shape, and `_enqueue_final_text`
  happy-path + empty-text skip.
- Total: **70 passed**.

### Known limitations (not blocking)

- `fetch_url` gets 403 from Wikipedia — our `DonnaBot/0.1 (+personal)` UA
  is policy-compliant but Wikipedia's bot-blocker has gotten stricter.
  Agent falls back to Tavily search + a non-Wikipedia fetch; answer
  quality is fine but a better UA would restore direct Wikipedia access.
- `send_update` caps text at 1500 chars; long-form answers get truncated.
  Long outputs should be saved as an artifact with a pointer sent in the
  update. Follow-up.

---

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
