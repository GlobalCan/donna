"""Cross-vendor review finding §3.1 / Codex GPT-5.3-codex RF1.

The tool-call wrapper `tools.knowledge.recall_knowledge` was already
propagating taint (see `test_list_taint_propagation.py`), but every mode
handler (grounded / speculative / debate / chat) called the underlying
`modes.retrieval.retrieve_knowledge` directly, bypassing the wrapper.
A tainted corpus row would shape grounded answers without the job's
`state.tainted` flag flipping — defeating the consent-escalation gates
that downstream `remember` / `run_python` / write-tool calls depend on.

Fix moves the taint check into `retrieve_knowledge` itself, and every
caller (the tool wrapper plus the four mode handlers plus the chat-mode
`_load_scoped_context`) now propagates `retrieval["tainted"]` to
`JobContext.state.tainted`.

These tests pin:

1. `retrieve_knowledge` sets `tainted=True` when any chosen chunk's
   source has `knowledge_sources.tainted=1`, and `tainted=False` when
   no tainted source is involved or the result is empty.
2. The tool wrapper `recall_knowledge` inherits the flag transparently
   (used to do its own check, now relies on retrieve_knowledge).
3. Each mode handler that calls `retrieve_knowledge` directly
   propagates the flag onto `ctx.state.tainted`. Run paths covered:
   grounded, speculative, debate, chat (via `_load_scoped_context`).

Attack shape closed by this fix:

  fetch_url(attacker.com) → save_artifact (tainted=1)
  → operator runs `botctl teach` against that artifact, or the model
     calls `teach` with the artifact's content
  → knowledge_sources row is `tainted=1`
  → user runs `/ask scope:tainted_scope ...` (grounded mode)
  → retrieve_knowledge returns chunks from tainted source
  → BEFORE FIX: ctx.state.tainted stays False; the model's `remember`
     or `run_python` call goes through without consent escalation
  → AFTER FIX: ctx.state.tainted flips True on retrieval; subsequent
     write/exec tools fire the consent gate.
"""
from __future__ import annotations

import pytest

from donna.memory.db import connect, transaction
from donna.types import JobMode, JobState

# ---------- shared fixtures ------------------------------------------------


def _seed_chunks(scope: str, *, tainted: bool, n: int = 3) -> list[str]:
    """Insert `n` knowledge_chunks under a scope; source has the given
    taint. Returns the chunk ids inserted. Embeddings are zero-padded
    floats; FTS picks them up via the AFTER INSERT trigger."""
    src_id = f"src_{'dirty' if tainted else 'clean'}_{scope}"
    chunk_ids: list[str] = []
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO knowledge_sources "
                "(id, agent_scope, source_type, title, copyright_status, added_by, tainted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (src_id, scope, "article", f"src for {scope}",
                 "personal_use" if tainted else "public_domain",
                 "tool:ingest_discord_attachment" if tainted else "test",
                 1 if tainted else 0),
            )
            for i in range(n):
                cid = f"ch_{src_id}_{i}"
                conn.execute(
                    "INSERT INTO knowledge_chunks "
                    "(id, source_id, agent_scope, work_id, publication_date, "
                    " source_type, content, embedding, chunk_index, token_count, "
                    " fingerprint, is_style_anchor) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (cid, src_id, scope, f"work_{i}", "2024-01-01",
                     "article",
                     f"this is chunk number {i} for scope {scope} content body",
                     None, i, 50, f"fp_{src_id}_{i}", 0),
                )
                chunk_ids.append(cid)
    finally:
        conn.close()
    return chunk_ids


def _make_ctx(scope: str = "author_twain", task: str = "chunk content body") -> object:
    """Build a JobContext-shaped object with just the surface mode handlers
    poke at — `state`, `job.agent_scope`, `job.task`, `job.id`, plus
    `check_cancelled` + `checkpoint_or_raise` no-ops + `model_step` stub.
    Real JobContext requires DB and worker plumbing we don't need here."""
    from types import SimpleNamespace

    state = JobState(job_id="job_test", agent_scope=scope, mode=JobMode.GROUNDED)

    async def _no_model_step(*a, **kw):
        return SimpleNamespace(text="{}", raw_content=[], tool_uses=[], stop_reason="end_turn")

    return SimpleNamespace(
        state=state,
        job=SimpleNamespace(id="job_test", agent_scope=scope, task=task,
                            mode=JobMode.GROUNDED, thread_id=None),
        worker_id="w_test",
        check_cancelled=lambda: None,
        checkpoint_or_raise=lambda: None,
        model_step=_no_model_step,
    )


