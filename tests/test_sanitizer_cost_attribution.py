"""Cross-vendor review #8 (Codex GPT-5): `sanitize_untrusted` called
`model().generate()` without passing `job_id`. The cost ledger therefore
couldn't attribute the Haiku-sanitize spend to the calling job — an
invisible blind spot in `botctl cost`. On a heavily-tainted day
(many `fetch_url` / `search_web` / `ingest_discord_attachment` calls),
this could undercount per-job cost by a noticeable margin.

Fix threads `job_id` through:
  sanitize_untrusted(..., job_id=...)
    → model().generate(..., job_id=...)
      → cost_ledger.record_llm_usage(job_id=...)

These tests pin the threading.
"""
from __future__ import annotations

import pytest

from donna.security.sanitize import sanitize_untrusted


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_sanitize_untrusted_passes_job_id_to_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capture the `job_id` arg the model adapter actually sees."""
    captured: dict = {}

    class _FakeResult:
        text = "summary"
        cost_usd = 0.0
        raw_content = []
        tool_uses = []
        stop_reason = "end_turn"

    class _FakeModel:
        async def generate(self, **kw):
            captured.update(kw)
            return _FakeResult()

    monkeypatch.setattr(
        "donna.security.sanitize.model", lambda: _FakeModel(),
    )

    await sanitize_untrusted(
        "some untrusted content body to sanitize",
        artifact_id="art_1",
        source_url="http://example.com",
        job_id="job_xyz",
    )
    assert captured.get("job_id") == "job_xyz", (
        f"sanitize_untrusted must thread job_id through to model.generate; "
        f"captured kw={list(captured.keys())}, job_id={captured.get('job_id')!r}"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_sanitize_untrusted_omits_job_id_when_not_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backwards-compat: callers that don't pass job_id (legacy code, tests)
    still work — the value passed through is None, which `model.generate`
    accepts."""
    captured: dict = {}

    class _FakeResult:
        text = "summary"
        cost_usd = 0.0

    class _FakeModel:
        async def generate(self, **kw):
            captured.update(kw)
            return _FakeResult()

    monkeypatch.setattr(
        "donna.security.sanitize.model", lambda: _FakeModel(),
    )

    await sanitize_untrusted(
        "content", artifact_id="art_1",
    )
    assert "job_id" in captured
    assert captured["job_id"] is None


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_sanitize_untrusted_short_circuits_without_calling_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty content: don't call the model at all. Pre-existing invariant
    must survive the job_id refactor."""
    called = False

    class _R:
        text = "x"
        cost_usd = 0.0

    class _FakeModel:
        async def generate(self, **kw):
            nonlocal called
            called = True
            return _R()

    monkeypatch.setattr(
        "donna.security.sanitize.model", lambda: _FakeModel(),
    )

    out = await sanitize_untrusted("   ", artifact_id="art_x", job_id="job_xyz")
    assert out == "[no substantive content]"
    assert called is False


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_search_web_threads_job_id_through_sanitizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end through search_web → _sanitize_hits → sanitize_untrusted →
    model.generate. The job_id from the agent's tool-call injection (via
    inspect.signature in JobContext._execute_one) must reach the cost
    ledger."""
    captured_job_ids: list = []

    class _FakeResult:
        text = "summary"
        cost_usd = 0.0

    class _FakeModel:
        async def generate(self, **kw):
            captured_job_ids.append(kw.get("job_id"))
            return _FakeResult()

    monkeypatch.setattr(
        "donna.security.sanitize.model", lambda: _FakeModel(),
    )

    # Stub Tavily to return synthetic hits
    from donna.tools import web as web_mod

    class _FakeTavily:
        async def search(self, **kw):
            return {"results": [
                {"title": "T1", "url": "http://a/", "content": "hit one body"},
                {"title": "T2", "url": "http://b/", "content": "hit two body"},
            ]}
    monkeypatch.setattr(web_mod, "_tv", lambda: _FakeTavily())

    await web_mod.search_web(query="anything", max_results=2, job_id="job_e2e")
    assert captured_job_ids == ["job_e2e", "job_e2e"], (
        f"each parallel sanitize call must propagate job_id; got {captured_job_ids}"
    )


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_search_news_threads_job_id_through_sanitizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_job_ids: list = []

    class _FakeResult:
        text = "summary"
        cost_usd = 0.0

    class _FakeModel:
        async def generate(self, **kw):
            captured_job_ids.append(kw.get("job_id"))
            return _FakeResult()

    monkeypatch.setattr(
        "donna.security.sanitize.model", lambda: _FakeModel(),
    )

    from donna.tools import web as web_mod

    class _FakeTavily:
        async def search(self, **kw):
            return {"results": [
                {"title": "N1", "url": "http://n/",
                 "content": "news body one", "published_date": "2024-01-01"},
            ]}
    monkeypatch.setattr(web_mod, "_tv", lambda: _FakeTavily())

    await web_mod.search_news(query="anything", max_results=1, job_id="job_news")
    assert captured_job_ids == ["job_news"]
