"""The private Hush home screen.

Normal users do everything from the one-to-one DM with Hush.  The view itself
never stores a user's server choice globally; that matters because persistent
views are re-registered after restarts and are shared across interactions.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

from app.views.common import PersistentView, guarded, respond, runtime_of

GuildAction = Callable[[discord.Interaction, int], Awaitable[None]]


class HomeView(PersistentView):
    def __init__(self, *, guild_id: int | None = None):
        super().__init__()
        # A guild id is only supplied for a short-lived flow that already chose
        # a guild (for example immediately after accepting rules).  The global
        # persistent HomeView is always created with None.
        self.guild_id = guild_id

    async def _run_for_guild(
        self,
        interaction: discord.Interaction,
        action: GuildAction,
        *,
        prompt: str,
    ) -> None:
        if self.guild_id is not None:
            await action(interaction, self.guild_id)
            return

        from app.views.picker import run_for_dm_guild

        await run_for_dm_guild(interaction, action, prompt=prompt)

    @discord.ui.button(
        label="New Confession",
        style=discord.ButtonStyle.primary,
        custom_id="cf:home:new",
    )
    async def new_confession(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        async def action(inner: discord.Interaction, guild_id: int) -> None:
            await start_confession(inner, guild_id)

        await guarded(
            interaction,
            "home.new_confession",
            lambda: self._run_for_guild(
                interaction,
                action,
                prompt="Choose where you want to post this confession.",
            ),
        )

    @discord.ui.button(
        label="My Profile",
        style=discord.ButtonStyle.secondary,
        custom_id="cf:home:profile",
    )
    async def my_profile(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        async def action(inner: discord.Interaction, guild_id: int) -> None:
            from app.services.profile_service import ProfileService
            from app.views.gate import ensure_ready
            from app.views.profile import ProfileView as ProfileUIView

            runtime = runtime_of(inner)
            actor = await ensure_ready(inner, guild_id)
            if actor is None:
                return

            async with runtime.session() as session:
                profile = await ProfileService(session).build_for_user(
                    actor.internal_id, guild_id
                )
            await respond(
                inner,
                embed=runtime.profile_embeds.build(profile, own_profile=True),
                view=ProfileUIView(
                    alias_id=profile.alias_id, guild_id=guild_id, own_profile=True
                ),
            )

        await guarded(
            interaction,
            "home.profile",
            lambda: self._run_for_guild(
                interaction,
                action,
                prompt="Choose which server's anonymous profile you want to view.",
            ),
        )

    @discord.ui.button(
        label="My Bookmarks",
        style=discord.ButtonStyle.secondary,
        custom_id="cf:home:bookmarks",
    )
    async def my_bookmarks(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        async def action(inner: discord.Interaction, guild_id: int) -> None:
            from app.services.bookmark_service import BookmarkService
            from app.utils.pagination import paginate
            from app.views.gate import ensure_ready

            runtime = runtime_of(inner)
            actor = await ensure_ready(inner, guild_id)
            if actor is None:
                return

            async with runtime.session() as session:
                rows = await BookmarkService(session).list_rows(
                    actor.internal_id, guild_id=guild_id
                )
            await respond(
                inner,
                embed=runtime.profile_embeds.bookmarks(paginate(rows, 0, 8)),
            )

        await guarded(
            interaction,
            "home.bookmarks",
            lambda: self._run_for_guild(
                interaction,
                action,
                prompt="Choose which server's bookmarks you want to view.",
            ),
        )


async def start_confession(
    interaction: discord.Interaction,
    guild_id: int,
) -> None:
    """Open the private confession flow for one already-resolved guild."""
    from app.modals.confession import ConfessionModal
    from app.views.gate import ensure_ready

    runtime = runtime_of(interaction)

    # Gate without deferring: when the user is already eligible, a modal must
    # be the first response to the interaction.
    actor = await ensure_ready(
        interaction,
        guild_id,
        require_agreement=True,
        defer=False,
    )
    if actor is None:
        return

    limit = getattr(
        actor.settings,
        "confession_character_limit",
        runtime.settings.default_confession_limit,
    )
    if interaction.response.is_done():
        # A prior gate/picker response consumed the initial interaction, so a
        # fresh button is required before Discord will allow a modal.
        from app.views.picker import StartConfessionView

        await respond(
            interaction,
            embed=runtime.agreement_embeds.submission_prompt(limit),
            view=StartConfessionView(guild_id=guild_id, limit=limit),
        )
    else:
        await interaction.response.send_modal(
            ConfessionModal(
                guild_id=guild_id,
                limit=limit,
                brand=runtime.settings.brand_name,
            )
        )
