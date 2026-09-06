"""Discord implementation of :class:`ConfessionPublisher`.

This is the only place that turns a :class:`ConfessionView` into an actual
message. Keeping it behind the protocol is what lets the whole service layer be
tested without touching the Discord API.
"""

from __future__ import annotations

import discord

from app.core.exceptions import GuildNotConfiguredError, MissingChannelPermissionsError
from app.core.runtime import Runtime
from app.services.dto import ConfessionView
from app.services.publishing_service import PublishedMessage, PublishTarget

#: Permissions the bot needs in a confession channel to function at all.
REQUIRED_PERMISSIONS = ("view_channel", "send_messages", "embed_links")


class DiscordPublisher:
    def __init__(self, client: discord.Client, runtime: Runtime):
        self.client = client
        self.runtime = runtime

    # --- Internals ----------------------------------------------------------

    async def _channel(self, channel_id: int) -> discord.abc.Messageable:
        channel = self.client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.client.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden) as exc:
                raise GuildNotConfiguredError() from exc
        if not isinstance(channel, discord.abc.Messageable):
            raise GuildNotConfiguredError()
        return channel

    def _check_permissions(self, channel: discord.abc.Messageable) -> None:
        guild = getattr(channel, "guild", None)
        if guild is None or guild.me is None:
            return
        permissions = channel.permissions_for(guild.me)  # type: ignore[union-attr]
        missing = [
            name.replace("_", " ").title()
            for name in REQUIRED_PERMISSIONS
            if not getattr(permissions, name, False)
        ]
        if missing:
            raise MissingChannelPermissionsError(
                channel_mention=getattr(channel, "mention", "the confession channel"),
                missing=missing,
            )

    async def _components(self, view: ConfessionView) -> discord.ui.View:
        from app.database.repositories import GuildRepository
        from app.views.confession import ConfessionActionView
        from app.views.polls import PollVoteButton

        async with self.runtime.session() as session:
            settings = await GuildRepository(session).get_settings(view.guild_id)

        components = ConfessionActionView(view.confession_id, settings=settings)
        if view.has_poll and view.poll is not None:
            for index, option in enumerate(view.poll.options[:4]):
                components.add_item(PollVoteButton(view.poll.poll_id, index, option.label))
        return components

    def _embeds(self, view: ConfessionView) -> list[discord.Embed]:
        embeds = [self.runtime.confession_embeds.build(view)]
        if view.has_poll and view.poll is not None:
            embeds.append(
                self.runtime.confession_embeds.poll(
                    view.poll,
                    alias_display=view.alias_display,
                    public_number=view.public_number,
                )
            )
        return embeds

    # --- Protocol -----------------------------------------------------------

    async def publish(self, view: ConfessionView, target: PublishTarget) -> PublishedMessage:
        channel = await self._channel(target.channel_id)
        self._check_permissions(channel)
        message = await channel.send(embeds=self._embeds(view), view=await self._components(view))
        return PublishedMessage(message_id=message.id, channel_id=message.channel.id)

    async def refresh(self, view: ConfessionView, message_id: int, channel_id: int) -> None:
        channel = await self._channel(channel_id)
        try:
            message = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
        except discord.NotFound:
            return
        await message.edit(embeds=self._embeds(view), view=await self._components(view))

    async def withdraw(self, message_id: int, channel_id: int) -> None:
        channel = await self._channel(channel_id)
        try:
            message = await channel.fetch_message(message_id)  # type: ignore[attr-defined]
        except discord.NotFound:
            return
        try:
            await message.delete()
        except discord.Forbidden:
            # Cannot delete - at least stop it being interactive and mark it.
            await message.edit(
                embed=self.runtime.embeds.unavailable(
                    "This confession was removed by a moderator."
                ),
                view=None,
            )
