"""DM-only profile, bookmark and follow commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.base import HushCog, dm_only, require_dm
from app.utils.pagination import paginate
from app.views.common import respond
from app.views.gate import ensure_ready
from app.views.picker import run_for_dm_guild
from app.views.profile import ProfileView


class ProfilesCog(HushCog):
    @app_commands.command(name="profile", description="View an anonymous profile.")
    @dm_only()
    @app_commands.describe(alias="Anonymous ID such as A17. Leave blank for your own.")
    async def profile(self, interaction: discord.Interaction, alias: str | None = None) -> None:
        require_dm(interaction)

        async def action(inner: discord.Interaction, guild_id: int) -> None:
            runtime = self.runtime
            actor = await ensure_ready(inner, guild_id)
            if actor is None:
                return

            from app.services.alias_service import AliasService
            from app.services.profile_service import ProfileService

            async with runtime.session() as session:
                if alias:
                    found = await AliasService(
                        session,
                        default_rotation_days=runtime.settings.default_alias_rotation_days,
                    ).find_public(guild_id, alias)
                    if found is None:
                        await respond(
                            inner,
                            embed=runtime.error_embeds.generic(
                                "Not found",
                                f"No anonymous profile matches `{alias}` in that server.",
                            ),
                        )
                        return
                    view_data = await ProfileService(session).build(found.id)
                    own = found.internal_user_id == actor.internal_id
                else:
                    view_data = await ProfileService(session).build_for_user(
                        actor.internal_id, guild_id
                    )
                    own = True

            await respond(
                inner,
                embed=runtime.profile_embeds.build(view_data, own_profile=own),
                view=ProfileView(
                    alias_id=view_data.alias_id,
                    guild_id=guild_id,
                    own_profile=own,
                ),
            )

        await run_for_dm_guild(
            interaction,
            action,
            prompt="Choose which server's anonymous profile you want to view.",
        )

    @app_commands.command(name="bookmarks", description="See the confessions you've saved.")
    @dm_only()
    async def bookmarks(self, interaction: discord.Interaction) -> None:
        require_dm(interaction)

        async def action(inner: discord.Interaction, guild_id: int) -> None:
            runtime = self.runtime
            actor = await ensure_ready(inner, guild_id)
            if actor is None:
                return

            from app.services.bookmark_service import BookmarkService

            async with runtime.session() as session:
                rows = await BookmarkService(session).list_rows(
                    actor.internal_id, guild_id=guild_id
                )
            await respond(
                inner,
                embed=runtime.profile_embeds.bookmarks(paginate(rows, 0, 8)),
            )

        await run_for_dm_guild(
            interaction,
            action,
            prompt="Choose which server's bookmarks you want to view.",
        )

    @app_commands.command(name="following", description="See which anonymous profiles you follow.")
    @dm_only()
    async def following(self, interaction: discord.Interaction) -> None:
        require_dm(interaction)

        async def action(inner: discord.Interaction, guild_id: int) -> None:
            runtime = self.runtime
            actor = await ensure_ready(inner, guild_id)
            if actor is None:
                return

            from app.security.identifiers import format_alias
            from app.services.follow_service import FollowService

            async with runtime.session() as session:
                pairs = await FollowService(session).following(actor.internal_id, guild_id)
            rows = [(format_alias(alias.public_alias), alias.is_current) for _f, alias in pairs]
            await respond(inner, embed=runtime.profile_embeds.following(rows))

        await run_for_dm_guild(
            interaction,
            action,
            prompt="Choose which server's followed profiles you want to view.",
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfilesCog(bot))
