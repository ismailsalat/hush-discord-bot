"""The Discord client."""

from __future__ import annotations

import discord
from discord.ext import commands

from app.config.settings import Settings
from app.core.runtime import Runtime
from app.database.session import Database, set_database
from app.lifecycle import load_extensions, shutdown_sequence, startup_sequence
from app.logging.setup import app_logger


def build_intents() -> discord.Intents:
    """The smallest set of intents that works.

    Notably ``message_content`` is *not* requested: confessions are typed into a
    modal, and reply counting only reads ``message.reference``. Nothing the bot
    does requires reading what members write.
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.dm_messages = True
    return intents


class HushBot(commands.Bot):
    def __init__(self, settings: Settings, database: Database):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=build_intents(),
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
            activity=discord.Activity(
                type=discord.ActivityType.listening, name=f"/{'confess'}"
            ),
        )
        self.settings = settings
        self.runtime = Runtime(settings, database)
        self._started = False

    async def setup_hook(self) -> None:
        """Runs once before the gateway connection completes."""
        set_database(self.runtime.database)
        loaded = await load_extensions(self)
        app_logger().info("extensions_loaded", count=len(loaded))

    async def on_ready(self) -> None:
        if self._started:
            app_logger().info("reconnected", user=str(self.user))
            return
        self._started = True
        await startup_sequence(self)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:  # pragma: no cover
        from app.logging.error_ids import report_exception
        import sys

        exc = sys.exc_info()[1]
        if exc is not None:
            report_exception(exc, operation=f"event.{event_method}")

    async def close(self) -> None:
        try:
            await shutdown_sequence(self)
        finally:
            await super().close()
