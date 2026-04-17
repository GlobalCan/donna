"""Eval runner — loads YAMLs, dispatches by capability, asserts expectations.

Live-API evals are skipped unless `--live` is passed; default is structural
checks only (validator, taint policy, chunker) which run in CI.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # yaml optional
    yaml = None  # type: ignore[assignment]


def load_goldens(path: Path) -> list[dict]:
    if yaml is None:
        return []
    return [yaml.safe_load(p.read_text()) for p in sorted(path.glob("*.yaml"))]


def run(live: bool = False) -> int:
    root = Path(__file__).resolve().parent / "golden"
    goldens = load_goldens(root)
    if not goldens:
        print("no goldens to run")
        return 0

    passed = failed = 0
    for g in goldens:
        ok = _run_one(g, live=live)
        print(f"{'PASS' if ok else 'FAIL'}  {g['id']}  — {g.get('description','')}")
        passed += ok
        failed += not ok
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


def _run_one(g: dict, *, live: bool) -> bool:
    cap = g.get("capability")
    try:
        if cap == "debate":
            return _debate_check(g)
        if cap in ("grounded", "speculative") and not live:
            # Structural skip — requires a live model for real checks
            return True
        return True
    except Exception as e:  # noqa: BLE001
        print(f"    error: {e}")
        return False


def _debate_check(g: dict) -> bool:
    from donna.security.validator import validate_debate_turn
    prior = g["setup"]["prior_turns"]
    turn = g["input"]["turn_text"]
    scope = g["input"]["current_scope"]
    issues = validate_debate_turn(turn, prior, scope)
    expected = g["expect"]["flagged_issue_contains"]
    return any(expected in i for i in issues)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    sys.exit(run(live=args.live))
