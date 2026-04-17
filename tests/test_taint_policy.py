"""Taint policy — tainted jobs escalate remember/run_python to always-confirm."""
from __future__ import annotations

from donna.security.taint import TAINT_ESCALATED_TOOLS, effective_confirmation
from donna.types import ConfirmationMode, ToolEntry


def _entry(name: str, conf: ConfirmationMode) -> ToolEntry:
    return ToolEntry(
        name=name, fn=None, schema={}, description="",  # type: ignore[arg-type]
        scope="x", cost="low", confirmation=conf,
        taints_job=False, idempotent=True, agents=("*",),
    )


def test_clean_job_keeps_original_mode() -> None:
    e = _entry("remember", ConfirmationMode.ONCE_PER_JOB)
    assert effective_confirmation(e, job_tainted=False) == ConfirmationMode.ONCE_PER_JOB


def test_tainted_escalates_remember() -> None:
    assert "remember" in TAINT_ESCALATED_TOOLS
    e = _entry("remember", ConfirmationMode.ONCE_PER_JOB)
    assert effective_confirmation(e, job_tainted=True) == ConfirmationMode.ALWAYS


def test_tainted_does_not_escalate_read_tool() -> None:
    e = _entry("recall", ConfirmationMode.NEVER)
    assert effective_confirmation(e, job_tainted=True) == ConfirmationMode.NEVER
