"""Compaction edge cases.

compact_messages replaces `messages[1:]` with a Haiku-generated summary
whenever `tool_calls_count % compact_every_n == 0`. Key invariants:

- Never compact lists ≤ 3 messages (guard at the top)
- Always preserve messages[0] (the initial user task)
- Always write the raw pre-compaction tail to an audit artifact BEFORE
  dropping it (Hermes-inspired session lineage — Codex Pass-2 #15 steal)
- Append the artifact id to jobs.compaction_log as queryable JSON
- Audit save failure must NOT crash the compaction — the summary still
  delivers; only the audit trail is lost

These tests exercise the structural contract without calling Haiku for
real. The `model` function is monkeypatched to return a fake result.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from donna.agent import compaction as compaction_mod
from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction


@dataclass
class _FakeResult:
    text: str
    cost_usd: float = 0.0


class _FakeModel:
    def __init__(self, text: str = "compacted summary") -> None:
        self.generate = AsyncMock(return_value=_FakeResult(text))


def _fake_model_factory(text: str = "compacted summary"):
    fake = _FakeModel(text)
    return fake, lambda: fake


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _make_job() -> str:
    conn = connect()
    try:
        with transaction(conn):
            return jobs_mod.insert_job(conn, task="test task")
    finally:
        conn.close()


# ---------- short-message guards --------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_returns_unchanged_for_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, factory = _fake_model_factory()
    monkeypatch.setattr(compaction_mod, "model", factory)

    result = await compaction_mod.compact_messages([], [])
    assert result == []
    fake.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_returns_unchanged_for_list_of_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, factory = _fake_model_factory()
    monkeypatch.setattr(compaction_mod, "model", factory)

    msgs = [_msg("user", "hi"), _msg("assistant", "hello")]
    result = await compaction_mod.compact_messages(msgs, [])
    assert result == msgs
    fake.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_returns_unchanged_for_list_of_3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge of the guard (`len <= 3`). Three messages isn't enough to
    benefit from compaction — the tail would be 2 messages, barely."""
    fake, factory = _fake_model_factory()
    monkeypatch.setattr(compaction_mod, "model", factory)

    msgs = [_msg("user", "hi"), _msg("assistant", "a"), _msg("user", "b")]
    result = await compaction_mod.compact_messages(msgs, [])
    assert result == msgs
    fake.generate.assert_not_called()


