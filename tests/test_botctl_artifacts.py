"""botctl artifacts + artifact-show commands.

Fills a natural gap — `forget-artifact` existed in botctl but there was
no way to *see* artifacts from the CLI. Operators had to hand-SQL or
drop into a Python REPL against the live DB.

Now:
    botctl artifacts [--tag X] [--limit N] [--tainted]
    botctl artifact-show <id> [--offset N] [--length N]
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from donna.cli.botctl import app
from donna.config import settings
from donna.memory import artifacts as artifacts_mod
from donna.memory.db import connect, transaction

runner = CliRunner()


def _save(content: str = "hello", *, name: str = "a.txt", tags: str = "",
          tainted: bool = False) -> dict:
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        with transaction(conn):
            return artifacts_mod.save_artifact(
                conn, content=content, name=name, mime="text/plain",
                tags=tags, tainted=tainted,
            )
    finally:
        conn.close()


# ---------- artifacts list ---------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_artifacts_list_shows_rows_with_metadata() -> None:
    _save("a", name="first", tags="docs")
    _save("b", name="second", tags="reports,notes")

    result = runner.invoke(app, ["artifacts"])
    assert result.exit_code == 0, result.output
    assert "first" in result.output
    assert "second" in result.output
    assert "2 shown" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_artifacts_list_empty() -> None:
    result = runner.invoke(app, ["artifacts"])
    assert result.exit_code == 0
    assert "0 shown" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_artifacts_list_filters_by_tag() -> None:
    _save("a", name="for_docs", tags="docs")
    _save("b", name="for_reports", tags="reports")

    result = runner.invoke(app, ["artifacts", "--tag", "docs"])
    assert result.exit_code == 0
    assert "for_docs" in result.output
    assert "for_reports" not in result.output


@pytest.mark.usefixtures("fresh_db")
def test_artifacts_list_tainted_only_filter() -> None:
    _save("clean", name="safe", tainted=False)
    _save("dirty", name="fetched", tainted=True)

    result = runner.invoke(app, ["artifacts", "--tainted"])
    assert result.exit_code == 0
    assert "fetched" in result.output
    assert "safe" not in result.output
    assert "⚠️" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_artifacts_list_respects_limit() -> None:
    for i in range(15):
        _save(f"blob {i}", name=f"n{i:02d}")

    result = runner.invoke(app, ["artifacts", "--limit", "5"])
    assert result.exit_code == 0
    assert "5 shown" in result.output


# ---------- artifact-show ----------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_artifact_show_prints_text_content() -> None:
    info = _save("the whole content here", name="thing")
    result = runner.invoke(app, ["artifact-show", info["artifact_id"]])
    assert result.exit_code == 0, result.output
    assert "the whole content here" in result.output
    assert "thing" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_artifact_show_missing_id_exits_nonzero() -> None:
    result = runner.invoke(app, ["artifact-show", "art_nope"])
    assert result.exit_code != 0
    assert "not found" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_artifact_show_offset_length_slice() -> None:
    info = _save("A" * 100 + "B" * 100 + "C" * 100, name="long")
    # Read the middle slice
    result = runner.invoke(
        app, ["artifact-show", info["artifact_id"], "--offset", "100", "--length", "50"],
    )
    assert result.exit_code == 0
    # That slice is all Bs — 50 of them
    assert "B" * 50 in result.output
    # Trailing hint about more content
    assert "more chars" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_artifact_show_binary_not_printed() -> None:
    """Binary artifacts shouldn't dump bytes to stdout. Operator should
    see metadata and a 'binary' marker."""
    conn = connect()
    try:
        with transaction(conn):
            info = artifacts_mod.save_artifact(
                conn, content=b"\x89PNG\r\n\x1a\n\x00\x01\x02binary\xff",
                name="pic.png", mime="image/png",
            )
    finally:
        conn.close()

    result = runner.invoke(app, ["artifact-show", info["artifact_id"]])
    assert result.exit_code == 0
    assert "binary" in result.output.lower()
    assert "image/png" in result.output
