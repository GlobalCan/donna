"""Process-wide rate-limit ledger for Anthropic models.

Tracks a sliding 60s window of (timestamp, input_tokens, output_tokens) per model
class. Shared across concurrent jobs — three workers on a single event loop
can't collectively blow through the RPM / ITPM / OTPM limits.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass

from ..config import settings
from ..logging import get_logger

log = get_logger(__name__)


class OversizedRequestError(Exception):
    """Raised when a single request estimate exceeds the per-minute cap."""


@dataclass
class Limits:
    rpm: int
    itpm: int
    otpm: int


class RateLimitLedger:
    def __init__(self) -> None:
        s = settings()
        self.limits: dict[str, Limits] = {
            "fast":   Limits(s.rate_haiku_rpm,  s.rate_haiku_itpm,  s.rate_haiku_otpm),
            "strong": Limits(s.rate_sonnet_rpm, s.rate_sonnet_itpm, s.rate_sonnet_otpm),
            "heavy":  Limits(s.rate_opus_rpm,   s.rate_opus_itpm,   s.rate_opus_otpm),
        }
        self.windows: dict[str, deque[tuple[float, int, int]]] = {
            "fast": deque(), "strong": deque(), "heavy": deque(),
        }
        self.lock = asyncio.Lock()

    async def reserve(self, tier: str, est_input: int, est_output: int) -> None:
        """Block until projected usage fits under the caps, then record the reservation.

        Raises OversizedRequestError if a single request is larger than the
        per-minute cap — no amount of waiting will make it fit. (Codex audit:
        prior behavior was infinite 5s sleeps on this path.)
        """
        lim = self.limits[tier]
        if est_input > lim.itpm:
            raise OversizedRequestError(
                f"request estimated input tokens ({est_input}) exceeds "
                f"tier '{tier}' ITPM cap ({lim.itpm}) — no wait can recover"
            )
        if est_output > lim.otpm:
            raise OversizedRequestError(
                f"request estimated output tokens ({est_output}) exceeds "
                f"tier '{tier}' OTPM cap ({lim.otpm}) — no wait can recover"
            )

        while True:
            async with self.lock:
                now = time.time()
                self._trim(tier, now)
                wnd = self.windows[tier]

                rpm = len(wnd) + 1
                itpm = sum(i for _, i, _ in wnd) + est_input
                otpm = sum(o for _, _, o in wnd) + est_output

                if rpm <= lim.rpm and itpm <= lim.itpm and otpm <= lim.otpm:
                    wnd.append((now, est_input, est_output))
                    return
                if wnd:
                    oldest = wnd[0][0]
                    sleep_for = max(1.0, 60.0 - (now - oldest) + 0.5)
                else:
                    sleep_for = 5.0
                log.info("ratelimit.wait", tier=tier, sleep_for=sleep_for, rpm=rpm, itpm=itpm, otpm=otpm)
            await asyncio.sleep(sleep_for)

    async def on_429(self, tier: str, retry_after: float) -> None:
        async with self.lock:
            if self.windows[tier]:
                self.windows[tier].pop()
        log.warning("ratelimit.429", tier=tier, retry_after=retry_after)
        await asyncio.sleep(retry_after)

    def _trim(self, tier: str, now: float) -> None:
        wnd = self.windows[tier]
        while wnd and now - wnd[0][0] > 60.0:
            wnd.popleft()


_ledger: RateLimitLedger | None = None


def ledger() -> RateLimitLedger:
    global _ledger
    if _ledger is None:
        _ledger = RateLimitLedger()
    return _ledger
