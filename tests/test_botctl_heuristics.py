"""botctl heuristics sub-app: list / approve / retire.

Fills the implicit gap — `approve_heuristic` existed as a memory helper
(used by the Discord reaction-approval flow), but there was no operator
CLI to approve proposed heuristics or retire bad ones. Users had to
hand-SQL-UPDATE the agent_heuristics table.

Structure:
    botctl heuristics list <scope>       (formerly `botctl heuristics <scope>`)
    botctl heuristics approve <id>
    botctl heuristics retire <id>

Breaking change for the list command — no users other than the solo
operator, checked against scripts/ and docs/. Clean break preferred over
backwards-compat alias (see CLAUDE rule on avoiding compat hacks).
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from donna.cli.botctl import app
from donna.memory import prompts as prompts_mod
from donna.memory.db import connect, transaction

runner = CliRunner()


def _insert(
    *, scope: str = "author_twain", heuristic: str = "Always cite chapter numbers.",
    status: str = "proposed",
) -> str:
    conn = connect()
    try:
        with transaction(conn):
            hid = prompts_mod.insert_heuristic(
                conn, agent_scope=scope, heuristic=heuristic, status=status,
            )
    finally:
        conn.close()
    return hid


def _status_of(heuristic_id: str) -> str:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT status FROM agent_heuristics WHERE id = ?", (heuristic_id,)
        ).fetchone()
    finally:
        conn.close()
    return row["status"] if row else "NOT FOUND"


# ---------- list --------------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_list_shows_scope_badges() -> None:
    _insert(heuristic="Active rule.", status="active")
    _insert(heuristic="Proposed rule.", status="proposed")
    _insert(heuristic="Retired rule.", status="retired")

    result = runner.invoke(app, ["heuristics", "list", "author_twain"])
    assert result.exit_code == 0, result.output
    # Scope header
    assert "author_twain" in result.output
    assert "1 active / 3 total" in result.output
    # Badges — active ✅, proposed 💭, retired 🗑️
    assert "✅" in result.output
    assert "💭" in result.output
    assert "🗑️" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_list_empty_scope() -> None:
    result = runner.invoke(app, ["heuristics", "list", "author_nobody"])
    assert result.exit_code == 0
    assert "0 active / 0 total" in result.output


# ---------- approve -----------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_approve_flips_proposed_to_active() -> None:
    hid = _insert(status="proposed")
    assert _status_of(hid) == "proposed"

    result = runner.invoke(app, ["heuristics", "approve", hid])
    assert result.exit_code == 0, result.output
    assert "approved" in result.output
    assert _status_of(hid) == "active"


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_approve_missing_id_exits_nonzero() -> None:
    result = runner.invoke(app, ["heuristics", "approve", "heu_nonexistent"])
    assert result.exit_code != 0
    assert "not found" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_approve_already_active_is_noop_but_clean() -> None:
    hid = _insert(status="active")
    result = runner.invoke(app, ["heuristics", "approve", hid])
    assert result.exit_code == 0
    assert "already active" in result.output
    assert _status_of(hid) == "active"


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_approve_can_reactivate_retired() -> None:
    """Retired → approve should reactivate with a warning. Avoids silently
    losing an operator's correction-of-a-correction."""
    hid = _insert(status="retired")
    result = runner.invoke(app, ["heuristics", "approve", hid])
    assert result.exit_code == 0
    assert "retired" in result.output.lower()
    assert "reactivate" in result.output.lower()
    assert _status_of(hid) == "active"


# ---------- retire ------------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_retire_flips_active_to_retired() -> None:
    hid = _insert(status="active")
    result = runner.invoke(app, ["heuristics", "retire", hid])
    assert result.exit_code == 0, result.output
    assert "retired" in result.output
    assert _status_of(hid) == "retired"


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_retire_flips_proposed_to_retired() -> None:
    """A heuristic can be retired without ever being approved — operator
    dismisses a bad LLM-proposed rule."""
    hid = _insert(status="proposed")
    result = runner.invoke(app, ["heuristics", "retire", hid])
    assert result.exit_code == 0
    assert _status_of(hid) == "retired"


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_retire_missing_id_exits_nonzero() -> None:
    result = runner.invoke(app, ["heuristics", "retire", "heu_nope"])
    assert result.exit_code != 0
    assert "not found" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_heuristics_retire_already_retired_is_noop() -> None:
    hid = _insert(status="retired")
    result = runner.invoke(app, ["heuristics", "retire", hid])
    assert result.exit_code == 0
    assert "already retired" in result.output
    assert _status_of(hid) == "retired"


# ---------- retire then re-list removes from active list ---------------


@pytest.mark.usefixtures("fresh_db")
def test_retired_heuristic_no_longer_returned_by_active_heuristics() -> None:
    """The prompt-composition path uses `active_heuristics` — retired
    heuristics must not surface there, or retirement is cosmetic."""
    hid = _insert(heuristic="A rule.", status="active")
    conn = connect()
    try:
        assert "A rule." in prompts_mod.active_heuristics(conn, "author_twain")
    finally:
        conn.close()

    result = runner.invoke(app, ["heuristics", "retire", hid])
    assert result.exit_code == 0

    conn = connect()
    try:
        remaining = prompts_mod.active_heuristics(conn, "author_twain")
    finally:
        conn.close()
    assert "A rule." not in remaining
