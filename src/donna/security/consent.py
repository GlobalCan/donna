"""Consent system — 3 modes (never / once_per_job / always / high_impact_always),
Discord reaction approval flow."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ..logging import get_logger
from ..memory import permissions as perm_mod
from ..memory.db import connect
from ..types import ConfirmationMode, ToolEntry
from .taint import effective_confirmation

log = get_logger(__name__)


@dataclass
class ConsentRequest:
    job_id: str
    tool_entry: ToolEntry
    arguments: dict[str, Any]
    tainted: bool
    future: asyncio.Future[bool]


@dataclass
class ConsentResult:
    approved: bool
    reason: str = ""


# Outbox queue drained by Discord adapter
_consent_queue: asyncio.Queue[ConsentRequest] | None = None


def init_queue() -> None:
    global _consent_queue
    if _consent_queue is None:
        _consent_queue = asyncio.Queue()


def consent_queue() -> asyncio.Queue[ConsentRequest]:
    init_queue()
    assert _consent_queue is not None
    return _consent_queue


async def check(
    *,
    job_id: str,
    entry: ToolEntry,
    arguments: dict[str, Any],
    tainted: bool,
) -> ConsentResult:
    """Evaluate whether a tool call proceeds, blocks for approval, or is auto-approved."""
    mode = effective_confirmation(entry, job_tainted=tainted)

    if mode == ConfirmationMode.NEVER:
        return ConsentResult(approved=True)

    if mode == ConfirmationMode.ONCE_PER_JOB:
        conn = connect()
        try:
            if perm_mod.has_grant(conn, job_id=job_id, tool_name=entry.name):
                return ConsentResult(approved=True, reason="existing grant")
        finally:
            conn.close()
        # Fall through to prompt
    # ALWAYS or HIGH_IMPACT_ALWAYS: always prompt; don't honor existing grants for HIGH_IMPACT

    fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
    await consent_queue().put(
        ConsentRequest(
            job_id=job_id, tool_entry=entry, arguments=arguments,
            tainted=tainted, future=fut,
        )
    )
    try:
        approved = await asyncio.wait_for(fut, timeout=1800)  # 30 min
    except asyncio.TimeoutError:
        return ConsentResult(approved=False, reason="timeout")

    if approved and mode == ConfirmationMode.ONCE_PER_JOB:
        conn = connect()
        try:
            perm_mod.insert_grant(conn, job_id=job_id, tool_name=entry.name, scope="job")
        finally:
            conn.close()

    return ConsentResult(
        approved=approved,
        reason="user approved" if approved else "user declined",
    )