# ---------- happy-path compaction ------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_preserves_initial_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, factory = _fake_model_factory(text="compacted summary text")
    monkeypatch.setattr(compaction_mod, "model", factory)

    initial = _msg("user", "What's the capital of France?")
    msgs = [
        initial,
        _msg("assistant", "Let me search."),
        _msg("user", "[tool results]"),
        _msg("assistant", "Searching more."),
        _msg("user", "[more results]"),
    ]

    jid = _make_job()
    result = await compaction_mod.compact_messages(msgs, [], job_id=jid)

    assert len(result) == 2
    assert result[0] == initial, "initial user task must be preserved verbatim"
    assert result[1]["role"] == "user"
    assert "[CONTEXT COMPACTED" in result[1]["content"]
    assert "4 prior messages replaced" in result[1]["content"]
    assert "compacted summary text" in result[1]["content"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_writes_audit_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session-lineage invariant — every compaction MUST archive the raw
    pre-compaction tail as an artifact before dropping it. Without this
    the audit trail is broken and compacted jobs become opaque."""
    fake, factory = _fake_model_factory()
    monkeypatch.setattr(compaction_mod, "model", factory)

    msgs = [
        _msg("user", "task"),
        _msg("assistant", "unique_turn_A"),
        _msg("user", "[result_X]"),
        _msg("assistant", "unique_turn_B"),
        _msg("user", "[result_Y]"),
    ]
    jid = _make_job()
    await compaction_mod.compact_messages(msgs, [], job_id=jid)

    conn = connect()
    try:
        artifacts = conn.execute(
            "SELECT id, name, mime, tags FROM artifacts",
        ).fetchall()
    finally:
        conn.close()
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art["name"].startswith(f"compaction:{jid}:")
    assert art["mime"] == "application/json"
    assert "compaction" in art["tags"]
    assert "audit" in art["tags"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_records_in_compaction_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queryable lineage — jobs.compaction_log accumulates a JSON list of
    every compaction event, each with {artifact_id, replaced_count, at}."""
    fake, factory = _fake_model_factory()
    monkeypatch.setattr(compaction_mod, "model", factory)

    jid = _make_job()
    msgs = [
        _msg("user", "task"),
        _msg("assistant", "a"), _msg("user", "b"),
        _msg("assistant", "c"), _msg("user", "d"),
    ]
    await compaction_mod.compact_messages(msgs, [], job_id=jid)

    conn = connect()
    try:
        row = conn.execute(
            "SELECT compaction_log FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    log_entries = json.loads(row["compaction_log"])
    assert len(log_entries) == 1
    entry = log_entries[0]
    assert "artifact_id" in entry
    assert entry["replaced_count"] == 4
    assert "at" in entry


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_accumulates_across_multiple_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two sequential compactions on the same job — compaction_log grows,
    doesn't replace."""
    fake, factory = _fake_model_factory()
    monkeypatch.setattr(compaction_mod, "model", factory)

    jid = _make_job()
    msgs = [_msg("user", "task")] + [
        _msg("assistant" if i % 2 else "user", f"turn-{i}") for i in range(6)
    ]

    await compaction_mod.compact_messages(msgs, [], job_id=jid)
    await compaction_mod.compact_messages(msgs, [], job_id=jid)

    conn = connect()
    try:
        row = conn.execute(
            "SELECT compaction_log FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    log_entries = json.loads(row["compaction_log"])
    assert len(log_entries) == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_survives_audit_save_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If save_artifact raises (disk full, permissions, whatever), the
    compaction must still deliver its summary — dropping the audit trail
    is a degraded but non-fatal outcome. Regression guard."""
    fake, factory = _fake_model_factory(text="summary ok")
    monkeypatch.setattr(compaction_mod, "model", factory)

    def _blow_up(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(
        compaction_mod.artifacts_mod, "save_artifact", _blow_up,
    )

    msgs = [
        _msg("user", "task"),
        _msg("assistant", "a"), _msg("user", "b"),
        _msg("assistant", "c"), _msg("user", "d"),
    ]
    result = await compaction_mod.compact_messages(msgs, [], job_id=_make_job())

    assert len(result) == 2
    assert "summary ok" in result[1]["content"]
    # When audit save fails, the "archived at artifact" line should NOT
    # appear — we don't want to claim an audit that doesn't exist
    assert "archived at artifact" not in result[1]["content"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_includes_artifact_refs_in_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifact refs already accumulated by earlier tool calls get surfaced
    in the compacted message — so the agent can still read_artifact(id)
    them after compaction."""
    fake, factory = _fake_model_factory()
    monkeypatch.setattr(compaction_mod, "model", factory)

    msgs = [
        _msg("user", "task"),
        _msg("assistant", "a"), _msg("user", "b"),
        _msg("assistant", "c"), _msg("user", "d"),
    ]
    refs = ["art_existing_1", "art_existing_2"]
    result = await compaction_mod.compact_messages(msgs, refs, job_id=_make_job())

    content = result[1]["content"]
    assert "art_existing_1" in content
    assert "art_existing_2" in content
    assert "use read_artifact" in content


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_trims_artifact_refs_to_last_20(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job with 50 artifact_refs shouldn't blow the context with a huge
    ids list — only the last 20 surface in the compacted message."""
    fake, factory = _fake_model_factory()
    monkeypatch.setattr(compaction_mod, "model", factory)

    msgs = [_msg("user", "task")] + [
        _msg("assistant" if i % 2 else "user", f"t{i}") for i in range(6)
    ]
    refs = [f"art_{i}" for i in range(50)]
    result = await compaction_mod.compact_messages(msgs, refs, job_id=_make_job())

    content = result[1]["content"]
    # The trim is `all_refs[-20:]` applied AFTER appending the audit
    # artifact, so the user-visible window is art_31..art_49 (19 refs) +
    # 1 audit = 20 total. art_30 and earlier are outside the window.
    assert "art_49" in content
    assert "art_31" in content
    assert "art_30" not in content  # just outside the window
    assert "art_0" not in content


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_truncates_tail_before_sending_to_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The raw tail is capped at 40k chars before the Haiku call. Without
    this a job that accumulates multi-MB tool outputs could blow Haiku's
    context and crash the compaction entirely."""
    fake = _FakeModel()
    monkeypatch.setattr(compaction_mod, "model", lambda: fake)

    huge_chunk = "x" * 100_000
    msgs = [
        _msg("user", "task"),
        _msg("assistant", huge_chunk),
        _msg("user", huge_chunk),
        _msg("assistant", huge_chunk),
    ]
    await compaction_mod.compact_messages(msgs, [], job_id=_make_job())

    # Confirm the model was called with capped content
    call_kwargs = fake.generate.call_args.kwargs
    sent = call_kwargs["messages"][0]["content"]
    assert len(sent) == 40_000


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_db")
async def test_compact_handles_tool_use_blocks_in_assistant_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real assistant messages often have content as a list of blocks
    (text + tool_use). json.dumps needs `default=str` to survive any
    unusual objects in those blocks (e.g., enums). Regression guard."""
    fake, factory = _fake_model_factory()
    monkeypatch.setattr(compaction_mod, "model", factory)

    msgs = [
        _msg("user", "task"),
        {"role": "assistant", "content": [
            {"type": "text", "text": "Let me search."},
            {"type": "tool_use", "id": "tu_1", "name": "search_web",
             "input": {"query": "test"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_1",
             "content": json.dumps({"hits": [{"title": "x", "url": "y"}]})},
        ]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Done."},
        ]},
    ]

    # Should not raise; should produce a compacted list of length 2
    result = await compaction_mod.compact_messages(msgs, [], job_id=_make_job())
    assert len(result) == 2
    assert result[0] == msgs[0]  # initial preserved
