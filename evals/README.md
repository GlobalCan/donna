# Donna eval suite

Golden-case ratchet for grounded mode + taint propagation + debate
validator. Runs offline by default (no model spend); `--live` adds
real-model checks.

## Layout

- `runner.py` — loads YAMLs, dispatches by capability, asserts.
- `golden/*.yaml` — one case per file. See schema below.

## Run

```bash
python -m evals.runner            # offline (CI default)
python -m evals.runner --live     # also runs cases that need a real model
```

CLI prints `PASS / FAIL / SKIP` per case and exits 0 if no FAILs.
SKIPs do not fail the run.

There is also a pytest wrapper at `tests/test_evals_smoke.py` so the
suite gates on `pytest -q`.

## Case schema

Every golden YAML must be a mapping with these top-level keys:

```yaml
id: short_unique_slug
description: One-paragraph human-readable summary.
capability: grounded_refusal | taint_propagation | debate | grounded | speculative
setup:    {capability-specific}
input:    {capability-specific}
expect:   {capability-specific}
```

`schema_lint()` enforces these keys + types before dispatch.
A missing field is **FAIL**, never SKIP — the case is malformed.

## Capabilities

### `grounded_refusal` (offline)

Asserts that an empty-corpus grounded query produces no chunks
(triggering the refusal path in `run_grounded` without a model call).

```yaml
setup:
  scope: author_empty_test       # any scope with no seeded corpus
input:
  question: "anything"
expect:
  refused: true                  # required; verified by chunks == []
```

### `taint_propagation` (offline)

Seeds a `knowledge_sources` row + chunks with the given taint, then
calls `retrieve_knowledge` and asserts the returned `tainted` flag
matches `expect.tainted`. Verifies the cross-vendor-review-#1 fix
stays in place across refactors.

```yaml
setup:
  scope: eval_taint_*
  source_tainted: true|false
  chunks:
    - {content: "..."}           # FTS-indexed text
    - {content: "..."}
input:
  query: "..."                   # must match seeded content
expect:
  tainted: true|false
```

### `debate` (offline)

Runs `validate_debate_turn` against a synthetic prior + turn and asserts
the validator flags `expect.flagged_issue_contains`.

```yaml
setup:
  prior_turns:
    - {round: 1, scope: lewis, content: "..."}
input:
  current_scope: dalio
  turn_text: "Lewis argues that..."
expect:
  flagged_issue_contains: "attacks_without_quote"
```

### `grounded` and `speculative` (live-only)

Cases that require a real model call. **SKIPPED** offline (`--live`
unset). The previous runner returned PASS for these without exercising
any assertion; that was a false ratchet and is what this rewrite fixes.

When the live runner ships, these will run end-to-end against the
configured model. Track via `evals/runner.py::run_one_async`.

## Why the ratchet matters

Cross-vendor review (Claude + Codex GPT-5 + Codex GPT-5.3-codex) flagged
the prior `_run_one` as a false ratchet:

```python
# OLD — silently PASSED everything that wasn't `live`:
if cap in ("grounded", "speculative") and not live:
    return True
```

The rewrite splits PASS / FAIL / SKIP, runs every case that CAN run
offline, and refuses to fake-pass cases that genuinely need a live model.
Adding a new failure mode to `run_grounded` or `retrieve_knowledge`
without updating the goldens now flips this suite from green to red.

## Adding new cases

1. Pick the right `capability`. If your case can be checked without a
   model, prefer `grounded_refusal` / `taint_propagation` / `debate`
   over the model-required ones.
2. Save as `golden/NN_short_name.yaml` with the next sequential prefix.
3. Run `python -m evals.runner` and confirm PASS.
4. Add structural tests if the case exercises a new code path.
