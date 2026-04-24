"""sanitize_untrusted structural edge cases.

Not a live-Haiku test — live bypass testing needs Anthropic calls + manually
crafted injection payloads, which is a separate (expensive, manual) exercise.
This covers the cheap-structural class that runs in CI:

- Empty / whitespace-only input short-circuits WITHOUT calling the model
  (Anthropic rejects empty user messages with 400; also no-op waste)
- Truncation at 60k happens before the model call
- Empty model response returns a placeholder (not empty string — which
  could silently erase the tool result entirely)
- Model exceptions propagate to the caller (callers like _sanitize_hits
  wrap with return_exceptions=True; fetch_url lets it propagate to the
  tool_step error path)
- Prompt loads from file if present, falls back to a known string if not
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from donna.security import sanitize as sanitize_mod


@dataclass
class _FakeResult:
    text: str
    cost_usd: float = 0.0


class _FakeModel:
    def __init__(self, text: str = "sanitized output") -> None:
        self.generate = AsyncMock(return_value=_FakeResult(text))


@pytest.mark.asyncio
async def test_empty_input_short_circuits_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ch.send("")` is the Discord equivalent of nothing happening. Also:
    Anthropic's API rejects empty user messages with a 400, so calling
    Haiku on `""` would blow up the tool, not return anything useful."""
    fake = _FakeModel()
    monkeypatch.setattr(sanitize_mod, "model", lambda: fake)

    result = await sanitize_mod.sanitize_untrusted("", artifact_id="a1")
    assert result == "[no substantive content]"
    fake.generate.assert_not_called()


@pytest.mark.asyncio
async def test_whitespace_only_input_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeModel()
    monkeypatch.setattr(sanitize_mod, "model", lambda: fake)

    result = await sanitize_mod.sanitize_untrusted("   \n\n\t  ", artifact_id="a1")
    assert result == "[no substantive content]"
    fake.generate.assert_not_called()


@pytest.mark.asyncio
async def test_nonempty_input_calls_model_with_truncated_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeModel(text="model returned this summary")
    monkeypatch.setattr(sanitize_mod, "model", lambda: fake)

    long_content = "x" * 80_000  # > 60k
    result = await sanitize_mod.sanitize_untrusted(long_content, artifact_id="a1")
    assert result == "model returned this summary"
    fake.generate.assert_called_once()
    # Confirm the message body was truncated at 60k, not sent whole
    call_kwargs = fake.generate.call_args.kwargs
    user_msg = call_kwargs["messages"][0]["content"]
    assert len(user_msg) == 60_000


@pytest.mark.asyncio
async def test_empty_model_response_returns_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the model returns an empty string, we MUST return the placeholder.
    A literal "" would make the tool's return value look like nothing
    happened, and the caller's next step (inline into agent context) would
    silently drop the data."""
    fake = _FakeModel(text="")
    monkeypatch.setattr(sanitize_mod, "model", lambda: fake)

    result = await sanitize_mod.sanitize_untrusted("real content here", artifact_id="a1")
    assert result == "[no substantive content]"


@pytest.mark.asyncio
async def test_whitespace_only_model_response_returns_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeModel(text="   \n   ")
    monkeypatch.setattr(sanitize_mod, "model", lambda: fake)

    result = await sanitize_mod.sanitize_untrusted("real content here", artifact_id="a1")
    assert result == "[no substantive content]"


@pytest.mark.asyncio
async def test_model_exception_propagates_to_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upstream callers handle this: `tools.web._sanitize_hits` uses
    `asyncio.gather(return_exceptions=True)` and falls back to a
    `[sanitize_error: ...]` string. `tools.web.fetch_url` lets it propagate
    which surfaces as a tool error block. Either way, we MUST NOT swallow
    the exception here — a silent "[no substantive content]" on a Haiku
    API outage would hide a real systemic problem."""
    fake = MagicMock()
    fake.generate = AsyncMock(side_effect=RuntimeError("anthropic 529 overloaded"))
    monkeypatch.setattr(sanitize_mod, "model", lambda: fake)

    with pytest.raises(RuntimeError, match="529 overloaded"):
        await sanitize_mod.sanitize_untrusted("content", artifact_id="a1")


def test_prompt_loads_from_file_when_present() -> None:
    """The sanitize prompt lives in src/donna/agent/prompts/sanitize.md.
    Test it loads (or the fallback kicks in if missing)."""
    # Clear cache to force re-read
    sanitize_mod._SANITIZE_PROMPT = None
    prompt = sanitize_mod._prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 50, (
        "prompt should be substantive — either loaded from sanitize.md "
        "or the hardcoded fallback. Anything shorter is suspicious."
    )
    # The prompt MUST instruct the model to ignore embedded instructions.
    # If this assertion ever fails, someone weakened the injection defense.
    assert "ignore" in prompt.lower() or "not follow" in prompt.lower(), (
        "prompt must instruct the model to ignore embedded instructions — "
        "that's the whole point of the dual-call defense"
    )


def test_prompt_falls_back_when_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from pathlib import Path

    # Force _SANITIZE_PROMPT_PATH to a nonexistent path, reset cache
    monkeypatch.setattr(
        sanitize_mod, "_SANITIZE_PROMPT_PATH", Path(tmp_path) / "does_not_exist.md",
    )
    sanitize_mod._SANITIZE_PROMPT = None

    prompt = sanitize_mod._prompt()
    assert "summarizer" in prompt.lower()
    assert "ignore" in prompt.lower()
    assert "summary" in prompt.lower()
