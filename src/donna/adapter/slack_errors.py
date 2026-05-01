"""Slack error classification for outbox drainers.

slack_sdk raises SlackApiError for any non-ok response: same exception type
for transient (retry), terminal (drop), and unknown (dead-letter) errors.
Drainer loops have to classify themselves or risk infinite retry storms
(V50-1, 2026-05-01).

Three buckets:

- transient: temporary; retry with backoff. rate_limited, server_error,
  service_unavailable, request_timeout.

- terminal: will never succeed without operator intervention; drop the row,
  log WARN, alert operator (throttled DM). not_in_channel, channel_not_found,
  is_archived, account_inactive, invalid_auth, token_revoked, etc.

- unknown: never seen before; move to dead-letter for human review. We'd
  rather an operator eyeball a new error code than have the drainer guess.

Reference: https://api.slack.com/methods/chat.postMessage#errors
"""
from __future__ import annotations

from enum import StrEnum

from slack_sdk.errors import SlackApiError


class ErrorClass(StrEnum):
    TRANSIENT = "transient"
    TERMINAL = "terminal"
    UNKNOWN = "unknown"


# Errors that disappear after waiting / retry. Drainer leaves row in place.
TRANSIENT_ERRORS: frozenset[str] = frozenset({
    "rate_limited",
    "server_error",
    "service_unavailable",
    "request_timeout",
})

# Errors that will never succeed without operator intervention.
TERMINAL_ERRORS: frozenset[str] = frozenset({
    # Channel state
    "not_in_channel",
    "channel_not_found",
    "is_archived",
    "channel_is_archived",
    # Auth / scope state
    "invalid_auth",
    "token_revoked",
    "token_expired",
    "account_inactive",
    "missing_scope",
    "no_permission",
    "restricted_action",
    "not_allowed_token_type",
    # Message-shape problems (the message itself can never deliver)
    "msg_too_long",
    "message_too_long",
    "no_text",
    "invalid_blocks",
    "invalid_blocks_format",
    # Recipient state
    "user_not_found",
    "user_disabled",
    "cannot_dm_bot",
    # Permanent message-state mismatches (edit / delete paths)
    "message_not_found",
    "cant_update_message",
    "cant_delete_message",
    "edit_window_closed",
})


def classify_error_code(error_code: str | None) -> ErrorClass:
    """Map a Slack `error` field string to one of three retry classes.

    Returns UNKNOWN for anything not in the explicit lists. Caller routes
    UNKNOWN to dead-letter so a human can decide whether to add it to the
    transient or terminal set.
    """
    if not error_code:
        return ErrorClass.UNKNOWN
    if error_code in TRANSIENT_ERRORS:
        return ErrorClass.TRANSIENT
    if error_code in TERMINAL_ERRORS:
        return ErrorClass.TERMINAL
    return ErrorClass.UNKNOWN


def extract_error_code(exc: BaseException) -> str | None:
    """Pull the Slack `error` field out of a SlackApiError.

    SlackApiError.response is a SlackResponse with .data dict containing
    {ok: False, error: '<code>'}. Wrapping exception types (network timeouts,
    DNS failures) won't have this — return None and caller treats as
    unknown.
    """
    if not isinstance(exc, SlackApiError):
        return None
    response = getattr(exc, "response", None)
    if response is None:
        return None
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        return None
    code = data.get("error")
    return code if isinstance(code, str) else None


def extract_retry_after_seconds(exc: BaseException) -> float | None:
    """Pull Retry-After header value from a rate_limited SlackApiError.

    Slack sets `Retry-After` (seconds, integer string) on 429 responses.
    SlackApiError.response.headers is dict-like. Returns None when the
    header is missing or unparseable; caller falls back to its own backoff.
    """
    if not isinstance(exc, SlackApiError):
        return None
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = None
    if hasattr(headers, "get"):
        raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
