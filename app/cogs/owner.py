"""The /owner command group.

Global and system-level operations, restricted to ``BOT_OWNER_IDS``. These are
the only commands that can touch every guild at once, read identities, or write
over production data, so they are separated from `/admin` entirely.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.base import HushCog
from app.core.constants import ExportFormat, ExportScope, PermissionLevel
from app.embeds.factory import subtext
from app.services.permission_service import owner_only, resolve_permission_level
from app.views.common import ConfirmView, respond


class OwnerCog(HushCog):
    """`/owner` - system status, global exports, backups, identity lookup."""

    group = app_commands.Group(
        name="owner",
        description="Hush system operations (bot owner only).",
    )

    @group.command(name="status", description="System-wide Hush status.")
    @owner_only()
    async def status(self, interaction: discord.Interaction) -> None:
        runtime = self.runtime
        report = await runtime.health.run()

        embed = runtime.admin_embeds.health(report)
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(
            name="Errors (1h)", value=str(runtime.error_counter.count_last_hour()), inline=True
        )
        embed.add_field(name="Version", value=f"v{runtime.settings.version}", inline=True)

        scheduler = getattr(self.bot, "scheduler", None)
        if scheduler is not None:
            embed.add_field(
                name="Background tasks",
                value="\n".join(
                    f"**{name}** {subtext(detail)}"
                    for name, detail in scheduler.status().items()
                )[:1024],
                inline=False,
            )
        await respond(interaction, embed=embed)

    @group.command(name="guilds", description="Servers Hush is in.")
    @owner_only()
    async def guilds(self, interaction: discord.Interaction) -> None:
        runtime = self.runtime
        from app.database.repositories import GuildRepository

        async with runtime.session() as session:
            configured = {
                settings.guild_id
                for settings in await GuildRepository(session).list_configured()
            }

        lines = [
            f"{'\u2705' if guild.id in configured else '\u2b1c'} **{guild.name}** "
            f"{subtext(f'{guild.member_count or 0:,} members')}"
            for guild in sorted(self.bot.guilds, key=lambda g: -(g.member_count or 0))[:25]
        ]
        embed = runtime.embeds.base(
            title=f"Servers ({len(self.bot.guilds)})",
            description="\n".join(lines) or "Not in any servers yet.",
        )
        embed.set_footer(text=f"{len(configured)} configured \u00b7 showing up to 25")
        await respond(interaction, embed=embed)

    @group.command(name="export", description="Export across every server.")
    @app_commands.describe(
        scope="What to export.", export_format="File format.",
        target="Internal user id, alias id or confession id, when the scope needs one.",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Full database", value=ExportScope.FULL.value),
            app_commands.Choice(name="Moderation", value=ExportScope.MODERATION.value),
            app_commands.Choice(name="Confessions only", value=ExportScope.CONFESSIONS_ONLY.value),
            app_commands.Choice(name="Reports only", value=ExportScope.REPORTS_ONLY.value),
            app_commands.Choice(name="User", value=ExportScope.USER.value),
        ],
        export_format=[
            app_commands.Choice(name="ZIP (everything)", value=ExportFormat.ZIP.value),
            app_commands.Choice(name="JSON", value=ExportFormat.JSON.value),
            app_commands.Choice(name="CSV", value=ExportFormat.CSV.value),
        ],
    )
    @owner_only()
    async def export(
        self,
        interaction: discord.Interaction,
        scope: app_commands.Choice[str],
        export_format: app_commands.Choice[str] | None = None,
        target: str | None = None,
    ) -> None:
        from app.services.export_service import ExportService

        runtime = self.runtime
        level = await resolve_permission_level(interaction)

        async with runtime.session() as session:
            result = await ExportService(session, runtime.settings).export(
                scope=ExportScope(scope.value),
                actor_level=level,
                actor_id=interaction.user.id,
                export_format=ExportFormat(
                    export_format.value if export_format else ExportFormat.ZIP
                ),
                guild_id=interaction.guild_id,
                internal_user_id=target if target and target.startswith("usr_") else None,
                alias_id=target if target and target.startswith("ali_") else None,
                confession_id=target if target and target.startswith("conf_") else None,
            )

        await respond(
            interaction,
            embed=runtime.admin_embeds.export_ready(
                filename=result.filename,
                size_bytes=result.size_bytes,
                row_counts=result.row_counts,
                redacted=result.redacted,
            ),
        )
        await interaction.followup.send(
            file=discord.File(result.path, filename=result.filename), ephemeral=True
        )

    @group.command(name="backup", description="Create, list or verify backups.")
    @app_commands.describe(action="What to do.", name="Backup filename, for verify.")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Create and verify", value="create"),
            app_commands.Choice(name="List", value="list"),
            app_commands.Choice(name="Verify", value="verify"),
            app_commands.Choice(name="Restore test (safe)", value="restore_test"),
        ]
    )
    @owner_only()
    async def backup(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        name: str | None = None,
    ) -> None:
        """Note there is no "restore" action here.

        A real restore overwrites production, so it is intentionally not a slash
        command. It is a documented, deliberate host operation - see
        `docs/backup_restore.md`. ``restore_test`` only ever writes to a
        temporary file.
        """
        runtime = self.runtime

        if action.value == "list":
            await respond(
                interaction, embed=runtime.admin_embeds.backup_list(await runtime.backups.list())
            )
            return

        if action.value == "create":
            confirm = ConfirmView(confirm_label="Create backup", danger=False)
            await respond(
                interaction,
                embed=runtime.embeds.warning(
                    "Create a backup now?",
                    "This snapshots the database and verifies it can be restored.",
                ),
                view=confirm,
            )
            await confirm.wait()
            if not confirm.value or confirm.interaction is None:
                return

            await confirm.interaction.response.defer(ephemeral=True)
            record, report = await runtime.backups.create_and_verify("manual")
            embed = runtime.admin_embeds.backup_verification(report)
            embed.title = f"Backup created \u00b7 {record.size_display}"
            await confirm.interaction.followup.send(embed=embed, ephemeral=True)
            return

        if not name:
            await respond(
                interaction,
                embed=runtime.error_embeds.generic(
                    "Which backup?", "Pass `name` with the backup filename."
                ),
            )
            return

        report = await runtime.backups.verify(name)
        embed = runtime.admin_embeds.backup_verification(report)
        if action.value == "restore_test":
            restored, detail = await runtime.backups.restore_test(name)
            embed.add_field(
                name="Restore test",
                value=f"{'\u2705' if restored else '\u274c'} {detail}",
                inline=False,
            )
            embed.set_footer(text="Restored into a temporary file. Production was not touched.")
        await respond(interaction, embed=embed)

    @group.command(name="identity", description="Reveal who is behind an anonymous ID.")
    @app_commands.describe(
        anon_id="The anonymous ID, e.g. A17.", reason="Why this lookup is necessary."
    )
    @owner_only()
    async def identity(
        self, interaction: discord.Interaction, anon_id: str, reason: str
    ) -> None:
        """The single path from an alias to a person. Always logged, always audited."""
        from app.core.exceptions import GuildOnlyError
        from app.services.identity_service import IdentityService

        if interaction.guild_id is None:
            raise GuildOnlyError()

        runtime = self.runtime
        async with runtime.session() as session:
            result = await IdentityService(session).lookup(
                actor_level=PermissionLevel.BOT_OWNER,
                actor_id=interaction.user.id,
                guild_id=interaction.guild_id,
                public_alias=anon_id,
                reason=reason,
            )

        embed = runtime.embeds.warning(
            "Identity lookup",
            f"`{anon_id}` is <@{result.discord_user_id}> (`{result.discord_user_id}`).",
        )
        embed.add_field(name="Reason given", value=reason, inline=False)
        embed.set_footer(text="This lookup is recorded in the moderation ledger.")
        await respond(interaction, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OwnerCog(bot))
