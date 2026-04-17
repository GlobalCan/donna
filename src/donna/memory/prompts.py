"""Agent prompts — versioned system prompts per scope."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import ids


DEFAULT_ORCHESTRATOR_PATH = Path(__file__).resolve().parent.parent / "agent" / "prompts" / "orchestrator.md"


def active_prompt(conn: sqlite3.Connection, agent_scope: str) -> dict | None:
    row = conn.execute(
        """
        SELECT id, agent_scope, version, system_prompt, speculation_allowed
        FROM agent_prompts
        WHERE agent_scope = ? AND active = 1
        ORDER BY version DESC LIMIT 1
        """,
        (agent_scope,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    # If this is the placeholder-seeded prompt, load from file
    if "placeholder" in result["system_prompt"] and agent_scope == "orchestrator":
        if DEFAULT_ORCHESTRATOR_PATH.exists():
            result["system_prompt"] = DEFAULT_ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    return result


def create_prompt_version(
    conn: sqlite3.Connection,
    *,
    agent_scope: str,
    system_prompt: str,
    speculation_allowed: bool = False,
) -> str:
    # Find next version
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM agent_prompts WHERE agent_scope = ?",
        (agent_scope,),
    ).fetchone()
    next_v = int(row["v"]) + 1
    pid = ids.prompt_id()
    conn.execute(
        """
        INSERT INTO agent_prompts (id, agent_scope, version, system_prompt, speculation_allowed)
        VALUES (?, ?, ?, ?, ?)
        """,
        (pid, agent_scope, next_v, system_prompt, 1 if speculation_allowed else 0),
    )
    return pid


def activate_prompt(conn: sqlite3.Connection, *, prompt_id: str) -> None:
    row = conn.execute("SELECT agent_scope FROM agent_prompts WHERE id = ?", (prompt_id,)).fetchone()
    if not row:
        raise ValueError(f"prompt {prompt_id} not found")
    scope = row["agent_scope"]
    conn.execute(
        "UPDATE agent_prompts SET active = 0 WHERE agent_scope = ?", (scope,)
    )
    conn.execute(
        "UPDATE agent_prompts SET active = 1, eval_passed_at = ? WHERE id = ?",
        (datetime.now(timezone.utc), prompt_id),
    )


def active_heuristics(conn: sqlite3.Connection, agent_scope: str) -> list[str]:
    rows = conn.execute(
        "SELECT heuristic FROM agent_heuristics WHERE agent_scope = ? AND status = 'active' ORDER BY created_at",
        (agent_scope,),
    ).fetchall()
    return [r["heuristic"] for r in rows]


def insert_heuristic(
    conn: sqlite3.Connection,
    *,
    agent_scope: str,
    heuristic: str,
    provenance: str = "user",
    status: str = "proposed",
    reasoning: str | None = None,
) -> str:
    """Codex review #14 — `reasoning` is now persisted into the provenance
    field (which was already a free-text column). Previously it was accepted
    by the tool wrapper and silently dropped."""
    hid = ids.heuristic_id()
    combined_prov = provenance
    if reasoning:
        combined_prov = f"{provenance} | reasoning: {reasoning}"
    conn.execute(
        """
        INSERT INTO agent_heuristics (id, agent_scope, heuristic, status, provenance)
        VALUES (?, ?, ?, ?, ?)
        """,
        (hid, agent_scope, heuristic, status, combined_prov),
    )
    if status == "active":
        conn.execute(
            "UPDATE agent_heuristics SET approved_at = ? WHERE id = ?",
            (datetime.now(timezone.utc), hid),
        )
    return hid


def approve_heuristic(conn: sqlite3.Connection, *, heuristic_id: str) -> None:
    conn.execute(
        """
        UPDATE agent_heuristics
        SET status = 'active', approved_at = ?
        WHERE id = ?
        """,
        (datetime.now(timezone.utc), heuristic_id),
    )
