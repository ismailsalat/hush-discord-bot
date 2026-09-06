"""The /mod command group.

Moderators work with anonymous IDs, never identities. Every command here is
gated by one decorator and every action is written to the append-only ledger by
the service layer.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.base import HushCog
from app.core.constants import BanDuration
from app.core.exceptions import AliasNotFoundError
from app.security.permissions import MODERATION_LEVEL
from app.services.permission_service import requires
from app.views.common import respond
from app.views.moderation import ReportQueueView, mirror_to_mod_log

BAN_CHOICES = [
    app_commands.Choice(name=duration.label, value=duration.value)
    for duration in BanDuration
]


class ModerationCog(HushCog):
    """`/mod` - review, warn, ban, unban, history."""

    group = app_commands.Group(
        name="mod",
        description="Hush moderation tools.",
        guild_only=True,
    )

    async def _resolve_alias(self, interaction: discord.Interaction, alias: str):
        """Turn `A17` / `#A17` / `Anon #A17` into an alias row, or explain why not."""
        from app.services.alias_service import AliasService

        async with self.runtime.session() as session:
            found = await AliasService(
                session,
                default_rotation_days=self.runtime.settings.default_alias_rotation_days,
            ).find_public(interaction.guild_id, alias)
        if found is None:
            raise AliasNotFoundError(
                f"no alias {alias!r} in guild {interaction.guild_id}",
                user_message=f"No anonymous ID matches `{alias}` in this server.",
            )
        return found

    # --- Reports ------------------------------------------------------------

    @group.command(name="reports", description="Review open reports.")
    @requires(MODERATION_LEVEL, action="review reports")
    async def reports(self, interaction: discord.Interaction) -> None:
        from app.services.moderation_service import ModerationService

        runtime = self.runtime
        async with runtime.session() as session:
            rows = await ModerationService(session, runtime.settings).open_reports(
                interaction.guild_id
            )

        await respond(
            interaction,
            embed=runtime.moderation_embeds.report_queue(rows),
            view=ReportQueueView(
                guild_id=interaction.guild_id, moderator_id=interaction.user.id, rows=rows
            ),
        )

    # --- Direct actions -----------------------------------------------------

    @group.command(name="warn", description="Warn the author of a confession.")
    @app_commands.describe(
        anon_id="The anonymous ID shown on the confession, e.g. A17.",
        reason="Shown to the user in their warning notice.",
    )
    @requires(MODERATION_LEVEL, action="warn users")
    async def warn(
        self, interaction: discord.Interaction, anon_id: str, reason: str
    ) -> None:
        from app.services.moderation_service import ModerationService

        runtime = self.runtime
        alias = await self._resolve_alias(interaction, anon_id)

        async with runtime.session() as session:
            await ModerationService(session, runtime.settings).warn(
                internal_user_id=alias.internal_user_id,
                guild_id=interaction.guild_id,
                moderator_id=interaction.user.id,
                reason=reason,
                guild_name=interaction.guild.name if interaction.guild else None,
            )

        await respond(
            interaction,
            embed=runtime.embeds.success(
                "Warning issued",
                f"`{anon_id}` has been warned. They will see the notice the next time "
                "they use Hush, even if their DMs are closed.",
            ),
        )
        await mirror_to_mod_log(
            interaction,
            action="Warning Issued",
            alias_display=f"Anon #{alias.public_alias}",
            reason=reason,
            guild_id=interaction.guild_id,
            punishment="Warning",
        )

    @group.command(name="ban", description="Suspend an anonymous account from Hush.")
    @app_commands.describe(
        anon_id="The anonymous ID shown on the confession, e.g. A17.",
        duration="How long they lose access to Hush features.",
        reason="Shown to the user in their suspension notice.",
    )
    @app_commands.choices(duration=BAN_CHOICES)
    @requires(MODERATION_LEVEL, action="ban users")
    async def ban(
        self,
        interaction: discord.Interaction,
        anon_id: str,
        duration: app_commands.Choice[str],
        reason: str,
    ) -> None:
        from app.services.moderation_service import ModerationService

        runtime = self.runtime
        alias = await self._resolve_alias(interaction, anon_id)

        async with runtime.session() as session:
            await ModerationService(session, runtime.settings).ban(
                internal_user_id=alias.internal_user_id,
                guild_id=interaction.guild_id,
                moderator_id=interaction.user.id,
                duration=BanDuration(duration.value),
                reason=reason,
                guild_name=interaction.guild.name if interaction.guild else None,
            )

        await respond(
            interaction,
            embed=runtime.embeds.success(
                "Access suspended",
                f"`{anon_id}` can no longer use Hush in this server "
                f"({duration.name}).\n\nThis does not affect their Discord membership.",
            ),
        )
        await mirror_to_mod_log(
            interaction,
            action="Access Suspended",
            alias_display=f"Anon #{alias.public_alias}",
            reason=reason,
            guild_id=interaction.guild_id,
            punishment=duration.name,
        )

    @group.command(name="unban", description="Restore an account's access to Hush.")
    @app_commands.describe(anon_id="The anonymous ID, e.g. A17.")
    @requires(MODERATION_LEVEL, action="unban users")
    async def unban(self, interaction: discord.Interaction, anon_id: str) -> None:
        from app.services.access_service import AccessService
        from app.services.moderation_service import ModerationService

        runtime = self.runtime
        alias = await self._resolve_alias(interaction, anon_id)

        async with runtime.session() as session:
            ban = await AccessService(session, runtime.settings).active_ban(
                alias.internal_user_id, interaction.guild_id
            )
            if ban is None:
                await respond(
                    interaction,
                    embed=runtime.error_embeds.generic(
                        "Not suspended", f"`{anon_id}` is not currently suspended."
                    ),
                )
                return
            await ModerationService(session, runtime.settings).revoke_ban(
                ban.id,
                interaction.user.id,
                guild_name=interaction.guild.name if interaction.guild else None,
            )

        await respond(
            interaction,
            embed=runtime.embeds.success(
                "Access restored", f"`{anon_id}` can use Hush again."
            ),
        )
        await mirror_to_mod_log(
            interaction,
            action="Access Restored",
            alias_display=f"Anon #{alias.public_alias}",
            reason=None,
            guild_id=interaction.guild_id,
            punishment="Ban revoked",
        )

    @group.command(name="history", description="See an anonymous account's Hush history.")
    @app_commands.describe(anon_id="The anonymous ID, e.g. A17.")
    @requires(MODERATION_LEVEL, action="view moderation history")
    async def history(self, interaction: discord.Interaction, anon_id: str) -> None:
        from app.services.moderation_service import ModerationService

        runtime = self.runtime
        alias = await self._resolve_alias(interaction, anon_id)

        async with runtime.session() as session:
            report = await ModerationService(session, runtime.settings).punishment_history(
                alias.internal_user_id, interaction.guild_id
            )

        await respond(interaction, embed=runtime.moderation_embeds.history(report))

    @group.command(name="review", description="Open the moderation panel for a confession.")
    @app_commands.describe(number="The confession number shown on the post.")
    @requires(MODERATION_LEVEL, action="review confessions")
    async def review(self, interaction: discord.Interaction, number: int) -> None:
        from app.services.confession_service import ConfessionService
        from app.views.moderation import ModerationPanelView

        runtime = self.runtime
        async with runtime.session() as session:
            service = ConfessionService(session, runtime.settings)
            confession = await service.get_by_number(interaction.guild_id, number)
            data = await service.build_view(confession)

        await respond(
            interaction,
            embed=runtime.confession_embeds.build(data),
            view=ModerationPanelView(
                confession_id=confession.id,
                guild_id=interaction.guild_id,
                public_number=data.public_number,
                alias_display=data.alias_display,
                author_internal_user_id=confession.internal_user_id,
                moderator_id=interaction.user.id,
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
