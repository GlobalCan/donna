"""V0.6 #4: `botctl slack-doctor` health check tests.

slack-doctor calls real Slack API methods via slack_sdk.WebClient. Tests
patch WebClient with stubs that return canned responses (or raise
SlackApiError) so we exercise every drift class without touching real
Slack.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError
from typer.testing import CliRunner

from donna.cli.botctl import app

runner = CliRunner()


class _FakeResponse(dict):
    """slack_sdk responses behave like dicts with a .data + .headers
    attribute. WebClient returns these from successful calls."""

    def __init__(
        self, data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(data or {})
        self.data = data or {}
        self.headers = headers or {}

    def get(self, k, default=None):
        return self.data.get(k, default)


def _slack_error(code: str) -> SlackApiError:
    resp = _FakeResponse(data={"ok": False, "error": code})
    return SlackApiError(message=f"slack rejected: {code}", response=resp)


def _ok_auth_test(
    user_id: str = "U_DONNA",
    team_id: str = "T_test",
    bot_user: str = "donna",
    scopes: str = "chat:write,commands,app_mentions:read,im:history,im:write",
) -> _FakeResponse:
    return _FakeResponse(
        data={
            "ok": True, "user_id": user_id, "user": bot_user,
            "team_id": team_id,
        },
        headers={"x-oauth-scopes": scopes},
    )


def _ok_connections_open() -> _FakeResponse:
    return _FakeResponse(
        data={"ok": True, "url": "wss://wss-primary.slack.com/link/abc"},
    )


def _ok_users_conversations(channels: list[dict] | None = None) -> _FakeResponse:
    return _FakeResponse(
        data={"ok": True, "channels": channels or []},
    )


# ---------- happy path ---------------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_all_green(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every check passes — exit 0, all-green summary."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.return_value = _ok_users_conversations(
        channels=[
            {"id": "C_DT", "name": "donna-test", "is_channel": True,
             "is_private": False},
        ],
    )
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 0, result.output
    assert "all green" in result.output
    assert "all required scopes present" in result.output
    assert "Socket Mode reachable" in result.output
    assert "donna-test" in result.output


# ---------- config-presence failures ------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_aborts_when_token_shape_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If env vars look broken before any API call, fail loud and don't
    bother making the HTTP requests."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "wrong")
    # Force settings re-read
    from donna import config as cfg
    cfg._settings = None

    result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 1
    assert "wrong shape" in result.output
    assert "cannot proceed" in result.output


# ---------- token / scope failures --------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_token_invalid_aborts() -> None:
    """auth.test returning invalid_auth aborts before scope/Socket Mode
    checks — token's broken, nothing else matters."""
    bot_client = MagicMock()
    bot_client.auth_test.side_effect = _slack_error("invalid_auth")
    app_client = MagicMock()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 1
    assert "auth.test rejected: invalid_auth" in result.output
    # No scope or Socket Mode checks should have run
    assert "Socket Mode reachable" not in result.output


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_flags_team_id_mismatch() -> None:
    """If the token's team doesn't match SLACK_TEAM_ID, every event is
    silently dropped by the bot — slack-doctor must surface this loud."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test(team_id="T_OTHER")
    bot_client.users_conversations.return_value = _ok_users_conversations()
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 1
    assert "doesn't match" in result.output
    assert "Token-vs-allowlist mismatch" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_flags_missing_scopes() -> None:
    """Missing chat:write or app_mentions:read = silent delivery failures.
    slack-doctor must surface every required scope that's absent."""
    bot_client = MagicMock()
    # Token has chat:write but missing app_mentions:read + im:write
    bot_client.auth_test.return_value = _ok_auth_test(
        scopes="chat:write,commands,im:history",
    )
    bot_client.users_conversations.return_value = _ok_users_conversations()
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 1
    assert "missing required scopes" in result.output
    assert "app_mentions:read" in result.output
    assert "im:write" in result.output


# ---------- Socket Mode kwarg passed through ----------------------------


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_passes_app_token_kwarg_to_connections_open() -> None:
    """v0.6.1 hotfix: slack_sdk requires app_token kwarg on
    apps.connections.open() even when the WebClient was constructed
    with that token. Pre-fix slack-doctor crashed with TypeError mid-run."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.return_value = _ok_users_conversations()
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 0
    # The fix: kwarg must be present
    call = app_client.apps_connections_open.call_args
    assert "app_token" in call.kwargs
    assert call.kwargs["app_token"].startswith("xapp-")


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_catches_typeerror_from_kwarg_drift() -> None:
    """Defensive: if slack_sdk changes its API surface and another
    keyword arg becomes required, slack-doctor should report the
    failure loud rather than crashing mid-check (v0.6.1 hotfix)."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.return_value = _ok_users_conversations()
    app_client = MagicMock()
    app_client.apps_connections_open.side_effect = TypeError(
        "missing 1 required keyword-only argument: 'frobnicator'",
    )

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 1
    assert "TypeError" in result.output
    assert "frobnicator" in result.output


