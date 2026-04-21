"""Regression tests for Pattern A (Hermes-inspired v1.1 additions)."""
from __future__ import annotations

import inspect

import pytest


# --- ModelRuntime registry module exists & has the expected shape ---------


def test_runtimes_module_importable() -> None:
    from donna.memory import runtimes
    assert hasattr(runtimes, "get_by_tier")
    assert hasattr(runtimes, "get_by_model_id")
    assert hasattr(runtimes, "list_runtimes")
    assert hasattr(runtimes, "add_runtime")


def test_runtime_dataclass_has_pricing_fields() -> None:
    from donna.memory.runtimes import Runtime
    names = {f.name for f in Runtime.__dataclass_fields__.values()}
    for f in (
        "provider", "model_id", "tier", "api_key_env",
        "price_input", "price_output", "price_cache_read", "price_cache_write",
        "active", "api_base", "context_limit",
    ):
        assert f in names, f"Runtime missing field: {f}"


def test_runtime_lookup_with_seeded_db(fresh_db) -> None:
    """Migration 0001 + 0004 seed three Anthropic runtimes (fast/strong/heavy)."""
    from donna.memory import runtimes as rt_mod
    rt_mod.clear_cache()
    fast = rt_mod.get_by_tier("fast", "anthropic")
    assert fast is not None
    assert fast.provider == "anthropic"
    assert fast.tier == "fast"
    assert "haiku" in fast.model_id.lower()
    assert fast.price_input > 0
    strong = rt_mod.get_by_tier("strong", "anthropic")
    assert strong is not None
    assert "sonnet" in strong.model_id.lower()
    heavy = rt_mod.get_by_tier("heavy", "anthropic")
    assert heavy is not None
    assert "opus" in heavy.model_id.lower()


def test_get_by_model_id_returns_matching_pricing(fresh_db) -> None:
    from donna.memory import runtimes as rt_mod
    rt_mod.clear_cache()
    strong = rt_mod.get_by_tier("strong", "anthropic")
    assert strong is not None
    resolved = rt_mod.get_by_model_id(strong.model_id)
    assert resolved is not None
    assert resolved.id == strong.id
    assert resolved.price_input == strong.price_input


# --- cost_mod reads pricing from the registry, not hardcoded --------------


def test_cost_pricing_consults_runtime_registry() -> None:
    from donna.memory import cost
    src = inspect.getsource(cost._pricing_for)
    assert "runtimes" in src
    assert "get_by_model_id" in src


# --- model_adapter.resolve_model routes via registry ----------------------


def test_model_adapter_resolve_model_uses_registry() -> None:
    from donna.agent import model_adapter
    assert hasattr(model_adapter.AnthropicAdapter, "resolve_model")
    src = inspect.getsource(model_adapter.AnthropicAdapter.resolve_model)
    assert "runtimes" in src or "get_by_tier" in src


# --- /model command + thread override --------------------------------------


def test_threads_has_set_and_get_tier_override() -> None:
    from donna.memory import threads
    assert hasattr(threads, "set_model_tier_override")
    assert hasattr(threads, "get_model_tier_override")


def test_loop_pick_tier_consults_thread_override() -> None:
    from donna.agent import loop
    src = inspect.getsource(loop._pick_tier)
    assert "model_tier_override" in src or "get_model_tier_override" in src


def test_set_and_read_thread_tier_override(fresh_db) -> None:
    from donna.memory import threads as threads_mod
    from donna.memory.db import connect, transaction
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, discord_channel="12345", discord_thread=None,
            )
            threads_mod.set_model_tier_override(conn, thread_id=tid, tier="heavy")
        got = threads_mod.get_model_tier_override(conn, thread_id=tid)
        assert got == "heavy"
        with transaction(conn):
            threads_mod.set_model_tier_override(conn, thread_id=tid, tier=None)
        got = threads_mod.get_model_tier_override(conn, thread_id=tid)
        assert got is None
    finally:
        conn.close()


# --- Compaction audit trail -----------------------------------------------


def test_compaction_saves_pre_compaction_as_artifact() -> None:
    """compact_messages should call save_artifact before summarizing."""
    from donna.agent import compaction
    src = inspect.getsource(compaction.compact_messages)
    assert "save_artifact" in src
    assert "compaction_log" in src


def test_compact_messages_accepts_job_id_kwarg() -> None:
    from donna.agent import compaction
    sig = inspect.signature(compaction.compact_messages)
    assert "job_id" in sig.parameters


def test_context_passes_job_id_to_compact() -> None:
    from donna.agent import context
    src = inspect.getsource(context.JobContext.maybe_compact)
    assert "job_id" in src
