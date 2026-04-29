# Cross-Model Comparison — GPT-5 vs GPT-5.3-codex vs GPT-5.5-pro

> Same prompt, three models, same code at HEAD `0149002`. The prompt is
> the augmented `codex_full_prompt.md` (33KB / 489 lines, original
> deep-dive + Claude's findings + market research + verification table).
>
> - **GPT-5 (default, ChatGPT auth)**: complete review, 269K tokens, 5min 43s.
>   See [`CODEX_REVIEW_DONNA_v0.4.0_GPT5.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT5.md)
> - **GPT-5.3-codex (API mode)**: complete review, 162 lines, similar
>   structure. See [`CODEX_REVIEW_DONNA_v0.4.0_GPT53CODEX.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT53CODEX.md)
> - **GPT-5.5-pro (API mode)**: TRUNCATED — burned 296K tokens reasoning,
>   hit OpenAI quota mid-stream, no final review produced. See
>   [`CODEX_REVIEW_DONNA_v0.4.0_GPT55PRO.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT55PRO.md).
>   Recommend running pro against narrower scopes only.

## Headline result

**GPT-5.3-codex was the most useful pass.** It surfaced two findings
that GPT-5 did not catch and that the prior Claude review missed
entirely. These are now the highest-confidence net-new items in the
merged action queue.

## Where the two completed runs converged

Both **GPT-5** and **GPT-5.3-codex** independently flagged the same
top-priority finding — **internal retrieval bypasses taint policy**
(`recall_knowledge` checks `knowledge_sources.tainted`; internal
`retrieve_knowledge` calls in every mode don't). Two LLMs from the
same family, given different system prompts and reasoning, both
landed on this as the #1 security gap. High-confidence target.

Other shared findings (both reviews):

- Eval scaffold exists but isn't a ratchet (Claude's "missing harness"
  framing wrong; runner returns `True` for non-`live` cases without
  exercising assertions)
- `agent_scope` flat string is **❌ change**, not Claude's softer
  ⚠️ reconsider
- `run_python` subprocess isolation already shipped (Claude's
  recommendation obsolete)
- Debate mode lacks per-turn checkpointing
- Stale-worker FAILED-status writes need owner guard
- Sanitizer cost not job-attributed
- `/validate` URL only, defer video to v0.6
- Quoted-span validator + overflow-to-artifact are real moat items

## Where GPT-5.3-codex went further than GPT-5

GPT-5.3-codex independently surfaced two findings GPT-5 missed:

### (1) Scheduler duplicate-fire across multiple workers

`worker.py:46`, `schedules.py:40`, `scheduler.py:35`. Each worker
process starts its own scheduler thread with no leadership lock. With
two workers running simultaneously, both will fire the same scheduled
job at the cron tick. Today this is prevented by deployment
discipline (single worker container in `docker-compose.yml`), but it
is not a code-level invariant.

GPT-5 flagged "two workers corrupt state" generically (Claude §8.1
verbatim); GPT-5.3-codex specifically called out **duplicate
scheduled-job firing** as the sharper concrete bug, distinct from the
worker-leadership invariant.

### (2) Denied / unknown / disallowed tool calls not audited

`context.py:200, 208, 253`. When a tool call is rejected (consent
denied, tool not found, tool not in allowlist), the rejection path
returns an error block to the model but does not insert a row into
`tool_calls`. Result: the operator can't audit what tools the model
TRIED to call but was denied. For a security-conscious bot this is a
visible gap — adversarial probes (model attempting to bypass consent
gates) are invisible in `botctl traces`.

This finding did not appear in either Claude's review or GPT-5's
review.

## Where the two completed runs diverged on verdicts

| Decision | GPT-5 | GPT-5.3-codex | Resolution |
|---|---|---|---|
| Mode dispatch (`if/elif` in `loop.py`) | ✅ keep | ⚠️ reconsider | GPT-5.3-codex stronger — at N=4 modes it's fine, but `/validate` (#5) + Think integration is now imminent and a registry would be cleaner |
| Cache-aware composition (`compose.py`) | ✅ keep, with concern | ⚠️ "incomplete" | Same root concern (retrieval blocks uncached); GPT-5.3-codex frames it more directly as a missing primitive |
| Compaction strategy | ⚠️ keep with step-state guardrails (debate concern) | ⚠️ keep with guardrails (drift + lineage) | Compatible — both flag the watch-items, different emphasis |
| Niche claim (market §C.7) | "narrower than market claims" | "under-served, not empty" | Same direction; GPT-5.3-codex more diplomatic |
| Bitemporal facts ranking | "defer to v0.6+; market overweights" | "DISAGREE Donna fits only bitemporal; lighter invalidation first" | Codex stronger — argues even the lighter-than-Graphiti shape isn't urgent |

## What GPT-5.5-pro spent 296K tokens doing before quota hit

Pro tier read the following files (in approximate order):
- `README.md`, `CHANGELOG.md` (large, ~600 lines)
- `docs/PLAN.md`, `docs/KNOWN_ISSUES.md`, `docs/SESSION_RESUME.md`,
  `docs/THINK_BRIEF.md`
- `src/donna/agent/context.py` (full)
- `src/donna/agent/loop.py` (partial — quota hit around line 100)

The reasoning trace shows pro was building a deeper code model than
GPT-5 or GPT-5.3-codex did, with multiple "thinking" steps interleaved
between file reads. This suggests pro would produce stronger findings
on the same scope **if budget allowed** — but the synthesis-style
prompt (13 output sections covering whole-system architecture)
exceeds a single quota window for tier-1 OpenAI accounts.

**Practical takeaway for using pro:** narrower-scope prompts. One
architectural decision at a time, one mode at a time, or one §B
question at a time. Whole-system synthesis blows budget.

## Cost / time profile (rough)

| Model | Tokens used | Wall time | Output produced | Cost class |
|---|---|---|---|---|
| GPT-5 (default, ChatGPT auth) | 269,250 | 5min 43s | Complete 13-section review | Free under ChatGPT Plus |
| GPT-5.3-codex (API mode) | ~similar | ~similar | Complete 13-section review with novel findings | API per-token |
| GPT-5.5-pro (API mode) | 296,476 | ~10min before quota | None (ERROR mid-stream) | API per-token, expensive, hit quota |

For full-system reviews on this codebase: **use GPT-5.3-codex**.
For per-section deep-dives: **try gpt-5.5-pro**.
For everyday "ask Codex": **gpt-5.5** (default, free under ChatGPT
auth) is fine but API access is unlocked, so codex variant works too.

## Updates to merged action queue

The synthesis at [`REVIEW_SYNTHESIS_v0.4.0.md`](REVIEW_SYNTHESIS_v0.4.0.md)
already incorporated the GPT-5 findings. The two new GPT-5.3-codex
findings should be inserted into the queue:

| Position | Action | Source | Effort | Leverage | Risk |
|---|---|---|---|---|---|
| (insert as #4) | Add scheduler leadership lock / single scheduler invariant | GPT-5.3-codex | M | High | Medium |
| (insert as #14) | Audit denied/unknown/disallowed tool calls — persist to `tool_calls` table | GPT-5.3-codex | XS-S | Medium | Low |

KNOWN_ISSUES.md will be updated alongside this comparison.

## Conclusion

The cross-vendor pass was already worth running once with GPT-5.
Re-running with GPT-5.3-codex produced two more concrete findings,
both of which are real bugs at file:line, both spot-checked.
GPT-5.5-pro is the future ceiling for quality but exceeds current
quota for whole-system synthesis prompts.

**Recommend default model `gpt-5.5-pro` for short queries; switch to
`gpt-5.3-codex` for any prompt over ~10K tokens until OpenAI quota
allows full pro deep-dives.**
