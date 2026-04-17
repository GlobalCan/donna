"""Taint propagation policy.

Rule 1: any tool with `taints_job=True` in the registry, once called, sets
        job.tainted = True for the rest of the job's life.
Rule 2: `read_artifact` propagates the artifact's own taint onto the job.
Rule 3: once tainted, certain write/exec tools escalate confirmation to 'always'.
"""
from __future__ import annotations

from ..types import ConfirmationMode, ToolEntry

# Tools whose confirmation level escalates to 'always' in a tainted job
TAINT_ESCALATED_TOOLS = frozenset({
    "remember",
    "run_python",
    "run_bash",      # future L3
    "execute_sql",   # future L3
    "send_email",    # future L3
})


def effective_confirmation(entry: ToolEntry, *, job_tainted: bool) -> ConfirmationMode:
    """Return the confirmation mode actually required for this call."""
    if job_tainted and entry.name in TAINT_ESCALATED_TOOLS:
        return ConfirmationMode.ALWAYS
    return entry.confirmation
