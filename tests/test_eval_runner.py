"""Unit tests for `evals.runner` — pin tri-state status, schema lint, and
the dispatch surface. These run offline; they don't load the actual
golden files (see `test_evals_smoke.py` for the integration ratchet).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from evals.runner import (
    load_goldens,
    run_one,
    run_one_async,
    schema_lint,
)

# ---------- schema_lint ---------------------------------------------------


def test_schema_lint_passes_well_formed_case() -> None:
    g = {
        "id": "x", "description": "y", "capability": "debate",
        "setup": {}, "input": {}, "expect": {},
    }
    assert schema_lint(g) is None


@pytest.mark.parametrize("missing_key", ["id", "description", "capability", "setup", "input", "expect"])
def test_schema_lint_flags_missing_top_level_keys(missing_key: str) -> None:
    g = {
        "id": "x", "description": "y", "capability": "debate",
        "setup": {}, "input": {}, "expect": {},
    }
    del g[missing_key]
    err = schema_lint(g)
    assert err is not None
    assert missing_key in err


def test_schema_lint_flags_unknown_capability() -> None:
    g = {
        "id": "x", "description": "y", "capability": "elephant_facts",
        "setup": {}, "input": {}, "expect": {},
    }
    err = schema_lint(g)
    assert err is not None
    assert "elephant_facts" in err


def test_schema_lint_flags_non_dict_setup() -> None:
    g = {
        "id": "x", "description": "y", "capability": "debate",
        "setup": "string-not-dict", "input": {}, "expect": {},
    }
    err = schema_lint(g)
    assert err is not None
    assert "setup" in err


def test_schema_lint_flags_empty_id() -> None:
    g = {
        "id": "   ", "description": "y", "capability": "debate",
        "setup": {}, "input": {}, "expect": {},
    }
    err = schema_lint(g)
    assert err is not None
    assert "id" in err


# ---------- run_one tri-state ---------------------------------------------


def test_run_one_skip_for_grounded_offline() -> None:
    """The whole point of the rewrite — grounded cases without --live
    should be SKIPPED, not silently PASSED."""
    g = {
        "id": "g_test", "description": "needs live model",
        "capability": "grounded",
        "setup": {}, "input": {}, "expect": {},
    }
    r = run_one(g, live=False)
    assert r.status == "SKIP"
    assert r.case_id == "g_test"
    assert r.capability == "grounded"


def test_run_one_skip_for_speculative_offline() -> None:
    g = {
        "id": "s_test", "description": "needs live model",
        "capability": "speculative",
        "setup": {}, "input": {}, "expect": {},
    }
    r = run_one(g, live=False)
    assert r.status == "SKIP"


def test_run_one_fail_for_malformed_case() -> None:
    """Schema lint runs first; missing keys mean FAIL even if the case
    would otherwise dispatch successfully."""
    g = {"id": "broken", "capability": "debate"}  # missing description, etc.
    r = run_one(g, live=False)
    assert r.status == "FAIL"
    assert "schema lint" in r.reason.lower()


def test_run_one_pass_for_valid_debate_case() -> None:
    g = {
        "id": "deb_pass",
        "description": "validator catches attack-without-quote",
        "capability": "debate",
        "setup": {
            "prior_turns": [{"round": 1, "scope": "lewis",
                             "content": "Markets are efficient."}],
        },
        "input": {
            "current_scope": "dalio",
            "turn_text": "Lewis argues that markets clear fast.",
        },
        "expect": {"flagged_issue_contains": "attacks_without_quote"},
    }
    r = run_one(g, live=False)
    assert r.status == "PASS", r.reason


def test_run_one_fail_for_unknown_capability() -> None:
    """The schema_lint should reject this first — but if capability slipped
    past lint somehow, the dispatcher's else branch returns FAIL."""
    g = {
        "id": "bad_cap", "description": "x",
        "capability": "ostrich_strategy",
        "setup": {}, "input": {}, "expect": {},
    }
    r = run_one(g, live=False)
    assert r.status == "FAIL"


# ---------- load_goldens raises on parse errors ---------------------------


def test_load_goldens_raises_on_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "broken.yaml"
    bad.write_text("id: x\n  bad: indentation: here\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="failed to parse"):
        load_goldens(tmp_path)


def test_load_goldens_raises_on_non_mapping_top_level(tmp_path: Path) -> None:
    bad = tmp_path / "list_not_dict.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="must be a mapping"):
        load_goldens(tmp_path)


def test_load_goldens_returns_empty_when_dir_has_no_yamls(tmp_path: Path) -> None:
    (tmp_path / "not_a_yaml.txt").write_text("ignored", encoding="utf-8")
    assert load_goldens(tmp_path) == []


# ---------- async dispatcher (taint_propagation needs a DB) ---------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_run_one_async_passes_taint_dirty_case() -> None:
    """End-to-end smoke for the taint_propagation dispatcher: tainted
    source → tainted=true expected → PASS."""
    g = {
        "id": "taint_dirty_async",
        "description": "tainted source produces tainted retrieval",
        "capability": "taint_propagation",
        "setup": {
            "scope": "eval_unit_dirty",
            "source_tainted": True,
            "chunks": [
                {"content": "alpha bravo charlie payload"},
                {"content": "delta echo foxtrot payload"},
            ],
        },
        "input": {"query": "payload"},
        "expect": {"tainted": True},
    }
    r = await run_one_async(g, live=False)
    assert r.status == "PASS", r.reason


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_run_one_async_passes_taint_clean_case() -> None:
    g = {
        "id": "taint_clean_async",
        "description": "clean source produces tainted=false retrieval",
        "capability": "taint_propagation",
        "setup": {
            "scope": "eval_unit_clean",
            "source_tainted": False,
            "chunks": [{"content": "kilo lima mike payload"}],
        },
        "input": {"query": "payload"},
        "expect": {"tainted": False},
    }
    r = await run_one_async(g, live=False)
    assert r.status == "PASS", r.reason


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_run_one_async_fails_when_taint_mismatches() -> None:
    """Negative test: declared expect.tainted=true but seeded clean → FAIL."""
    g = {
        "id": "taint_mismatch",
        "description": "negative: clean source but expects tainted",
        "capability": "taint_propagation",
        "setup": {
            "scope": "eval_unit_mismatch",
            "source_tainted": False,
            "chunks": [{"content": "papa quebec romeo payload"}],
        },
        "input": {"query": "payload"},
        "expect": {"tainted": True},
    }
    r = await run_one_async(g, live=False)
    assert r.status == "FAIL"
    assert "taint mismatch" in r.reason


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_run_one_async_passes_grounded_refusal() -> None:
    """Empty-corpus refusal is offline-runnable: retrieve_knowledge returns
    no chunks, which is the refusal path's trigger."""
    g = {
        "id": "refusal_async",
        "description": "no chunks for empty scope",
        "capability": "grounded_refusal",
        "setup": {"scope": "eval_empty_scope"},
        "input": {"question": "anything"},
        "expect": {"refused": True},
    }
    r = await run_one_async(g, live=False)
    assert r.status == "PASS", r.reason
