# Codex Deep Dive — Donna v0.4.0 — GPT-5.5-pro (TRUNCATED)

> Reviewer: OpenAI Codex CLI with `model = "gpt-5.5-pro"`, session
> `019dda*`, 2026-04-29. **This run did NOT complete.** Codex burned
> 296,476 tokens on reasoning + file reads against the same augmented
> prompt used for GPT-5 and GPT-5.3-codex, then hit
>
> ```
> ERROR: Quota exceeded. Check your plan and billing details.
> ```
>
> from OpenAI mid-stream, before producing the final markdown synthesis.
> No `REVIEW_COMPLETE` marker. The raw transcript is preserved at
> `C:\Users\rchan\AppData\Local\Temp\donna-review\codex_raw_55pro.txt`
> for forensic review (3,072 lines: 0–434 prompt echo, 434–3,068 codex
> reasoning + interleaved code dumps, 3,069–3,072 quota error + token tally).
>
> The pro tier is meaningfully more expensive than `gpt-5.5` /
> `gpt-5.3-codex`. The full deep-dive prompt as run is unfinished work
> for pro at the operator's current OpenAI quota tier; either upgrade
> the API spend cap or run pro on a narrower scope (single section, not
> the 13-section synthesis).
>
> Findings from the completed runs:
> - **GPT-5 (default, 2026-04-29)**: [`CODEX_REVIEW_DONNA_v0.4.0_GPT5.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT5.md)
> - **GPT-5.3-codex**: [`CODEX_REVIEW_DONNA_v0.4.0_GPT53CODEX.md`](CODEX_REVIEW_DONNA_v0.4.0_GPT53CODEX.md)
> - **Side-by-side**: [`REVIEW_COMPARISON_GPT5_VARIANTS.md`](REVIEW_COMPARISON_GPT5_VARIANTS.md)
>
> If the operator wants pro-tier output, options:
> 1. Wait for the OpenAI quota window to reset (typically 1 hour for
>    tier-1 accounts), then rerun
> 2. Upgrade OpenAI billing tier
> 3. Run pro against a narrower prompt — e.g. just §A Part 4 (six
>    deep-dive questions), which would fit well under 296K tokens
> 4. Accept that GPT-5.3-codex's review (which completed cleanly with
>    novel findings the GPT-5 review missed) is the substantive
>    cross-vendor pass for this iteration

## Reasoning observations from the partial run

Pro spent its budget on:
- Reading >12 source files in `src/donna/agent/`, `src/donna/modes/`,
  `src/donna/security/`, `src/donna/tools/`, `migrations/versions/`
- Multiple "thinking" passes interleaved with code reads
- Building up the contextual model before producing any output

This suggests the prompt is well-suited to pro's deep-reasoning style
but exceeds a single-window budget when forced to also produce all 13
sections of structured output. The right shape for pro on this codebase
is probably narrower-scope queries (one architectural decision at a
time, or one mode at a time), not whole-system synthesis.

## What we DO know from the partial run

The error appeared after Codex was midway through reading
`src/donna/agent/loop.py` around line 100. By that point it had
absorbed the prompt + at least the agent core + likely most modes.
Given the same input context as GPT-5.3-codex (which completed with a
specific, opinionated review), the pro tier should produce comparable
or stronger findings on the same scope when given enough budget.

## Recommendation

Default model stays `gpt-5.5-pro` per operator's "always use best
model" directive. For full deep-dive reviews against ~30k-token prompts,
**use `gpt-5.3-codex` until pro budget allows**. The codex variant
produced a complete, substantive review (162 lines, 13 sections,
novel findings) within the same input budget.

The synthesis at [`REVIEW_SYNTHESIS_v0.4.0.md`](REVIEW_SYNTHESIS_v0.4.0.md)
incorporates the GPT-5 + GPT-5.3-codex findings + the Claude review +
the market research. The 5.5-pro retry is a TODO.
