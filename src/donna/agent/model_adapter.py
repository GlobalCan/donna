"""Anthropic client wrapper with tier routing + rate limiting + cost recording.

Vendor-agnostic by interface: future `OpenAIAdapter` plugs in without touching
callers. v1 is Anthropic-only.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import anthropic
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import settings
from ..logging import get_logger
from ..memory import cost as cost_mod
from ..memory.db import connect
from ..observability import otel
from ..types import ModelTier
from .rate_limiter import ledger

log = get_logger(__name__)


@dataclass
class GenerateResult:
    text: str
    stop_reason: str
    tool_uses: list[dict[str, Any]]
    raw_content: list[dict[str, Any]]
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float


class AnthropicAdapter:
    """Anthropic client wrapper. Reads model_id + pricing from the
    `model_runtimes` table (Pattern A Hermes steal #1) so adding OpenAI
    later is a data change, not a code change.

    Env-var fallback preserved for local dev / initial deploy if the table
    hasn't been seeded yet.
    """

    def __init__(self) -> None:
        s = settings()
        self.client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key)
        # Env-var fallback: used only if the runtimes table is empty (e.g., on
        # the very first boot before migrations have been applied).
        self._fallback_model_for: dict[ModelTier, str] = {
            ModelTier.FAST: s.anthropic_model_fast,
            ModelTier.STRONG: s.anthropic_model_strong,
            ModelTier.HEAVY: s.anthropic_model_heavy,
        }

    def resolve_model(self, tier: ModelTier) -> str:
        """Resolve a tier to a concrete model_id via the runtimes registry."""
        from ..memory import runtimes as rt_mod
        try:
            rt = rt_mod.get_by_tier(tier.value, provider="anthropic")
            if rt is not None:
                return rt.model_id
        except Exception:
            # DB not ready (migrations not yet run, etc.)
            pass
        return self._fallback_model_for[tier]

    async def generate(
        self,
        *,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tier: ModelTier = ModelTier.STRONG,
        max_tokens: int = 4096,
        job_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> GenerateResult:
        model = self.resolve_model(tier)

        # Estimate tokens conservatively for the ledger
        est_input = _estimate_tokens(system) + sum(_estimate_tokens(m) for m in messages)
        await ledger().reserve(tier.value, est_input, max_tokens)

        with otel.span(
            "gen_ai.request",
            **{
                "gen_ai.system": "anthropic",
                "gen_ai.request.model": model,
                "gen_ai.request.max_tokens": max_tokens,
                "agent.model.tier": tier.value,
                "agent.job.id": job_id,
            },
        ):
            response = await self._call_with_retry(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                tier=tier,
                extra_headers=extra_headers,
            )

        usage = response.usage
        input_tok = getattr(usage, "input_tokens", 0) or 0
        output_tok = getattr(usage, "output_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

        # Record cost
        conn = connect()
        try:
            cost = cost_mod.record_llm_usage(
                conn, job_id=job_id, model=model,
                input_tokens=input_tok, output_tokens=output_tok,
                cache_read_tokens=cache_read, cache_write_tokens=cache_write,
            )
        finally:
            conn.close()

        otel.set_attr("gen_ai.usage.input_tokens", input_tok)
        otel.set_attr("gen_ai.usage.output_tokens", output_tok)
        otel.set_attr("gen_ai.usage.cache_read_tokens", cache_read)
        otel.set_attr("gen_ai.usage.cache_write_tokens", cache_write)
        otel.set_attr("gen_ai.usage.cost_usd", cost)

        # Split content into text + tool_uses
        text_parts: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        raw_content: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
                raw_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_uses.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                raw_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        return GenerateResult(
            text="\n".join(text_parts),
            stop_reason=response.stop_reason or "",
            tool_uses=tool_uses,
            raw_content=raw_content,
            model=model,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=cost,
        )

    async def _call_with_retry(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        tier: ModelTier,
        extra_headers: dict[str, str] | None,
    ) -> Any:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type((
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.InternalServerError,
                anthropic.RateLimitError,
            )),
            reraise=True,
        ):
            with attempt:
                try:
                    kwargs: dict[str, Any] = {
                        "model": model,
                        "system": system,
                        "messages": messages,
                        "max_tokens": max_tokens,
                    }
                    if tools:
                        kwargs["tools"] = tools
                    if extra_headers:
                        kwargs["extra_headers"] = extra_headers
                    return await self.client.messages.create(**kwargs)
                except anthropic.RateLimitError as e:
                    retry_after = float(getattr(e, "retry_after", None) or 5.0)
                    await ledger().on_429(tier.value, retry_after)
                    raise
        raise RuntimeError("unreachable")


def _estimate_tokens(x: Any) -> int:
    """Rough ~4 chars/token heuristic for budgeting."""
    if isinstance(x, str):
        return len(x) // 4
    if isinstance(x, list):
        return sum(_estimate_tokens(i) for i in x)
    if isinstance(x, dict):
        return sum(_estimate_tokens(v) for v in x.values())
    return 0


_adapter: AnthropicAdapter | None = None


def model() -> AnthropicAdapter:
    global _adapter
    if _adapter is None:
        _adapter = AnthropicAdapter()
    return _adapter