# ---------- 1. retrieve_knowledge sets the flag ----------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_retrieve_knowledge_marks_tainted_when_source_is_tainted() -> None:
    from donna.modes.retrieval import retrieve_knowledge

    _seed_chunks("author_twain", tainted=True)
    out = await retrieve_knowledge(scope="author_twain", query="chunk content body")
    assert out["chunks"], "seeded chunks should surface for keyword query"
    assert out.get("tainted") is True, (
        "retrieve_knowledge must set tainted=True when any chosen chunk's "
        "source row has knowledge_sources.tainted=1"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_retrieve_knowledge_clean_corpus_is_not_tainted() -> None:
    from donna.modes.retrieval import retrieve_knowledge

    _seed_chunks("author_twain", tainted=False)
    out = await retrieve_knowledge(scope="author_twain", query="chunk content body")
    assert out["chunks"]
    assert out.get("tainted") is False


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_retrieve_knowledge_empty_corpus_is_not_tainted() -> None:
    from donna.modes.retrieval import retrieve_knowledge

    out = await retrieve_knowledge(scope="author_nobody", query="anything")
    assert out["chunks"] == []
    assert out.get("tainted") is False


# ---------- 2. tool wrapper inherits the flag ------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_recall_knowledge_wrapper_inherits_tainted_flag() -> None:
    """`tools.knowledge.recall_knowledge` used to do its own taint check.
    After the cross-vendor fix it just delegates to `retrieve_knowledge`,
    which is the single source of truth. The flag must still appear on
    the wrapper's return so JobContext._execute_one's tool-result check
    (`agent/context.py:245`) propagates onto state.tainted."""
    from donna.tools.knowledge import recall_knowledge

    _seed_chunks("author_twain", tainted=True)
    out = await recall_knowledge(scope="author_twain", query="chunk content body")
    assert out.get("tainted") is True


# ---------- 3. mode handlers propagate to ctx.state.tainted ----------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_grounded_propagates_retrieval_taint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_grounded calls retrieve_knowledge directly, not through the
    tool wrapper. It must set ctx.state.tainted when retrieval is tainted."""
    from donna.modes import grounded as grounded_mod

    _seed_chunks("author_twain", tainted=True)
    ctx = _make_ctx()
    # Stub the model + validator so we don't need full LLM plumbing
    monkeypatch.setattr(
        grounded_mod, "validate_grounded",
        lambda raw, chunks: type("V", (), {"ok": True, "issues": []})(),
    )

    await grounded_mod.run_grounded(ctx)
    assert ctx.state.tainted is True, (
        "run_grounded must propagate retrieve_knowledge's tainted flag "
        "onto ctx.state.tainted; otherwise downstream consent gates miss "
        "the fact that the model's context contains attacker-controlled bytes"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_grounded_clean_corpus_does_not_taint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from donna.modes import grounded as grounded_mod

    _seed_chunks("author_twain", tainted=False)
    ctx = _make_ctx()
    monkeypatch.setattr(
        grounded_mod, "validate_grounded",
        lambda raw, chunks: type("V", (), {"ok": True, "issues": []})(),
    )

    await grounded_mod.run_grounded(ctx)
    assert ctx.state.tainted is False


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_speculative_propagates_retrieval_taint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from donna.memory import prompts as prompts_mod
    from donna.modes import speculative as speculative_mod

    _seed_chunks("author_twain", tainted=True)
    # speculative.py refuses unless agent_prompts.speculation_allowed = 1.
    # Stub active_prompt to return a permissive row so the retrieval path runs.
    monkeypatch.setattr(
        prompts_mod, "active_prompt",
        lambda conn, scope: {
            "id": "p1", "scope": scope, "speculation_allowed": 1,
            "system_prompt": "stub", "voice_card": None, "guardrails": None,
        },
    )

    ctx = _make_ctx(scope="author_twain")
    ctx.state.mode = JobMode.SPECULATIVE
    await speculative_mod.run_speculative(ctx)
    assert ctx.state.tainted is True


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_debate_propagates_retrieval_taint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """debate runs retrieve_knowledge per (round × scope). A tainted
    chunk in any round taints the whole job."""
    from donna.modes import debate as debate_mod

    _seed_chunks("author_twain", tainted=True)
    _seed_chunks("author_dalio", tainted=False)

    ctx = _make_ctx(scope="orchestrator")
    ctx.state.mode = JobMode.DEBATE

    # Stub validate_debate_turn so the loop doesn't need real schema
    monkeypatch.setattr(debate_mod, "validate_debate_turn", lambda *a, **kw: [])

    await debate_mod._debate_core(
        topic="chunk content body", scopes=["author_twain", "author_dalio"],
        rounds=1, ctx=ctx,
    )
    assert ctx.state.tainted is True, (
        "debate.run with one tainted scope must taint the orchestrator job"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_chat_load_scoped_context_returns_tainted_flag() -> None:
    """`agent/loop.py::_load_scoped_context` returns
    `(chunks, examples, anchors, tainted)`. Chat mode must propagate that
    flag onto ctx.state.tainted at the loop iteration boundary."""
    from donna.agent.loop import _load_scoped_context

    _seed_chunks("author_twain", tainted=True)
    chunks, examples, anchors, tainted = await _load_scoped_context(
        "author_twain", "chunk content body",
    )
    assert chunks, "seeded chunks should surface"
    assert tainted is True


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_chat_load_scoped_context_orchestrator_short_circuits() -> None:
    """orchestrator scope skips retrieval entirely (no corpus). Must
    return tainted=False without querying the DB."""
    from donna.agent.loop import _load_scoped_context

    chunks, examples, anchors, tainted = await _load_scoped_context(
        "orchestrator", "anything",
    )
    assert chunks == []
    assert tainted is False
