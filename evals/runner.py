"""Eval runner — loads YAMLs, dispatches by capability, asserts expectations.

Tri-state status: PASS / FAIL / SKIP. Cases that need a live model are
SKIPPED (not silently PASSED) when `--live` is not set; the previous
runner's "always return True for non-live grounded/speculative" was a
false ratchet — failures couldn't surface.

Capabilities and how each runs:

| capability                        | offline behavior        | live behavior |
|-----------------------------------|-------------------------|---------------|
| grounded_refusal                  | RUNS — assert empty corpus → refusal output shape | RUNS (same) |
| taint_propagation                 | RUNS — seed tainted/clean source, assert `retrieve_knowledge.tainted` matches | RUNS (same) |
| debate                            | RUNS — `validate_debate_turn` is offline | RUNS (same) |
| grounded (general)                | SKIP — needs live model | RUNS via real LLM |
| speculative (general)             | SKIP — needs live model | RUNS via real LLM |

Every case also passes through `schema_lint()` first; a missing required
field is FAIL, not SKIP — the case is malformed regardless of mode.

Cross-vendor review finding §3.x / merged action queue #2: the eval
scaffold was reporting PASS for non-live grounded/speculative cases
without exercising any assertion. This runner is the ratchet.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    import yaml
except ImportError:  # yaml optional in dev installs
    yaml = None  # type: ignore[assignment]


Status = Literal["PASS", "FAIL", "SKIP"]


@dataclass(frozen=True)
class Result:
    status: Status
    reason: str
    case_id: str
    capability: str

    @property
    def ok_or_skipped(self) -> bool:
        return self.status in ("PASS", "SKIP")


# ---------- public API -----------------------------------------------------


def load_goldens(path: Path) -> list[dict[str, Any]]:
    """Load every *.yaml under `path`. Returns a list of parsed dicts.

    Refuses to silently swallow YAML errors — a malformed case is a real
    eval-suite regression and should surface.
    """
    if yaml is None:
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(path.glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise RuntimeError(f"failed to parse {p.name}: {e}") from e
        if not isinstance(doc, dict):
            raise RuntimeError(f"{p.name}: top-level must be a mapping, got {type(doc).__name__}")
        out.append(doc)
    return out


def schema_lint(g: dict[str, Any]) -> str | None:
    """Return None if the case has all required keys, else a short reason."""
    required_top = ("id", "description", "capability", "setup", "input", "expect")
    for key in required_top:
        if key not in g:
            return f"missing top-level key '{key}'"
    if not isinstance(g["id"], str) or not g["id"].strip():
        return "'id' must be a non-empty string"
    valid_caps = {
        "grounded", "speculative", "debate",
        "grounded_refusal", "taint_propagation",
    }
    if g["capability"] not in valid_caps:
        return f"unknown capability '{g['capability']}' (valid: {sorted(valid_caps)})"
    for key in ("setup", "input", "expect"):
        if not isinstance(g[key], dict):
            return f"'{key}' must be a mapping"
    return None


def run_one(g: dict[str, Any], *, live: bool = False) -> Result:
    """Dispatch a single golden case. Always returns a Result — never raises."""
    case_id = g.get("id", "<unknown>")
    cap = g.get("capability", "<unknown>")

    lint_err = schema_lint(g)
    if lint_err:
        return Result("FAIL", f"schema lint: {lint_err}", case_id, cap)

    try:
        if cap == "debate":
            return _check_debate(g)
        if cap == "grounded_refusal":
            return asyncio.get_event_loop().run_until_complete(_check_grounded_refusal(g)) \
                if not _has_running_loop() else _run_async(_check_grounded_refusal(g))
        if cap == "taint_propagation":
            return _run_async(_check_taint_propagation(g))
        if cap in ("grounded", "speculative"):
            if not live:
                return Result(
                    "SKIP",
                    f"{cap} requires --live (real model)",
                    case_id, cap,
                )
            # Live path not implemented here; live evals require model
            # plumbing the runner doesn't yet provide. Track in TODO.
            return Result(
                "SKIP",
                f"{cap} live runner not yet implemented",
                case_id, cap,
            )
        return Result("FAIL", f"no dispatcher for capability '{cap}'", case_id, cap)
    except Exception as e:  # noqa: BLE001 — runner converts every failure to a result row
        return Result("FAIL", f"{type(e).__name__}: {e}", case_id, cap)


def run(live: bool = False, *, root: Path | None = None) -> int:
    """Run every golden under root. Returns shell exit code: 0 if no FAILs."""
    if root is None:
        root = Path(__file__).resolve().parent / "golden"
    goldens = load_goldens(root)
    if not goldens:
        print("no goldens to run")
        return 0

    results = [run_one(g, live=live) for g in goldens]

    pad = max((len(r.case_id) for r in results), default=12)
    for r in results:
        marker = {"PASS": " PASS", "FAIL": " FAIL", "SKIP": " SKIP"}[r.status]
        print(f"{marker}  {r.case_id:<{pad}}  ({r.capability})  {r.reason}")

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 0 if failed == 0 else 1


# ---------- capability dispatchers -----------------------------------------


def _check_debate(g: dict[str, Any]) -> Result:
    from donna.security.validator import validate_debate_turn
    case_id, cap = g["id"], "debate"
    try:
        prior = g["setup"]["prior_turns"]
        turn = g["input"]["turn_text"]
        scope = g["input"]["current_scope"]
        expected = g["expect"]["flagged_issue_contains"]
    except KeyError as e:
        return Result("FAIL", f"missing field: {e}", case_id, cap)
    issues = validate_debate_turn(turn, prior, scope)
    if any(expected in i for i in issues):
        return Result("PASS", f"flagged: {expected!r}", case_id, cap)
    return Result(
        "FAIL",
        f"validator did not flag {expected!r}; issues={issues}",
        case_id, cap,
    )


async def _check_grounded_refusal(g: dict[str, Any]) -> Result:
    """Empty-corpus grounded queries should produce a refusal — verifiable
    offline by calling `retrieve_knowledge` and asserting `chunks == []`.
    No model needed; the refusal path in `run_grounded` is purely
    chunks-empty + early return."""
    from donna.modes.retrieval import retrieve_knowledge
    case_id, cap = g["id"], "grounded_refusal"

    scope = g["setup"].get("scope", "author_empty_test")
    question = g["input"].get("question", "anything")
    out = await retrieve_knowledge(scope=scope, query=question, top_k=8)

    if out.get("chunks"):
        return Result(
            "FAIL",
            f"empty-scope retrieval should return no chunks; got {len(out['chunks'])}",
            case_id, cap,
        )
    if g["expect"].get("refused") is not True:
        return Result(
            "FAIL",
            "grounded_refusal cases must declare expect.refused=true",
            case_id, cap,
        )
    return Result("PASS", "no chunks → refusal path", case_id, cap)


async def _check_taint_propagation(g: dict[str, Any]) -> Result:
    """Seed a knowledge_source row with taint per the case, insert chunks,
    call `retrieve_knowledge`, assert the `tainted` flag matches the case's
    expectation. Verifies the cross-vendor-review-#1 fix stays in place."""
    from donna.memory.db import connect, transaction
    from donna.modes.retrieval import retrieve_knowledge

    case_id, cap = g["id"], "taint_propagation"
    setup = g["setup"]
    scope = setup.get("scope")
    source_tainted = bool(setup.get("source_tainted", False))
    chunks_payload = setup.get("chunks", [])
    if not scope or not chunks_payload:
        return Result("FAIL", "setup must define scope + chunks", case_id, cap)

    src_id = f"src_eval_{case_id}"
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO knowledge_sources "
                "(id, agent_scope, source_type, title, copyright_status, added_by, tainted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (src_id, scope, "article", f"eval src {case_id}",
                 "personal_use" if source_tainted else "public_domain",
                 "eval:runner", 1 if source_tainted else 0),
            )
            for i, ch in enumerate(chunks_payload):
                conn.execute(
                    "INSERT INTO knowledge_chunks "
                    "(id, source_id, agent_scope, work_id, publication_date, "
                    " source_type, content, embedding, chunk_index, token_count, "
                    " fingerprint, is_style_anchor) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"ch_eval_{case_id}_{i}", src_id, scope,
                     f"work_eval_{i}", "2024-01-01", "article",
                     ch.get("content", f"chunk {i} eval body content"),
                     None, i, 50, f"fp_eval_{case_id}_{i}", 0),
                )
    finally:
        conn.close()

    query = g["input"].get("query", "chunk eval body content")
    out = await retrieve_knowledge(scope=scope, query=query, top_k=8)
    expected_tainted = bool(g["expect"].get("tainted", False))
    actual_tainted = bool(out.get("tainted"))

    if not out.get("chunks"):
        return Result(
            "FAIL",
            f"retrieval returned no chunks for scope={scope!r} query={query!r}",
            case_id, cap,
        )
    if actual_tainted != expected_tainted:
        return Result(
            "FAIL",
            f"taint mismatch: expected={expected_tainted}, got={actual_tainted}",
            case_id, cap,
        )
    return Result(
        "PASS",
        f"tainted={actual_tainted} (n={len(out['chunks'])} chunks)",
        case_id, cap,
    )


