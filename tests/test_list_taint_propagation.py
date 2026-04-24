"""Adversarial: list_* tools must surface top-level tainted flag.

Codex round-2 #4 caught this for `tools.memory.recall` and
`tools.knowledge.recall_knowledge`: tools that return lists with per-row
tainted flags were invisible to `JobContext._execute_one`'s taint-
propagation check because it only looks at the top-level `tainted` key.

Same-class audit this session found the same gap in:
- `tools.artifacts.list_artifacts`
- `tools.knowledge.list_knowledge`

These tests pin the fix. A list containing any tainted row must surface
`tainted: True` at the top level; a clean list must not.

Attack shape without the fix: model calls fetch_url on an attacker's page
→ save_artifact persists the page (tainted=True) → model calls list_artifacts
to 'see what's there' → attacker-controlled name/tags flow into model
context → model does a `remember` / `run_python` in the same job → no
escalated confirmation because taint never propagated to JobContext.state.
"""
from __future__ import annotations

import pytest

from donna.memory.db import connect, transaction
from donna.tools.artifacts import list_artifacts
from donna.tools.knowledge import list_knowledge


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_list_artifacts_surfaces_top_level_tainted_when_any_row_tainted() -> None:
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO artifacts (id, sha256, name, mime, bytes, tainted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("art_clean", "a" * 64, "a clean one", "text/plain", 10, 0),
            )
            conn.execute(
                "INSERT INTO artifacts (id, sha256, name, mime, bytes, tainted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("art_dirty", "b" * 64, "from fetch_url", "text/plain", 10, 1),
            )
    finally:
        conn.close()

    result = await list_artifacts()
    assert result["count"] == 2
    assert result.get("tainted") is True, (
        "list_artifacts must set top-level tainted=True when any row is tainted "
        "so JobContext._execute_one propagates taint onto the job"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_list_artifacts_omits_top_level_tainted_when_all_rows_clean() -> None:
    """Clean list must not set tainted=True — we'd trip confirmation
    escalations on jobs that never actually saw untrusted content."""
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO artifacts (id, sha256, name, mime, bytes, tainted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("art_clean_only", "c" * 64, "clean", "text/plain", 10, 0),
            )
    finally:
        conn.close()

    result = await list_artifacts()
    assert result["count"] == 1
    # Either the key is absent or explicitly falsey — both acceptable
    assert not result.get("tainted"), "no tainted row → no top-level taint"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_list_artifacts_empty_is_clean() -> None:
    result = await list_artifacts()
    assert result["count"] == 0
    assert not result.get("tainted")


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_list_knowledge_surfaces_top_level_tainted_when_any_source_tainted() -> None:
    """knowledge_sources.tainted is set by ingest_text when the caller passes
    tainted=True (e.g., ingest_discord_attachment). A list that includes any
    tainted source must flag the aggregate as tainted."""
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO knowledge_sources "
                "(id, agent_scope, source_type, title, copyright_status, added_by, tainted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("src_clean", "author_twain", "book", "Huck Finn",
                 "public_domain", "test", 0),
            )
            conn.execute(
                "INSERT INTO knowledge_sources "
                "(id, agent_scope, source_type, title, copyright_status, added_by, tainted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("src_dirty", "author_twain", "article", "From an attachment",
                 "personal_use", "tool:ingest_discord_attachment", 1),
            )
    finally:
        conn.close()

    result = await list_knowledge(scope="author_twain")
    assert result["count"] == 2
    assert result.get("tainted") is True


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_list_knowledge_omits_top_level_tainted_when_all_clean() -> None:
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO knowledge_sources "
                "(id, agent_scope, source_type, title, copyright_status, added_by, tainted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("src_clean_only", "author_twain", "book", "Roughing It",
                 "public_domain", "test", 0),
            )
    finally:
        conn.close()

    result = await list_knowledge(scope="author_twain")
    assert result["count"] == 1
    assert not result.get("tainted")


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_list_knowledge_empty_scope_is_clean() -> None:
    result = await list_knowledge(scope="author_nonexistent")
    assert result["count"] == 0
    assert not result.get("tainted")
