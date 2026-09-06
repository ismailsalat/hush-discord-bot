"""Server selection for private Hush flows.

Normal-user slash commands live in Hush DMs.  They still act on one Discord
server, so this module discovers configured mutual servers and, only when
necessary, asks the user to choose one.

The discovery path deliberately does not rely solely on Hush's historical
``guild_memberships`` rows.  A brand-new member must be able to DM Hush before
ever running a server command.  For configured guilds we therefore use a
cached member when available and fall back to ``Guild.fetch_member`` (a REST
lookup that does not require the privileged members gateway intent).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

from app.views.common import HushView, PersistentView, guarded, respond, runtime_of

GuildAction = Callable[[discord.Interaction, int], Awaitable[None]]


async def mutual_guild_ids(interaction: discord.Interaction) -> list[int]:
    """Return configured guilds that both Hush and the caller belong to.

    Results are ordered with previously-used guilds first.  Successful member
    checks are written back to ``guild_memberships`` so future DM interactions
    are cheap.  A stale historical membership is re-verified before being
    offered, preventing users who left a server from continuing to post there.
    """
    runtime = runtime_of(interaction)
    from app.database.repositories import GuildRepository
    from app.services.user_service import UserService

    async with runtime.session() as session:
        users = UserService(session, runtime.settings)
        context = await users.resolve(interaction.user.id)
        known = await users.known_guild_ids(context.internal_id)
        configured_rows = await GuildRepository(session).list_configured()

    known_rank = {guild_id: index for index, guild_id in enumerate(known)}
    configured_ids = [row.guild_id for row in configured_rows]
    configured_ids.sort(key=lambda gid: (gid not in known_rank, known_rank.get(gid, 10**9)))

    mutual: list[int] = []
    verified: list[int] = []

    for guild_id in configured_ids:
        guild = interaction.client.get_guild(guild_id)
        if guild is None:
            continue

        member = guild.get_member(interaction.user.id)
        if member is None:
            try:
                member = await guild.fetch_member(interaction.user.id)
            except (discord.NotFound, discord.Forbidden):
                continue
            except discord.HTTPException:
                # Never authorize a DM post from stale membership data when
                # Discord could not verify that the user is still in the guild.
                continue

        mutual.append(guild_id)
        verified.append(guild_id)

    if verified:
        async with runtime.session() as session:
            users = UserService(session, runtime.settings)
            context = await users.resolve(interaction.user.id)
            for guild_id in verified:
                await users.remember_guild(context.internal_id, guild_id)

    return mutual


async def run_for_dm_guild(
    interaction: discord.Interaction,
    action: GuildAction,
    *,
    prompt: str = "Choose the server this should use.",
) -> None:
    """Run ``action`` for the caller's one configured mutual guild.

    If several are available, render a compact selector.  If none are
    available, give a useful setup message rather than the misleading old
    "No servers yet" result caused by passing a Discord ID where an internal
    Hush ID was expected.
    """
    runtime = runtime_of(interaction)
    guild_ids = await mutual_guild_ids(interaction)

    if len(guild_ids) == 1:
        await action(interaction, guild_ids[0])
        return

    if not guild_ids:
        await respond(
            interaction,
            embed=runtime.error_embeds.generic(
                "No Hush server available",
                (
                    "I couldn't find a server you share with Hush that has a confession "
                    "channel configured.\n\n"
                    "If you just added Hush, ask a server admin to run **/admin setup**."
                ),
            ),
        )
        return

    await respond(
        interaction,
        embed=runtime.embeds.base(title="Which server?", description=prompt),
        view=GuildActionPickerView(interaction.client, guild_ids, action=action),
    )


class GuildActionPickerView(HushView):
    """Reusable ephemeral guild picker for any DM-only user command."""

    def __init__(self, client: discord.Client, guild_ids: list[int], *, action: GuildAction):
        super().__init__(timeout=180)
        self.action = action

        options: list[discord.SelectOption] = []
        for guild_id in guild_ids[:25]:
            guild = client.get_guild(guild_id)
            options.append(
                discord.SelectOption(
                    label=(guild.name if guild else str(guild_id))[:100],
                    value=str(guild_id),
                )
            )

        self.select: discord.ui.Select = discord.ui.Select(
            placeholder="Choose a server",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.select.callback = self._chosen  # type: ignore[assignment]
        self.add_item(self.select)

    async def _chosen(self, interaction: discord.Interaction) -> None:
        guild_id = int(self.select.values[0])

        async def action() -> None:
            await self.action(interaction, guild_id)

        await guarded(interaction, "picker.choose_guild", action)


class GuildPickerView(HushView):
    """Backwards-compatible confession picker used by the DM home screen."""

    def __init__(self, client: discord.Client, guild_ids: list[int], *, origin=None):
        super().__init__(timeout=180)
        self.origin = origin

        options: list[discord.SelectOption] = []
        for guild_id in guild_ids[:25]:
            guild = client.get_guild(guild_id)
            options.append(
                discord.SelectOption(
                    label=(guild.name if guild else str(guild_id))[:100],
                    value=str(guild_id),
                )
            )
        self.select: discord.ui.Select = discord.ui.Select(
            placeholder="Choose a server", options=options, min_values=1, max_values=1
        )
        self.select.callback = self._chosen  # type: ignore[assignment]
        self.add_item(self.select)

    async def _chosen(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            guild_id = int(self.select.values[0])
            runtime = runtime_of(interaction)
            if self.origin is not None:
                self.origin.guild_id = guild_id

            guild = interaction.client.get_guild(guild_id)
            limit = runtime.settings.default_confession_limit
            async with runtime.session() as session:
                from app.database.repositories import GuildRepository

                settings = await GuildRepository(session).get_settings(guild_id)
                if settings:
                    limit = settings.confession_character_limit

            await respond(
                interaction,
                embed=runtime.agreement_embeds.submission_prompt(
                    limit, guild_name=guild.name if guild else None
                ),
                view=StartConfessionView(guild_id=guild_id, limit=limit),
                edit=True,
            )

        await guarded(interaction, "picker.choose_confession_guild", action)


class StartConfessionView(HushView):
    """Fresh interaction used to open the compose modal after a picker/gate."""

    def __init__(self, *, guild_id: int, limit: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.limit = limit

    @discord.ui.button(label="Write Confession", style=discord.ButtonStyle.primary)
    async def write(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.modals.confession import ConfessionModal

        await interaction.response.send_modal(
            ConfessionModal(guild_id=self.guild_id, limit=self.limit)
        )


class OpenDMView(PersistentView):
    """Optional in-server redirect surface kept for legacy/stale interactions."""

    def __init__(self, dm_url: str | None = None):
        super().__init__()
        if dm_url:
            self.add_item(
                discord.ui.Button(label="Open DM", url=dm_url, style=discord.ButtonStyle.link)
            )
