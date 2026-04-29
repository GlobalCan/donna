"""Eval suite ratchet — pytest wrapper that loads every golden under
`evals/golden/` and dispatches via the runner. Asserts no FAILs;
SKIPs are tolerated (those need `--live` + real model spend).

This is what makes the eval suite a CI gate. Without this, the runner
is a developer tool but doesn't catch regressions in normal `pytest -q`.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from evals.runner import load_goldens, run_one_async

GOLDEN_ROOT = Path(__file__).resolve().parent.parent / "evals" / "golden"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_all_goldens_pass_or_skip() -> None:
    """Iterate every golden; assert no FAIL outcomes. SKIPs (live-required)
    are reported but don't fail the gate."""
    goldens = load_goldens(GOLDEN_ROOT)
    assert goldens, f"no goldens found under {GOLDEN_ROOT}"

    failures: list[tuple[str, str]] = []
    skipped = 0
    passed = 0
    for g in goldens:
        r = await run_one_async(g, live=False)
        if r.status == "FAIL":
            failures.append((r.case_id, r.reason))
        elif r.status == "SKIP":
            skipped += 1
        else:
            passed += 1

    assert not failures, (
        f"{len(failures)} eval golden(s) FAILED:\n"
        + "\n".join(f"  - {cid}: {reason}" for cid, reason in failures)
    )
    # Sanity: at least one offline case ran. If they're all SKIP we lost
    # the ratchet entirely.
    assert passed > 0, (
        f"all {len(goldens)} goldens skipped; no offline coverage "
        f"(skipped={skipped})"
    )