# ---------- Socket Mode failure -----------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_flags_socket_mode_failure() -> None:
    """apps.connections.open rejected = Donna can't open her WebSocket =
    no events ever reach her. Fail."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.return_value = _ok_users_conversations()
    app_client = MagicMock()
    app_client.apps_connections_open.side_effect = _slack_error(
        "not_authed",
    )

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 1
    assert "apps.connections.open rejected" in result.output
    assert "not_authed" in result.output


# ---------- delivery probe ----------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_delivery_probe_success_cleans_up() -> None:
    """Probe path: send a message, get ts, delete it. Both calls must
    succeed; user shouldn't be left with `slack-doctor probe` litter."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.return_value = _ok_users_conversations()
    bot_client.chat_postMessage.return_value = _FakeResponse(
        data={"ok": True, "ts": "1234.5678"},
    )
    bot_client.chat_delete.return_value = _FakeResponse(data={"ok": True})
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(
            app, ["slack-doctor", "--delivery-channel", "C_TEST"],
        )
    assert result.exit_code == 0, result.output
    assert "delivered" in result.output
    assert "probe message deleted" in result.output
    bot_client.chat_postMessage.assert_called_once()
    bot_client.chat_delete.assert_called_once()


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_delivery_probe_not_in_channel_fails() -> None:
    """If the bot can't post to the requested channel, that's a real
    Slack permission drift — fail the doctor."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.return_value = _ok_users_conversations()
    bot_client.chat_postMessage.side_effect = _slack_error("not_in_channel")
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(
            app, ["slack-doctor", "--delivery-channel", "C_NOT_MEMBER"],
        )
    assert result.exit_code == 1
    assert "chat.postMessage rejected: not_in_channel" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_no_delivery_probe_when_flag_omitted() -> None:
    """Without --delivery-channel, no chat.postMessage / chat.delete
    is made. Operators can run slack-doctor as a routine check without
    spamming a channel."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.return_value = _ok_users_conversations()
    bot_client.chat_postMessage.side_effect = AssertionError(
        "should not be called",
    )
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 0
    bot_client.chat_postMessage.assert_not_called()


# ---------- channel membership listing ----------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_lists_member_channels() -> None:
    """Operator wants to see at-a-glance which channels Donna is in.
    Slack permission drift includes 'I forgot which channels she has
    access to'."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.return_value = _ok_users_conversations(
        channels=[
            {"id": "C_DT", "name": "donna-test",
             "is_channel": True, "is_private": False},
            {"id": "C_MB", "name": "morning-brief",
             "is_channel": True, "is_private": False},
            {"id": "D_DM", "is_im": True},
        ],
    )
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 0
    assert "2 public" in result.output
    assert "1 DMs" in result.output
    assert "donna-test" in result.output
    assert "morning-brief" in result.output


# ---------- V60-4: missing_scope on channel listing is WARN, not FAIL ----


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_demotes_users_conversations_missing_scope() -> None:
    """V60-4 (v0.6.2): the v0.5.0 manifest deliberately omits
    `channels:read` and `groups:read` per Codex's privacy review.
    `users.conversations` requires those scopes for channel listing,
    so it returns missing_scope on a healthy minimally-scoped bot.

    Pre-fix slack-doctor exited 1 on this -> operator chasing a
    non-existent failure on every routine check. Demote to WARN so
    a healthy bot reports all-green.
    """
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.side_effect = _slack_error(
        "missing_scope",
    )
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 0, result.output
    assert "WARN" in result.output
    assert "missing_scope" in result.output
    assert "Channel listing skipped" in result.output
    assert "all green" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_slack_doctor_other_users_conversations_errors_still_fail() -> None:
    """V60-4 demote applies ONLY to missing_scope. Other Slack errors
    on users.conversations (rate_limited, account_inactive, ...) are
    still real problems that should fail loud."""
    bot_client = MagicMock()
    bot_client.auth_test.return_value = _ok_auth_test()
    bot_client.users_conversations.side_effect = _slack_error(
        "account_inactive",
    )
    app_client = MagicMock()
    app_client.apps_connections_open.return_value = _ok_connections_open()

    def _make_client(token: str):
        return app_client if token.startswith("xapp-") else bot_client

    with patch(
        "slack_sdk.web.client.WebClient", side_effect=_make_client,
    ):
        result = runner.invoke(app, ["slack-doctor"])
    assert result.exit_code == 1, result.output
    assert "users.conversations failed: account_inactive" in result.output
