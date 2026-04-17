"""Communicate tools — ask_user, send_update. Plumbed through an outbox queue
that the Discord adapter drains."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .registry import tool


@dataclass
class OutgoingAsk:
    job_id: str
    question: str
    future: asyncio.Future[str]


@dataclass
class OutgoingUpdate:
    job_id: str
    text: str
    tainted: bool


# Outbox queues filled by tools, drained by Discord adapter.
_ask_queue: asyncio.Queue[OutgoingAsk] | None = None
_update_queue: asyncio.Queue[OutgoingUpdate] | None = None


def init_queues() -> None:
    global _ask_queue, _update_queue
    if _ask_queue is None:
        _ask_queue = asyncio.Queue()
    if _update_queue is None:
        _update_queue = asyncio.Queue()


def ask_queue() -> asyncio.Queue[OutgoingAsk]:
    init_queues()
    assert _ask_queue is not None
    return _ask_queue


def update_queue() -> asyncio.Queue[OutgoingUpdate]:
    init_queues()
    assert _update_queue is not None
    return _update_queue


@tool(
    scope="communicate", cost="low",
    description=(
        "Pause and ask the user a clarifying question in Discord. Blocks the "
        "job until they reply. Use when genuinely ambiguous — do NOT use to "
        "rubber-stamp trivial assumptions."
    ),
)
async def ask_user(question: str, job_id: str | None = None) -> dict[str, Any]:
    if job_id is None:
        return {"error": "ask_user requires job_id context"}
    fut: asyncio.Future[str] = asyncio.get_event_loop().create_future()
    await ask_queue().put(OutgoingAsk(job_id=job_id, question=question, future=fut))
    try:
        reply = await asyncio.wait_for(fut, timeout=1800)  # 30 min
    except asyncio.TimeoutError:
        return {"timeout": True, "reply": None}
    return {"reply": reply, "timeout": False}


@tool(
    scope="communicate", cost="low",
    description=(
        "Send a short progress update to the user's Discord thread. "
        "Rate-limited to 1/5s per job. Use for visible 'I'm working on X' pings "
        "during long jobs."
    ),
)
async def send_update(
    text: str,
    job_id: str | None = None,
    tainted: bool = False,
) -> dict[str, Any]:
    if job_id is None:
        return {"error": "send_update requires job_id context"}
    await update_queue().put(OutgoingUpdate(job_id=job_id, text=text[:1500], tainted=tainted))
    return {"queued": True}
