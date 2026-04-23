"""Rate limiter basic behavior."""
from __future__ import annotations

import asyncio

from donna.agent.rate_limiter import RateLimitLedger


async def test_reserve_under_cap() -> None:
    ledger = RateLimitLedger()
    ledger.limits["fast"].rpm = 10
    # shouldn't block
    await asyncio.wait_for(ledger.reserve("fast", 100, 100), timeout=2.0)


async def test_429_pops_last_entry() -> None:
    ledger = RateLimitLedger()
    await ledger.reserve("strong", 50, 50)
    assert len(ledger.windows["strong"]) == 1
    # simulate server 429 — shorten retry_after for test speed
    await ledger.on_429("strong", retry_after=0.01)
    assert len(ledger.windows["strong"]) == 0