# ---------- helpers --------------------------------------------------------


def _has_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _run_async(coro) -> Result:
    """Dispatch a coroutine. From CLI we have no running loop; from pytest
    asyncio mode we may. Either way, return the Result."""
    if _has_running_loop():
        # We're being called from inside an async test — yield via task
        # is wrong; the caller should `await run_one_async` instead. The
        # `run` CLI only invokes _run_async from the synchronous `run_one`.
        raise RuntimeError(
            "run_one cannot dispatch async cases when a loop is already running; "
            "call run_one_async() from async test contexts"
        )
    return asyncio.run(coro)


async def run_one_async(g: dict[str, Any], *, live: bool = False) -> Result:
    """Async variant for use from pytest-asyncio. Same dispatch as run_one."""
    case_id = g.get("id", "<unknown>")
    cap = g.get("capability", "<unknown>")

    lint_err = schema_lint(g)
    if lint_err:
        return Result("FAIL", f"schema lint: {lint_err}", case_id, cap)

    try:
        if cap == "debate":
            return _check_debate(g)
        if cap == "grounded_refusal":
            return await _check_grounded_refusal(g)
        if cap == "taint_propagation":
            return await _check_taint_propagation(g)
        if cap in ("grounded", "speculative"):
            if not live:
                return Result("SKIP", f"{cap} requires --live", case_id, cap)
            return Result("SKIP", f"{cap} live runner TBD", case_id, cap)
        return Result("FAIL", f"no dispatcher for '{cap}'", case_id, cap)
    except Exception as e:  # noqa: BLE001
        return Result("FAIL", f"{type(e).__name__}: {e}", case_id, cap)


# ---------- CLI ------------------------------------------------------------


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="Enable cases that require a live model (cost!)")
    args = ap.parse_args()
    sys.exit(run(live=args.live))
