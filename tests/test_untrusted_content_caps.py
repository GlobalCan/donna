"""Untrusted content caps on fetch_url + ingest_discord_attachment.

Codex adversarial scan #4: the tools had no byte/content-type/page guards.
A model-chosen URL pointing at a multi-MB binary (or HTML bomb) would be
materialized in full, and the worker's 512MB container cap would likely be
hit before the sanitizer ran. Same class on attachments → huge PDFs.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from donna.tools import attachments as attachments_mod
from donna.tools import web as web_mod

# ---------- fetch_url -------------------------------------------------------


class _FakeStreamResponse:
    """Minimal async-context-manager mock for httpx.AsyncClient.stream()."""

    def __init__(
        self,
        chunks: list[bytes],
        *,
        content_type: str = "text/html; charset=utf-8",
        content_length: str | None = None,
    ) -> None:
        self._chunks = chunks
        self.headers: dict[str, str] = {"content-type": content_type}
        if content_length is not None:
            self.headers["content-length"] = content_length

    async def __aenter__(self) -> _FakeStreamResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c


def _patched_client(stream_response: _FakeStreamResponse) -> MagicMock:
    """Build an httpx.AsyncClient() replacement whose .stream() returns
    our fake response as an async context manager."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.stream = MagicMock(return_value=stream_response)
    return client


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_fetch_url_rejects_binary_content_type() -> None:
    fake = _FakeStreamResponse([b"binary"], content_type="application/octet-stream")
    with patch.object(web_mod.httpx, "AsyncClient", return_value=_patched_client(fake)):
        out = await web_mod.fetch_url(url="http://example.invalid/file.bin")
    assert out.get("error") == "unsupported_content_type"
    assert out.get("content_type") == "application/octet-stream"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_fetch_url_rejects_oversized_content_length() -> None:
    fake = _FakeStreamResponse(
        [b""],
        content_type="text/html",
        content_length=str(web_mod._FETCH_MAX_BYTES + 1),
    )
    with patch.object(web_mod.httpx, "AsyncClient", return_value=_patched_client(fake)):
        out = await web_mod.fetch_url(url="http://example.invalid/huge")
    assert out.get("error") == "content_length_exceeds_cap"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_fetch_url_truncates_on_overrun() -> None:
    """content-length absent but body exceeds cap via streaming — we stop
    reading and flag truncated=True."""
    # Chunk larger than the cap → loop exits after first chunk
    fake = _FakeStreamResponse(
        [b"x" * (web_mod._FETCH_MAX_BYTES + 100)],
        content_type="text/html",
    )
    # sanitize_untrusted is imported lazily inside fetch_url; patch at module level.
    with (
        patch.object(web_mod.httpx, "AsyncClient", return_value=_patched_client(fake)),
        patch("donna.security.sanitize.sanitize_untrusted", AsyncMock(return_value="[summary]")),
    ):
        out = await web_mod.fetch_url(url="http://example.invalid/bomb")
    assert out.get("truncated") is True


# ---------- ingest_discord_attachment ---------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_ingest_rejects_oversized_declared_content_length() -> None:
    fake = _FakeStreamResponse(
        [b""],
        content_type="application/pdf",
        content_length=str(attachments_mod._ATTACH_MAX_BYTES + 1),
    )
    with patch.object(attachments_mod.httpx, "AsyncClient", return_value=_patched_client(fake)):
        out = await attachments_mod.ingest_discord_attachment(
            scope="t", attachment_url="http://example.invalid/huge.pdf",
            title="Huge",
        )
    assert out.get("error") == "content_length_exceeds_cap"


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_ingest_rejects_overrun_via_stream() -> None:
    fake = _FakeStreamResponse(
        [b"x" * (attachments_mod._ATTACH_MAX_BYTES + 100)],
        content_type="text/plain",
    )
    with patch.object(attachments_mod.httpx, "AsyncClient", return_value=_patched_client(fake)):
        out = await attachments_mod.ingest_discord_attachment(
            scope="t", attachment_url="http://example.invalid/huge.txt",
            title="Huge text",
        )
    assert out.get("error") == "download_exceeded_cap"
