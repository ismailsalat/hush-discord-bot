"""The /admin command group.

Guild-scoped administration: setup, settings, status, exports and backup
visibility. Anything global or destructive lives in `/owner` instead.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.base import HushCog
from app.core.constants import ExportFormat, ExportScope
from app.core.exceptions import ExportError, MissingChannelPermissionsError
from app.security.permissions import (
    CONFIG_LEVEL,
    GUILD_EXPORT_LEVEL,
    ROLE_CONFIG_LEVEL,
    STATUS_LEVEL,
)
from app.services.permission_service import requires, resolve_permission_level
from app.views.common import respond

#: Permissions Hush needs in a confession channel to work at all.
REQUIRED_CHANNEL_PERMISSIONS = ("view_channel", "send_messages", "embed_links")

#: Exports a guild admin may run. Full-database export is owner-only and lives
#: in the `/owner` group.
GUILD_EXPORT_SCOPES = (
    ExportScope.GUILD,
    ExportScope.USER,
    ExportScope.ALIAS,
    ExportScope.CONFESSION,
    ExportScope.MODERATION,
    ExportScope.REPORTS_ONLY,
)


def _maybe_int(value: str | None) -> int | None:
    """Pull an id out of a raw number or a `<@mention>`."""
    if not value:
        return None
    digits = "".join(character for character in value if character.isdigit())
    return int(digits) if digits else None


class AdminCog(HushCog):
    """`/admin` - setup, settings, status, export, backup."""

    group = app_commands.Group(
        name="admin",
        description="Configure Hush for this server.",
        guild_only=True,
    )

    async def _settings(self, guild: discord.Guild):
        from app.database.repositories import GuildRepository

        async with self.runtime.session() as session:
            return await GuildRepository(session).get_or_create_settings(
                guild.id, self.runtime.settings, name=guild.name
            )

    async def _update(self, guild_id: int, **values):
        from app.database.repositories import GuildRepository

        async with self.runtime.session() as session:
            return await GuildRepository(session).update_settings(guild_id, **values)

    # --- Setup --------------------------------------------------------------

    @group.command(name="setup", description="Set Hush up in this server.")
    @app_commands.describe(
        confession_channel="Where confessions are posted.",
        mod_log="Optional. Where moderation actions are logged.",
        admin_role="Optional. A role that may configure Hush.",
        moderator_role="Optional. A role that may moderate Hush.",
    )
    @requires(CONFIG_LEVEL, action="set Hush up")
    async def setup_command(
        self,
        interaction: discord.Interaction,
        confession_channel: discord.TextChannel,
        mod_log: discord.TextChannel | None = None,
        admin_role: discord.Role | None = None,
        moderator_role: discord.Role | None = None,
    ) -> None:
        """One command, everything optional except the channel.

        Deliberately not a multi-step wizard: an admin can be finished in a
        single message, and `/admin settings` covers everything else later.
        """
        runtime = self.runtime
        permissions = confession_channel.permissions_for(interaction.guild.me)
        missing = [
            name.replace("_", " ").title()
            for name in REQUIRED_CHANNEL_PERMISSIONS
            if not getattr(permissions, name)
        ]
        if missing:
            raise MissingChannelPermissionsError(
                channel_mention=confession_channel.mention, missing=missing
            )

        await self._settings(interaction.guild)
        values: dict[str, object] = {"confession_channel_id": confession_channel.id}
        if mod_log is not None:
            values["mod_log_channel_id"] = mod_log.id
        if admin_role is not None:
            values["admin_role_ids"] = [admin_role.id]
        if moderator_role is not None:
            values["moderator_role_ids"] = [moderator_role.id]
        await self._update(interaction.guild_id, **values)

        lines = [f"Confessions will be posted in {confession_channel.mention}."]
        if mod_log:
            lines.append(f"Moderation actions will be logged in {mod_log.mention}.")
        if admin_role:
            lines.append(f"{admin_role.mention} can configure Hush.")
        if moderator_role:
            lines.append(f"{moderator_role.mention} can moderate Hush.")
        lines.append("\nMembers can now DM Hush and use `/confess`.")

        await respond(
            interaction,
            embed=runtime.embeds.success("Hush is set up", "\n".join(lines)),
        )

    # --- Settings -----------------------------------------------------------

    @group.command(name="settings", description="View or change Hush settings.")
    @app_commands.describe(
        confession_channel="Where confessions are posted.",
        mod_log="Where moderation actions are logged.",
        character_limit="Confession length limit (100-4000).",
        alias_rotation_days="How often members may change their anonymous ID.",
        feature="A feature to turn on or off.",
        enabled="Whether that feature is on.",
        bump_rules="Ask everyone to accept the rules again.",
    )
    @app_commands.choices(
        alias_rotation_days=[
            app_commands.Choice(name="7 days", value=7),
            app_commands.Choice(name="14 days", value=14),
            app_commands.Choice(name="30 days", value=30),
        ],
        feature=[
            app_commands.Choice(name="Ratings", value="ratings_enabled"),
            app_commands.Choice(name="Followers", value="followers_enabled"),
            app_commands.Choice(name="Bookmarks", value="bookmarks_enabled"),
            app_commands.Choice(name="Polls", value="polls_enabled"),
            app_commands.Choice(name="Updates", value="updates_enabled"),
        ],
    )
    @requires(CONFIG_LEVEL, action="change Hush settings")
    async def settings_command(
        self,
        interaction: discord.Interaction,
        confession_channel: discord.TextChannel | None = None,
        mod_log: discord.TextChannel | None = None,
        character_limit: int | None = None,
        alias_rotation_days: app_commands.Choice[int] | None = None,
        feature: app_commands.Choice[str] | None = None,
        enabled: bool | None = None,
        bump_rules: bool = False,
    ) -> None:
        """With no options this shows current settings; with options it changes them."""
        runtime = self.runtime
        settings = await self._settings(interaction.guild)

        values: dict[str, object] = {}
        notes: list[str] = []

        if confession_channel is not None:
            values["confession_channel_id"] = confession_channel.id
            notes.append(f"Confession channel set to {confession_channel.mention}.")
        if mod_log is not None:
            values["mod_log_channel_id"] = mod_log.id
            notes.append(f"Mod log set to {mod_log.mention}.")
        if character_limit is not None:
            clamped = max(100, min(character_limit, 4000))
            values["confession_character_limit"] = clamped
            notes.append(f"Character limit set to {clamped:,}.")
        if alias_rotation_days is not None:
            values["alias_rotation_days"] = alias_rotation_days.value
            notes.append(f"Anonymous IDs may change every {alias_rotation_days.value} days.")
        if feature is not None:
            if enabled is None:
                raise ExportError(
                    "feature toggle without a value",
                    user_message="Choose `enabled: True` or `enabled: False` with a feature.",
                )
            values[feature.value] = enabled
            notes.append(f"{feature.name} {'enabled' if enabled else 'disabled'}.")
        if bump_rules:
            values["rules_version"] = settings.rules_version + 1
            notes.append(
                f"Rules bumped to version {settings.rules_version + 1}. "
                "Members will accept them once more before their next confession."
            )

        if values:
            settings = await self._update(interaction.guild_id, **values)
            await respond(
                interaction,
                embed=runtime.embeds.success("Settings updated", "\n".join(notes)),
            )
            return

        await respond(
            interaction,
            embed=runtime.admin_embeds.settings(settings, guild_name=interaction.guild.name),
        )

    @group.command(name="roles", description="Choose who can manage and moderate Hush.")
    @app_commands.describe(
        action="Grant or revoke.",
        level="Hush Admin or Hush Moderator.",
        role="A role to grant or revoke.",
        user="A specific user to grant or revoke.",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Grant", value="grant"),
            app_commands.Choice(name="Revoke", value="revoke"),
        ],
        level=[
            app_commands.Choice(name="Hush Admin", value="admin"),
            app_commands.Choice(name="Hush Moderator", value="moderator"),
        ],
    )
    @requires(ROLE_CONFIG_LEVEL, action="change who manages Hush")
    async def roles_command(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        level: app_commands.Choice[str],
        role: discord.Role | None = None,
        user: discord.User | None = None,
    ) -> None:
        """Server-owner only.

        Deciding who may moderate is a trust decision, so it sits one tier above
        ordinary configuration - a Hush Admin cannot quietly promote themselves.
        """
        runtime = self.runtime
        if role is None and user is None:
            raise ExportError(
                "no target given",
                user_message="Choose a role or a user to grant or revoke.",
            )

        settings = await self._settings(interaction.guild)
        role_field = f"{level.value}_role_ids"
        user_field = f"{level.value}_user_ids"

        values: dict[str, object] = {}
        notes: list[str] = []

        if role is not None:
            current = list(getattr(settings, role_field) or [])
            if action.value == "grant" and role.id not in current:
                current.append(role.id)
                notes.append(f"{role.mention} is now a **{level.name}** role.")
            elif action.value == "revoke" and role.id in current:
                current.remove(role.id)
                notes.append(f"{role.mention} is no longer a **{level.name}** role.")
            values[role_field] = current

        if user is not None:
            current = list(getattr(settings, user_field) or [])
            if action.value == "grant" and user.id not in current:
                current.append(user.id)
                notes.append(f"{user.mention} is now a **{level.name}**.")
            elif action.value == "revoke" and user.id in current:
                current.remove(user.id)
                notes.append(f"{user.mention} is no longer a **{level.name}**.")
            values[user_field] = current

        if values:
            await self._update(interaction.guild_id, **values)

        await respond(
            interaction,
            embed=runtime.embeds.success(
                "Hush roles updated", "\n".join(notes) or "Nothing changed."
            ),
        )

    # --- Status -------------------------------------------------------------

    @group.command(name="status", description="Check that Hush is healthy here.")
    @requires(STATUS_LEVEL, action="view Hush status")
    async def status(self, interaction: discord.Interaction) -> None:
        from app.database.repositories import NotificationRepository

        runtime = self.runtime
        settings = await self._settings(interaction.guild)
        report = await runtime.health.run()

        async with runtime.session() as session:
            pending = await NotificationRepository(session).count_pending()

        latest = await runtime.backups.list()
        if latest:
            from app.utils.time import ensure_utc, format_duration, utcnow

            age = utcnow() - (ensure_utc(latest[0].created_at) or utcnow())
            last_backup = f"{format_duration(age)} ago"
        else:
            last_backup = "never"

        await respond(
            interaction,
            embed=runtime.about_embeds.status(
                report=report,
                guild_count=len(self.bot.guilds),
                started_at=runtime.started_at,
                version=runtime.settings.version,
                channel_configured=bool(settings.confession_channel_id),
                mod_log_configured=bool(settings.mod_log_channel_id),
                pending_notifications=pending,
                errors_last_hour=runtime.error_counter.count_last_hour(),
                last_backup=last_backup,
            ),
        )

    # --- Export -------------------------------------------------------------

    @group.command(name="export", description="Export this server's Hush data.")
    @app_commands.describe(
        scope="What to export.",
        target="A user, anonymous ID or confession number, when the scope needs one.",
        export_format="File format.",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name=item.value.replace("_", " ").title(), value=item.value)
            for item in GUILD_EXPORT_SCOPES
        ],
        export_format=[
            app_commands.Choice(name="ZIP (everything)", value=ExportFormat.ZIP.value),
            app_commands.Choice(name="JSON", value=ExportFormat.JSON.value),
            app_commands.Choice(name="CSV", value=ExportFormat.CSV.value),
            app_commands.Choice(name="Text", value=ExportFormat.TXT.value),
        ],
    )
    @requires(GUILD_EXPORT_LEVEL, action="export server data")
    async def export(
        self,
        interaction: discord.Interaction,
        scope: app_commands.Choice[str],
        target: str | None = None,
        export_format: app_commands.Choice[str] | None = None,
    ) -> None:
        from app.services.export_service import ExportService

        runtime = self.runtime
        level = await resolve_permission_level(interaction)
        chosen = ExportScope(scope.value)

        async with runtime.session() as session:
            service = ExportService(session, runtime.settings)
            internal_user_id = alias_id = confession_id = None

            if chosen is ExportScope.USER and target:
                internal_user_id = await service.resolve_internal_user_id(
                    discord_user_id=_maybe_int(target),
                    internal_user_id=target if target.startswith("usr_") else None,
                    public_alias=target,
                    guild_id=interaction.guild_id,
                )
                if internal_user_id is None:
                    raise ExportError(
                        "unresolved export target",
                        user_message=f"Could not find anyone matching `{target}`.",
                    )
            elif chosen is ExportScope.ALIAS and target:
                from app.services.alias_service import AliasService

                found = await AliasService(
                    session,
                    default_rotation_days=runtime.settings.default_alias_rotation_days,
                ).find_public(interaction.guild_id, target)
                if found is None:
                    raise ExportError(
                        "unknown alias",
                        user_message=f"No anonymous ID matches `{target}` here.",
                    )
                alias_id = found.id
            elif chosen is ExportScope.CONFESSION and target:
                from app.services.confession_service import ConfessionService

                confession = await ConfessionService(
                    session, runtime.settings
                ).get_by_number(interaction.guild_id, _maybe_int(target) or 0)
                confession_id = confession.id

            result = await service.export(
                scope=chosen,
                actor_level=level,
                actor_id=interaction.user.id,
                export_format=ExportFormat(
                    export_format.value if export_format else ExportFormat.ZIP
                ),
                guild_id=interaction.guild_id,
                internal_user_id=internal_user_id,
                alias_id=alias_id,
                confession_id=confession_id,
            )

        # Always ephemeral: an export must never land in a public channel.
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

    # --- Backup visibility --------------------------------------------------

    @group.command(name="backup", description="See whether backups are healthy.")
    @requires(STATUS_LEVEL, action="view backup status")
    async def backup(self, interaction: discord.Interaction) -> None:
        """Read-only on purpose.

        Creating, verifying and restoring backups are system operations and live
        under `/owner backup`.
        """
        runtime = self.runtime
        ok, detail = await runtime.backups.status()
        records = await runtime.backups.list()

        embed = (
            runtime.embeds.success("Backups healthy", detail)
            if ok
            else runtime.embeds.warning("Backups need attention", detail)
        )
        embed.add_field(name="Stored backups", value=str(len(records)), inline=True)
        if records:
            embed.add_field(name="Most recent", value=records[0].name, inline=False)
        embed.set_footer(text="Creating and restoring backups is a bot-owner operation.")
        await respond(interaction, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
