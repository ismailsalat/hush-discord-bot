"""Profile screens, including the alias rotation flow."""

from __future__ import annotations

import discord

from app.utils.pagination import paginate
from app.views.common import HushView, guarded, respond, runtime_of


class ProfileView(HushView):
    def __init__(self, *, alias_id: str, guild_id: int, own_profile: bool = False):
        super().__init__(timeout=300)
        self.alias_id = alias_id
        self.guild_id = guild_id
        self.own_profile = own_profile

        self.add_item(_AllConfessionsButton())
        if own_profile:
            self.add_item(_FollowingButton())
            self.add_item(_ChangeAliasButton())


class _AllConfessionsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="All Confessions", emoji="\U0001f4dc")

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.profile_service import ProfileService

            view: ProfileView = self.view  # type: ignore[assignment]
            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                service = ProfileService(session)
                rows = await service.list_all_confessions(view.alias_id)
                profile = await service.build(view.alias_id, recent_limit=0)
            await respond(
                interaction,
                embed=runtime.profile_embeds.confession_list(
                    profile.alias_display, paginate(rows, 0, 10)
                ),
            )

        await guarded(interaction, "profile.all_confessions", action)


class _FollowingButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Following", emoji="\u2764\ufe0f")

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.follow_service import FollowService
            from app.services.user_service import UserService

            view: ProfileView = self.view  # type: ignore[assignment]
            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                user = await UserService(session, runtime.settings).resolve(
                    interaction.user.id, view.guild_id
                )
                pairs = await FollowService(session).following(user.internal_id, view.guild_id)

            from app.security.identifiers import format_alias

            rows = [
                (format_alias(alias.public_alias), alias.is_current) for _follow, alias in pairs
            ]
            await respond(interaction, embed=runtime.profile_embeds.following(rows))

        await guarded(interaction, "profile.following", action)


class _ChangeAliasButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Change Anonymous ID", emoji="\U0001f504",
                         style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.alias_service import AliasService
            from app.services.user_service import UserService
            from app.utils.time import discord_timestamp

            view: ProfileView = self.view  # type: ignore[assignment]
            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                user = await UserService(session, runtime.settings).resolve(
                    interaction.user.id, view.guild_id
                )
                service = AliasService(
                    session, default_rotation_days=runtime.settings.default_alias_rotation_days
                )
                alias = await service.get_or_create_current(user.internal_id, view.guild_id)
                allowed, next_at = await service.can_rotate(alias, view.guild_id)

            from app.security.identifiers import format_alias

            embed = runtime.agreement_embeds.alias_rotation_notice(
                current_alias=format_alias(alias.public_alias),
                available_on=discord_timestamp(next_at, "F") if next_at else None,
                can_rotate=allowed,
            )
            await respond(
                interaction,
                embed=embed,
                view=RotateAliasView(guild_id=view.guild_id) if allowed else None,
            )

        await guarded(interaction, "profile.change_alias", action)


class RotateAliasView(HushView):
    def __init__(self, *, guild_id: int):
        super().__init__(timeout=180)
        self.guild_id = guild_id

    @discord.ui.button(
        label="Change My ID", emoji="\U0001f504", style=discord.ButtonStyle.danger
    )
    async def rotate(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async def action() -> None:
            from app.security.identifiers import format_alias
            from app.services.alias_service import AliasService
            from app.services.user_service import UserService

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                user = await UserService(session, runtime.settings).resolve(
                    interaction.user.id, self.guild_id
                )
                old, new = await AliasService(
                    session, default_rotation_days=runtime.settings.default_alias_rotation_days
                ).rotate(user.internal_id, self.guild_id)

            await respond(
                interaction,
                embed=runtime.agreement_embeds.alias_rotated(
                    old_alias=format_alias(old.public_alias),
                    new_alias=format_alias(new.public_alias),
                ),
                view=None,
                edit=True,
            )

        await guarded(interaction, "profile.rotate_alias", action)

    @discord.ui.button(label="Keep Current ID", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        runtime = runtime_of(interaction)
        await interaction.response.edit_message(
            embed=runtime.error_embeds.generic(
                "No changes", "You kept your current anonymous ID."
            ),
            view=None,
        )
