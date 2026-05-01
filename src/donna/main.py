"""Donna — bot process entry point (Slack adapter, v0.5.0+).

Connects to Slack via Socket Mode, drains outbox queues, dispatches
incoming messages into the jobs table. The separate `worker` process
actually runs the agent loops.

v0.4.x ran a Discord bot here; v0.5.0 retooled the entire adapter
package (`adapter/discord_adapter.py` + `adapter/discord_ux.py` →
`adapter/slack_adapter.py` + `adapter/slack_ux.py`). Revival point:
git tag `legacy/v0.4.4-discord`.
"""
from __future__ import annotations

import asyncio
import contextlib
import sys

from .adapter.slack_adapter import build_bot
from .config import settings
from .logging import configure_logging, get_logger
from .observability import otel
from .observability.budget import BudgetWatcher
from .observability.watchdog import Watchdog
from .tools import register_all_v1_tools


async def _run() -> None:
    configure_logging()
    log = get_logger("donna.bot")

    s = settings()
    missing: list[str] = []
    if not s.slack_bot_token:
        missing.append("SLACK_BOT_TOKEN")
    if not s.slack_app_token:
        missing.append("SLACK_APP_TOKEN")
    if not s.slack_team_id:
        missing.append("SLACK_TEAM_ID")
    if not s.slack_allowed_user_id:
        missing.append("SLACK_ALLOWED_USER_ID")
    if not s.anthropic_api_key:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        log.error("config.missing", keys=missing)
        sys.exit(2)

    register_all_v1_tools()
    otel.initialize_tracing()

    bot = build_bot()

    # Budget watcher + Watchdog notify the operator via DM. Uses the
    # Slack Web API directly — Slack opens a DM conversation between
    # the bot and a user the first time we post to that user_id.
    async def notify(msg: str) -> None:
        try:
            await bot.client.chat_postMessage(
                channel=s.slack_allowed_user_id,
                text=msg,
                unfurl_links=False,
                unfurl_media=False,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("budget.dm_failed", error=str(e))

    budget_watcher = BudgetWatcher(notify)
    ops_watchdog = Watchdog(notify)

    async def _budget_loop() -> None:
        # No equivalent of discord.py's `wait_until_ready` here —
        # SocketModeHandler.start_async() comes online quickly. Wait a
        # few seconds for the connection to stabilize before the first
        # budget check (which can post a DM).
        await asyncio.sleep(5.0)
        await budget_watcher.loop()

    async def _watchdog_loop() -> None:
        await asyncio.sleep(5.0)
        await ops_watchdog.loop(interval_seconds=300)

    asyncio.create_task(_budget_loop())
    asyncio.create_task(_watchdog_loop())

    await bot.start()


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
