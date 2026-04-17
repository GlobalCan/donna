"""Donna — bot process entry point.

Connects to Discord, drains outbox queues, dispatches incoming messages into
the jobs table. The separate `worker` process actually runs the agent loops.
"""
from __future__ import annotations

import asyncio
import signal
import sys

from .adapter.discord_adapter import build_bot
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
    if not s.discord_bot_token:
        log.error("config.missing DISCORD_BOT_TOKEN")
        sys.exit(2)
    if not s.anthropic_api_key:
        log.error("config.missing ANTHROPIC_API_KEY")
        sys.exit(2)

    register_all_v1_tools()
    otel.initialize_tracing()

    bot = build_bot()

    # Budget watcher — uses the bot's DM channel
    async def notify(msg: str) -> None:
        try:
            user = await bot.fetch_user(s.discord_allowed_user_id)
            await user.send(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("budget.dm_failed", error=str(e))

    budget_watcher = BudgetWatcher(notify)
    ops_watchdog = Watchdog(notify)

    async def _budget_loop() -> None:
        await bot.wait_until_ready()
        await budget_watcher.loop()

    async def _watchdog_loop() -> None:
        await bot.wait_until_ready()
        await ops_watchdog.loop(interval_seconds=300)

    bot.loop.create_task(_budget_loop())
    bot.loop.create_task(_watchdog_loop())

    await bot.start(s.discord_bot_token)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
