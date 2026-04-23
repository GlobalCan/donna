"""Regression tests for Codex Pass-2 (challenge review) fixes."""
from __future__ import annotations

import json

from donna.security.validator import validate_grounded
from donna.types import Chunk


def _c(id_: str, content: str) -> Chunk:
    return Chunk(
        id=id_, source_id="s1", agent_scope="test",
        work_id="w1", publication_date="2020-01-01", source_type="book",
        content=content, score=1.0, chunk_index=0, is_style_anchor=False,
        source_title="Test",
    )


# --- Pass 2 #11: quoted_span enforcement -----------------------------------


def test_quoted_span_verbatim_required() -> None:
    """Claim with a valid verbatim quoted_span >=20 chars passes."""
    chunks = [_c("chunk_1",
                 "Lewis argues that outsiders systematically see what insiders miss, "
                 "exploiting structural blindspots in modern markets.")]
    resp = json.dumps({
        "claims": [{
            "text": "Lewis argues outsiders see systemic blindspots.",
            "citations": ["#chunk_1"],
            "quoted_span": "outsiders systematically see what insiders miss",
        }],
        "prose": "..."
    })
    r = validate_grounded(resp, chunks)
    assert r.ok, f"expected pass; got issues: {r.issues}"


def test_quoted_span_fabricated_rejected() -> None:
    """Claim with quoted_span NOT in the chunk must be rejected."""
    chunks = [_c("chunk_1", "A short chunk about cats and dogs.")]
    resp = json.dumps({
        "claims": [{
            "text": "Dogs are superior to cats in every way.",
            "citations": ["#chunk_1"],
            "quoted_span": "dogs are superior to cats in every way",  # fabricated
        }],
        "prose": "..."
    })
    r = validate_grounded(resp, chunks)
    assert not r.ok
    assert any("quoted_span_not_in_chunk" in i.reason for i in r.issues)


def test_quoted_span_too_short_rejected() -> None:
    """Quoted span shorter than min_len (20) doesn't count as verbatim proof."""
    chunks = [_c("chunk_1", "A discussion of markets and their efficiency.")]
    resp = json.dumps({
        "claims": [{
            "text": "Markets exist.",
            "citations": ["#chunk_1"],
            "quoted_span": "markets",  # only 7 chars
        }],
        "prose": "...",
    })
    r = validate_grounded(resp, chunks)
    assert not r.ok


def test_quoted_span_missing_rejected() -> None:
    """Claim with no quoted_span must be rejected under the new rule."""
    chunks = [_c("chunk_1", "Content content content.")]
    resp = json.dumps({
        "claims": [{
            "text": "Some claim.",
            "citations": ["#chunk_1"],
        }],
        "prose": "...",
    })
    r = validate_grounded(resp, chunks)
    assert not r.ok
    assert any("quoted_span_missing" in i.reason for i in r.issues)


def test_quoted_span_case_and_whitespace_insensitive() -> None:
    chunks = [_c("chunk_1",
                 "The Big Short told the story of mortgage-market speculators who bet against housing.")]
    resp = json.dumps({
        "claims": [{
            "text": "Speculators bet against the housing market.",
            "citations": ["#chunk_1"],
            "quoted_span": "mortgage-market   speculators who bet against",  # extra whitespace
        }],
        "prose": "...",
    })
    r = validate_grounded(resp, chunks)
    assert r.ok, f"whitespace/case should not matter: {r.issues}"


# --- Pass 2 #5: persistent consent --------------------------------------


def test_pending_consent_has_pending_id_field() -> None:
    """ConsentRequest now carries pending_id for cleanup after resolution."""
    import dataclasses as dc

    from donna.security.consent import ConsentRequest
    fields = {f.name for f in dc.fields(ConsentRequest)}
    assert "pending_id" in fields


def test_list_unresolved_pendings_exported() -> None:
    """Adapter needs this at startup to re-prompt for surviving pendings."""
    from donna.security import consent as c
    assert hasattr(c, "list_unresolved_pendings")


# --- Pass 2 #2+#15: JobContext unified primitives -----------------------


def test_jobcontext_has_shared_primitives() -> None:
    from donna.agent.context import JobContext
    # Every mode should use these — they're the "shared graph primitives"
    assert callable(getattr(JobContext, "model_step", None))
    assert callable(getattr(JobContext, "tool_step", None))
    assert callable(getattr(JobContext, "checkpoint", None))
    assert callable(getattr(JobContext, "finalize", None))
    assert callable(getattr(JobContext, "maybe_compact", None))


def test_loop_dispatches_to_context_based_modes() -> None:
    """run_job uses JobContext.open and dispatches by mode."""
    import inspect

    from donna.agent import loop
    src = inspect.getsource(loop.run_job)
    assert "JobContext.open" in src
    # All four modes explicitly handled
    assert "JobMode.GROUNDED" in src
    assert "JobMode.SPECULATIVE" in src
    assert "JobMode.DEBATE" in src


# --- Pass 2 #14: attachment tool + heuristic reasoning ------------------


def test_attachment_tool_registered() -> None:
    from donna.tools.registry import REGISTRY
    assert "ingest_discord_attachment" in REGISTRY
    entry = REGISTRY["ingest_discord_attachment"]
    assert entry.taints_job is True


def test_heuristic_reasoning_persists_in_provenance() -> None:
    """propose_heuristic's `reasoning` field should make it to the DB."""
    import inspect

    from donna.memory import prompts as prompts_mod
    sig = inspect.signature(prompts_mod.insert_heuristic)
    assert "reasoning" in sig.parameters


# --- Pass 2 #4: search snippet sanitization -----------------------------


def test_search_web_has_sanitize_helper() -> None:
    from donna.tools.web import _sanitize_hits
    assert callable(_sanitize_hits)


# --- Pass 2 #3+#7: native sqlite-vec retrieval --------------------------


def test_knowledge_module_uses_vec_distance() -> None:
    import inspect

    from donna.memory import knowledge
    src = inspect.getsource(knowledge.semantic_search)
    assert "vec_distance_cosine" in src, "semantic_search should use sqlite-vec's native function"


# --- Pass 2 #13: watchdog + trace store ---------------------------------


def test_watchdog_importable() -> None:
    from donna.observability.watchdog import Watchdog
    assert callable(getattr(Watchdog, "tick", None))
    assert callable(getattr(Watchdog, "loop", None))


def test_trace_store_processor_importable() -> None:
    from donna.observability.trace_store import SqliteSpanProcessor
    sp = SqliteSpanProcessor()
    assert callable(getattr(sp, "on_end", None))


# --- Pass 2 #10: cache-hit-rate CLI -------------------------------------


def test_botctl_has_cache_hit_rate() -> None:
    """Typer populates `.name` from the decorator kwarg; when the function
    name is used as-is, `.name` is None. Inspect callback names instead."""
    from donna.cli import botctl
    callback_names = {
        cmd.callback.__name__ for cmd in botctl.app.registered_commands
        if cmd.callback is not None
    }
    assert "cache_hit_rate" in callback_names, f"got callbacks: {callback_names}"


# --- "Anything else logical" pass ---------------------------------------


def test_facts_last_used_is_async_fire_and_forget() -> None:
    """facts.search_facts_fts no longer mutates last_used_at synchronously
    on the same connection."""
    import inspect

    from donna.memory import facts
    src = inspect.getsource(facts.search_facts_fts)
    assert "_touch_last_used_async" in src
    assert "conn.execute" not in src.split("if rows:")[-1]  # no sync UPDATE after rows
