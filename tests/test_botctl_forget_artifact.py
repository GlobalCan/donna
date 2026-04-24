"""botctl forget-artifact tests.

Fills the user-facing gap flagged in docs/SESSION_RESUME.md §1 and
docs/KNOWN_ISSUES.md: "`botctl forget-artifact <id>` — currently manual
SQL DELETE + `rm` until then."

Covers:
- Happy path: deletes row and blob when no other references
- Missing artifact id exits non-zero
- Dedup safety: blob file is kept when another artifact row shares its sha256
- Knowledge-source soft reference produces a warning but doesn't block
- --force bypasses confirmation
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from donna.cli.botctl import app
from donna.config import settings
from donna.memory import artifacts as artifacts_mod
from donna.memory.db import connect, transaction

runner = CliRunner()


def _save_blob(content: str, name: str = "a.txt") -> dict:
    conn = connect()
    try:
        with transaction(conn):
            return artifacts_mod.save_artifact(
                conn, content=content, name=name, mime="text/plain",
            )
    finally:
        conn.close()


def _blob_path(sha: str) -> Path:
    return settings().artifacts_dir / f"{sha}.blob"


@pytest.mark.usefixtures("fresh_db")
def test_forget_artifact_happy_path_deletes_row_and_blob() -> None:
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    info = _save_blob("unique content for this test")
    art_id = info["artifact_id"]
    sha = info["sha256"]
    assert _blob_path(sha).exists()

    result = runner.invoke(app, ["forget-artifact", art_id, "--force"])
    assert result.exit_code == 0, result.output
    assert "forgot artifact" in result.output

    conn = connect()
    try:
        row = conn.execute("SELECT id FROM artifacts WHERE id = ?", (art_id,)).fetchone()
    finally:
        conn.close()
    assert row is None
    assert not _blob_path(sha).exists(), "blob should be removed when no other refs"


@pytest.mark.usefixtures("fresh_db")
def test_forget_artifact_missing_id_exits_nonzero() -> None:
    result = runner.invoke(app, ["forget-artifact", "art_nonexistent", "--force"])
    assert result.exit_code != 0
    assert "not found" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_forget_artifact_dedup_safety_is_enforced_by_schema() -> None:
    """`artifacts.sha256` has a UNIQUE constraint, so the "two rows share
    a blob" scenario can't occur. Pinning that invariant here: if it ever
    changes, the forget-artifact command's assumption (row is 1:1 with
    blob file) needs to be revisited."""
    info = _save_blob("shared content")
    sha = info["sha256"]

    conn = connect()
    try:
        with pytest.raises(Exception) as exc_info, transaction(conn):
            conn.execute(
                "INSERT INTO artifacts (id, sha256, name, mime, bytes, tainted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("art_second", sha, "b.txt", "text/plain", info["bytes"], 0),
            )
    finally:
        conn.close()
    assert "UNIQUE" in str(exc_info.value)


@pytest.mark.usefixtures("fresh_db")
def test_forget_artifact_warns_on_knowledge_source_reference() -> None:
    """knowledge_sources.source_ref is a free-form text field; if it points
    at the artifact_id we're deleting, warn the operator but don't block.
    Deletes still proceed with --force."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    info = _save_blob("corpus source material")
    art_id = info["artifact_id"]

    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO knowledge_sources "
                "(id, agent_scope, source_type, title, source_ref, copyright_status, added_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("src_corpus", "author_twain", "article", "A Twain Essay",
                 art_id, "public_domain", "test"),
            )
    finally:
        conn.close()

    result = runner.invoke(app, ["forget-artifact", art_id, "--force"])
    assert result.exit_code == 0, result.output
    assert "referenced by 1 knowledge_sources" in result.output
    assert "A Twain Essay" in result.output
    # Deletion still happened
    conn = connect()
    try:
        row = conn.execute("SELECT id FROM artifacts WHERE id = ?", (art_id,)).fetchone()
    finally:
        conn.close()
    assert row is None


@pytest.mark.usefixtures("fresh_db")
def test_forget_artifact_without_force_prompts_and_aborts_on_no() -> None:
    """Without --force, confirm defaults to No — typer.confirm returns False
    on empty input. Row stays intact."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    info = _save_blob("definitely here")
    art_id = info["artifact_id"]

    result = runner.invoke(app, ["forget-artifact", art_id], input="\n")
    assert result.exit_code == 0
    assert "aborted" in result.output

    conn = connect()
    try:
        row = conn.execute("SELECT id FROM artifacts WHERE id = ?", (art_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None, "artifact must NOT be deleted when user says no"


@pytest.mark.usefixtures("fresh_db")
def test_forget_artifact_without_force_prompts_and_deletes_on_yes() -> None:
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    info = _save_blob("going away")
    art_id = info["artifact_id"]

    result = runner.invoke(app, ["forget-artifact", art_id], input="y\n")
    assert result.exit_code == 0, result.output
    assert "forgot artifact" in result.output

    conn = connect()
    try:
        row = conn.execute("SELECT id FROM artifacts WHERE id = ?", (art_id,)).fetchone()
    finally:
        conn.close()
    assert row is None


@pytest.mark.usefixtures("fresh_db")
def test_forget_artifact_tolerates_missing_blob_file() -> None:
    """Edge: row exists but blob file was already rm'd manually. Row deletion
    should still succeed — we just skip the file rm."""
    import os as _os

    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    info = _save_blob("about to lose its blob")
    art_id = info["artifact_id"]
    bp = _blob_path(info["sha256"])
    _os.remove(bp)
    assert not bp.exists()

    result = runner.invoke(app, ["forget-artifact", art_id, "--force"])
    assert result.exit_code == 0, result.output
    assert "forgot artifact" in result.output

    conn = connect()
    try:
        row = conn.execute("SELECT id FROM artifacts WHERE id = ?", (art_id,)).fetchone()
    finally:
        conn.close()
    assert row is None
