"""First-time rules agreement."""

from __future__ import annotations

import discord

from app.security.identifiers import build_custom_id
from app.services.agreement_service import AgreementService
from app.services.alias_service import AliasService
from app.services.user_service import UserService
from app.views.common import PersistentView, guarded, respond, runtime_of


class AgreeButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"cf:agree:(?P<gid>\d+):(?P<ver>\d+)",
):
    """Persistent: an agreement prompt sitting in a DM must survive a restart.

    The guild id here is public information (the server the user is in), so it
    is safe to embed. No user identity is present in the custom id.
    """

    def __init__(self, guild_id: int, version: int):
        self.guild_id = guild_id
        self.version = version
        super().__init__(
            discord.ui.Button(
                label="I Agree",
                style=discord.ButtonStyle.success,
                custom_id=f"cf:agree:{guild_id}:{version}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):  # noqa: D102
        return cls(int(match["gid"]), int(match["ver"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            runtime = runtime_of(interaction)
            guild = interaction.client.get_guild(self.guild_id)

            async with runtime.session() as session:
                user = await UserService(session, runtime.settings).resolve(
                    interaction.user.id, self.guild_id
                )
                await AgreementService(session).accept(
                    user.internal_id, self.guild_id, self.version
                )
                # Mint the alias now so their first confession is instant.
                await AliasService(
                    session, default_rotation_days=runtime.settings.default_alias_rotation_days
                ).get_or_create_current(user.internal_id, self.guild_id)

            from app.views.home import HomeView

            await respond(
                interaction,
                embed=runtime.agreement_embeds.accepted(guild.name if guild else None),
                view=HomeView(guild_id=self.guild_id),
                edit=True,
            )

        await guarded(interaction, "agreement.accept", action)


class CancelAgreementButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"cf:agreecancel:(?P<gid>\d+)",
):
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="Cancel",
                style=discord.ButtonStyle.secondary,
                custom_id=f"cf:agreecancel:{guild_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):  # noqa: D102
        return cls(int(match["gid"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            runtime = runtime_of(interaction)
            await respond(
                interaction,
                embed=runtime.agreement_embeds.cancelled(),
                view=None,
                edit=True,
            )

        await guarded(interaction, "agreement.cancel", action)


class AgreementView(PersistentView):
    def __init__(self, *, guild_id: int, version: int):
        super().__init__()
        self.add_item(AgreeButton(guild_id, version))
        self.add_item(CancelAgreementButton(guild_id))


__all__ = ["AgreementView", "AgreeButton", "CancelAgreementButton", "build_custom_id"]
