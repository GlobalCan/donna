"""V50-1: Slack error classifier + extractor unit tests.

Pure logic, no DB. Verifies the three-bucket classification and the
SlackApiError unwrapping helpers used by the outbox drainer.
"""
from __future__ import annotations

from slack_sdk.errors import SlackApiError

from donna.adapter.slack_errors import (
    TERMINAL_ERRORS,
    TRANSIENT_ERRORS,
    ErrorClass,
    classify_error_code,
    extract_error_code,
    extract_retry_after_seconds,
)

# ---------- classifier ----------------------------------------------------


def test_classify_known_transient_codes() -> None:
    for code in ("rate_limited", "server_error", "service_unavailable",
                 "request_timeout"):
        assert classify_error_code(code) is ErrorClass.TRANSIENT, code


def test_classify_known_terminal_codes() -> None:
    samples = (
        "not_in_channel", "channel_not_found", "is_archived",
        "invalid_auth", "token_revoked", "account_inactive",
        "msg_too_long", "no_text", "user_not_found",
        "no_permission", "missing_scope", "message_not_found",
    )
    for code in samples:
        assert classify_error_code(code) is ErrorClass.TERMINAL, code


def test_classify_unknown_code_returns_unknown() -> None:
    assert classify_error_code("a_brand_new_slack_error") is ErrorClass.UNKNOWN
    assert classify_error_code("") is ErrorClass.UNKNOWN
    assert classify_error_code(None) is ErrorClass.UNKNOWN


def test_terminal_and_transient_sets_disjoint() -> None:
    """A code shouldn't claim both classes — that would make the routing
    decision silently dependent on lookup order."""
    assert TERMINAL_ERRORS.isdisjoint(TRANSIENT_ERRORS)


# ---------- extract_error_code -------------------------------------------


class _FakeResponse:
    """Minimal stand-in for slack_sdk.web.SlackResponse — we only need the
    .data and .headers attributes."""

    def __init__(self, data: dict | None = None, headers: dict | None = None):
        self.data = data
        self.headers = headers


def _make_slack_error(
    error_code: str | None, headers: dict | None = None,
) -> SlackApiError:
    data = {"ok": False, "error": error_code} if error_code is not None else {}
    return SlackApiError(
        message=f"slack rejected: {error_code}",
        response=_FakeResponse(data=data, headers=headers),
    )


def test_extract_error_code_from_slackapierror() -> None:
    exc = _make_slack_error("not_in_channel")
    assert extract_error_code(exc) == "not_in_channel"


def test_extract_error_code_returns_none_for_non_slack_exception() -> None:
    assert extract_error_code(ValueError("nope")) is None
    assert extract_error_code(RuntimeError("network down")) is None


def test_extract_error_code_returns_none_when_data_missing() -> None:
    """A SlackApiError without a response or with missing data shouldn't
    crash the classifier — it returns None and the caller treats as
    unknown."""
    exc = SlackApiError(message="malformed", response=_FakeResponse(data=None))
    assert extract_error_code(exc) is None


def test_extract_error_code_returns_none_when_error_field_missing() -> None:
    exc = SlackApiError(message="ok=False but no error", response=_FakeResponse(data={"ok": False}))
    assert extract_error_code(exc) is None


# ---------- extract_retry_after_seconds ----------------------------------


def test_extract_retry_after_returns_seconds_from_headers() -> None:
    exc = _make_slack_error("rate_limited", headers={"Retry-After": "30"})
    assert extract_retry_after_seconds(exc) == 30.0


def test_extract_retry_after_case_insensitive() -> None:
    """Some Slack edges return lowercase header name."""
    exc = _make_slack_error("rate_limited", headers={"retry-after": "5"})
    assert extract_retry_after_seconds(exc) == 5.0


def test_extract_retry_after_returns_none_when_header_missing() -> None:
    exc = _make_slack_error("rate_limited", headers={})
    assert extract_retry_after_seconds(exc) is None


def test_extract_retry_after_returns_none_on_unparseable() -> None:
    """Not all upstream proxies return integer-string Retry-After.
    Unparseable falls back to None so caller uses its own backoff."""
    exc = _make_slack_error(
        "rate_limited", headers={"Retry-After": "in a bit"},
    )
    assert extract_retry_after_seconds(exc) is None


def test_extract_retry_after_returns_none_for_non_slack_exception() -> None:
    assert extract_retry_after_seconds(ValueError("x")) is None
