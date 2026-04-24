"""Taint propagation policy.

Rule 1: any tool with `taints_job=True` in the registry, once called, sets
        job.tainted = True for the rest of the job's life.
Rule 2: `read_artifact` propagates the artifact's own taint onto the job.
Rule 2.1: tools that return a top-level ``tainted: True`` (e.g. `recall`
        when any matching fact is tainted) also propagate onto the job.
Rule 3: once tainted, certain write/exec tools escalate confirmation to 'always'.
"""
from __future__ import annotations

from ..types import ConfirmationMode, ToolEntry

# Tools whose confirmation level escalates to 'always' in a tainted job.
# Codex adversarial scan #6: `teach` and `propose_heuristic` were not in
# this set, so a model could read a tainted URL or fact and then silently
# write to the corpus / propose a reasoning rule with no extra gate. Both
# are durable knowledge-layer writes and belong in the escalated set.
TAINT_ESCALATED_TOOLS = frozenset({
    "remember",
    "run_python",
    "teach",              # corpus write — tainted source could poison knowledge
    "propose_heuristic",  # reasoning-rule proposal — tainted source could poison reasoning
    "run_bash",           # future L3
    "execute_sql",        # future L3
    "send_email",         # future L3
})


def effective_confirmation(entry: ToolEntry, *, job_tainted: bool) -> ConfirmationMode:
    """Return the confirmation mode actually required for this call."""
    if job_tainted and entry.name in TAINT_ESCALATED_TOOLS:
        return ConfirmationMode.ALWAYS
    return entry.confirmation
