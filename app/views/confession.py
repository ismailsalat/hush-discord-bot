"""The public confession action row.

Exactly four buttons: Rate, Profile, Follow, More. Everything else is behind
More, so a confession never turns into a wall of buttons.

All four are :class:`discord.ui.DynamicItem` components, which is what keeps
them working after a restart: the confession id lives in the custom id and is
parsed back out on click, so no in-memory view state is required.
"""

from __future__ import annotations

import discord

from app.security.identifiers import build_custom_id
from app.views.common import PersistentView, guarded, respond, runtime_of

CONFESSION_ID_PATTERN = r"(?P<cid>conf_[0-9a-f]{4,32})"


def _button(
    action: str,
    confession_id: str,
    *,
    label: str,
    emoji: str | None = None,
    style: discord.ButtonStyle = discord.ButtonStyle.secondary,
) -> discord.ui.Button:
    """Build one public confession button.

    ``build_custom_id`` is the privacy tripwire: it refuses to encode a Discord
    snowflake or an internal user id, so no button can ever leak an identity
    into a custom id.
    """
    kwargs = {
        "label": label,
        "style": style,
        "custom_id": build_custom_id(action, confession_id),
    }
    if emoji is not None:
        kwargs["emoji"] = emoji
    return discord.ui.Button(**kwargs)


class RateConfessionButton(
    discord.ui.DynamicItem[discord.ui.Button], template=rf"cf:rate:{CONFESSION_ID_PATTERN}"
):
    def __init__(self, confession_id: str):
        self.confession_id = confession_id
        super().__init__(
            _button(
                "rate", confession_id, label="Rate", emoji="\u2b50",
                style=discord.ButtonStyle.primary,
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):  # noqa: D102
        return cls(match["cid"])

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.confession_service import ConfessionService
            from app.services.rating_service import RatingService
            from app.views.gate import ensure_ready
            from app.views.rating import RatingView

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                confession = await ConfessionService(session, runtime.settings).get_visible(
                    self.confession_id
                )
                guild_id = confession.guild_id

            actor = await ensure_ready(interaction, guild_id)
            if actor is None:
                return

            async with runtime.session() as session:
                service = RatingService(session, runtime.settings)
                scale_min, scale_max = await service.scale(guild_id)
                current = await service.get_existing_value(
                    self.confession_id, actor.internal_id
                )

            view = RatingView(
                confession_id=self.confession_id,
                guild_id=guild_id,
                internal_user_id=actor.internal_id,
                scale_min=scale_min,
                scale_max=scale_max,
                current=current,
            )
            await respond(
                interaction,
                embed=RatingView.prompt_embed(runtime, current=current, scale_max=scale_max),
                view=view,
            )

        await guarded(interaction, "confession.rate_open", action)


class ProfileConfessionButton(
    discord.ui.DynamicItem[discord.ui.Button], template=rf"cf:prof:{CONFESSION_ID_PATTERN}"
):
    def __init__(self, confession_id: str):
        self.confession_id = confession_id
        super().__init__(_button("prof", confession_id, label="Profile", emoji="\U0001f464"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):  # noqa: D102
        return cls(match["cid"])

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.confession_service import ConfessionService
            from app.services.profile_service import ProfileService
            from app.views.gate import ensure_ready
            from app.views.profile import ProfileView as ProfileUIView

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                confession = await ConfessionService(session, runtime.settings).get_visible(
                    self.confession_id
                )
                guild_id, alias_id = confession.guild_id, confession.alias_id

            actor = await ensure_ready(interaction, guild_id)
            if actor is None:
                return

            async with runtime.session() as session:
                profile = await ProfileService(session).build(alias_id)

            await respond(
                interaction,
                embed=runtime.profile_embeds.build(profile),
                view=ProfileUIView(alias_id=alias_id, guild_id=guild_id),
            )

        await guarded(interaction, "confession.profile", action)


class FollowConfessionButton(
    discord.ui.DynamicItem[discord.ui.Button], template=rf"cf:fol:{CONFESSION_ID_PATTERN}"
):
    def __init__(self, confession_id: str):
        self.confession_id = confession_id
        super().__init__(_button("fol", confession_id, label="Follow", emoji="\u2764\ufe0f"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):  # noqa: D102
        return cls(match["cid"])

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.confession_service import ConfessionService
            from app.services.follow_service import FollowService
            from app.views.gate import ensure_ready

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                confession = await ConfessionService(session, runtime.settings).get_visible(
                    self.confession_id
                )
                guild_id, alias_id = confession.guild_id, confession.alias_id

            actor = await ensure_ready(interaction, guild_id)
            if actor is None:
                return

            async with runtime.session() as session:
                service = FollowService(session)
                now_following = await service.toggle(
                    follower_internal_user_id=actor.internal_id, alias_id=alias_id
                )
                from app.services.profile_service import ProfileService

                profile = await ProfileService(session).build(alias_id, recent_limit=0)

            if now_following:
                embed = runtime.embeds.success(
                    f"Following {profile.alias_display}",
                    "You'll get a DM when this anonymous profile posts again.",
                )
                embed.set_footer(
                    text="If they change their anonymous ID, the follow does not carry over."
                )
            else:
                embed = runtime.embeds.base(
                    title=f"Unfollowed {profile.alias_display}",
                    description="You will no longer receive updates from this profile.",
                )
            await respond(interaction, embed=embed)

        await guarded(interaction, "confession.follow", action)


class MoreConfessionButton(
    discord.ui.DynamicItem[discord.ui.Button], template=rf"cf:more:{CONFESSION_ID_PATTERN}"
):
    def __init__(self, confession_id: str):
        self.confession_id = confession_id
        super().__init__(_button("more", confession_id, label="More"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):  # noqa: D102
        return cls(match["cid"])

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.confession_service import ConfessionService
            from app.views.gate import ensure_ready
            from app.views.more_menu import MoreMenuView

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                service = ConfessionService(session, runtime.settings)
                confession = await service.get_visible(self.confession_id)
                guild_id = confession.guild_id
                view_data = await service.build_view(confession)
                is_author_pending = confession.internal_user_id

            actor = await ensure_ready(interaction, guild_id)
            if actor is None:
                return

            menu = MoreMenuView(
                confession_id=self.confession_id,
                guild_id=guild_id,
                internal_user_id=actor.internal_id,
                is_author=is_author_pending == actor.internal_id,
                view_data=view_data,
                settings=actor.settings,
            )
            await respond(
                interaction,
                embed=runtime.embeds.base(
                    title=f"Confession #{view_data.public_number}",
                    description="What would you like to do?",
                ),
                view=menu,
            )

        await guarded(interaction, "confession.more", action)


class ConfessionActionView(PersistentView):
    """The four-button row attached to every public confession."""

    def __init__(self, confession_id: str, *, settings=None):
        super().__init__()
        self.add_item(RateConfessionButton(confession_id))
        self.add_item(ProfileConfessionButton(confession_id))
        if settings is None or getattr(settings, "followers_enabled", True):
            self.add_item(FollowConfessionButton(confession_id))
        self.add_item(MoreConfessionButton(confession_id))


#: Registered at startup so clicks on old messages still resolve.
PERSISTENT_ITEMS = (
    RateConfessionButton,
    ProfileConfessionButton,
    FollowConfessionButton,
    MoreConfessionButton,
)
