"""Rate limiter basic behavior."""
from __future__ import annotations

import asyncio

import pytest

from donna.agent.rate_limiter import RateLimitLedger


async def test_reserve_under_cap() -> None:
    l = RateLimitLedger()
    l.limits["fast"].rpm = 10
    # shouldn't block
    await asyncio.wait_for(l.reserve("fast", 100, 100), timeout=2.0)


async def test_429_pops_last_entry() -> None:
    l = RateLimitLedger()
    await l.reserve("strong", 50, 50)
    assert len(l.windows["strong"]) == 1
    # simulate server 429 — shorten retry_after for test speed
    await l.on_429("strong", retry_after=0.01)
    assert len(l.windows["strong"]) == 0
