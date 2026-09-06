"""Command surface, About page and startup configuration.

These tests assemble the real bot (without connecting to Discord) so the
registered command tree, the permission decorators and the persistent view
registry are all exercised as they will be in production.
"""

from __future__ import annotations

from datetime import timedelta

import discord
import pytest
import pytest_asyncio

from app.__version__ import __version__
from app.bot import HushBot, build_intents
from app.config.settings import Settings
from app.core.constants import PermissionLevel
from app.database.session import Database
from app.utils.time import utcnow

#: The exact command surface agreed for Hush.
EXPECTED_TOP_LEVEL = {
    "confess",
    "profile",
    "bookmarks",
    "following",
    "trending",
    "halloffame",
    "about",
    "mod",
    "admin",
    "owner",
}
EXPECTED_MOD = {"warn", "ban", "unban", "history", "reports", "review"}
EXPECTED_ADMIN = {"setup", "settings", "status", "export", "backup", "roles"}
EXPECTED_OWNER = {"status", "export", "backup", "guilds", "identity"}


@pytest_asyncio.fixture
async def bot(tmp_path):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        discord_token="test-token",
        bot_owner_ids=[1],
        backup_directory=tmp_path / "backups",
        export_directory=tmp_path / "exports",
        log_directory=tmp_path / "logs",
    )
    database = Database(settings.database_url)
    await database.create_all()
    instance = HushBot(settings, database)
    await instance.setup_hook()
    try:
        yield instance
    finally:
        await instance.close()


def subcommands(bot: HushBot, name: str) -> set[str]:
    group = bot.tree.get_command(name)
    assert isinstance(group, discord.app_commands.Group), f"/{name} should be a group"
    return {command.name for command in group.commands}


class TestCommandSurface:
    async def test_top_level_commands_are_exactly_as_agreed(self, bot):
        assert {command.name for command in bot.tree.get_commands()} == EXPECTED_TOP_LEVEL

    async def test_command_list_stays_small(self, bot):
        """Seven flat commands plus three groups - not a wall of slash commands."""
        flat = [
            command
            for command in bot.tree.get_commands()
            if not isinstance(command, discord.app_commands.Group)
        ]
        assert len(flat) == 7

    async def test_moderation_is_grouped(self, bot):
        assert subcommands(bot, "mod") == EXPECTED_MOD

    async def test_administration_is_grouped(self, bot):
        assert subcommands(bot, "admin") == EXPECTED_ADMIN

    async def test_owner_operations_are_grouped(self, bot):
        assert subcommands(bot, "owner") == EXPECTED_OWNER

    async def test_no_ugly_flattened_names(self, bot):
        """Guards against /hush_admin_database_export_user_json style creep."""
        for command in bot.tree.walk_commands():
            assert "_" not in command.name, f"{command.name} should use a group"
            assert len(command.name) <= 12, f"{command.name} is too long to type"

    async def test_no_debug_commands_are_exposed(self, bot):
        forbidden = {"debug", "eval", "exec", "sync", "reload", "shutdown", "sql", "test"}
        assert not forbidden & {command.name for command in bot.tree.walk_commands()}

    async def test_privileged_groups_use_hush_permission_layer(self, bot):
        """Custom Hush roles/users must not be hidden by Discord native permissions.

        Discord ``default_permissions`` cannot represent Hush's per-guild custom
        moderator/admin assignments or bot-owner IDs.  Leave the groups visible
        and enforce access through the centralized Hush permission decorators.
        """
        for name in ("mod", "admin", "owner"):
            group = bot.tree.get_command(name)
            assert group.default_permissions is None
            for command in group.commands:
                assert getattr(command.callback, "__hush_required_level__", None) is not None

    async def test_user_commands_need_no_special_permissions(self, bot):
        for name in ("confess", "profile", "bookmarks", "following", "trending",
                     "halloffame", "about"):
            command = bot.tree.get_command(name)
            assert command.default_permissions is None


class TestPermissionDecorators:
    async def test_every_mod_and_admin_command_declares_a_level(self, bot):
        for group_name in ("mod", "admin", "owner"):
            group = bot.tree.get_command(group_name)
            for command in group.commands:
                level = getattr(command.callback, "__hush_required_level__", None)
                assert level is not None, f"/{group_name} {command.name} has no permission gate"

    async def test_mod_commands_require_moderator_or_higher(self, bot):
        group = bot.tree.get_command("mod")
        for command in group.commands:
            level = command.callback.__hush_required_level__
            assert level.meets(PermissionLevel.MODERATOR)

    async def test_owner_commands_require_bot_owner(self, bot):
        group = bot.tree.get_command("owner")
        for command in group.commands:
            assert command.callback.__hush_required_level__ is PermissionLevel.BOT_OWNER

    async def test_changing_who_moderates_needs_the_server_owner(self, bot):
        roles = next(c for c in bot.tree.get_command("admin").commands if c.name == "roles")
        assert roles.callback.__hush_required_level__ is PermissionLevel.SERVER_OWNER


class TestPersistentViews:
    async def test_every_persistent_custom_id_resolves_after_restart(self, bot):
        from app.lifecycle import register_persistent_views
        from app.views.confession import ConfessionActionView
        from app.views.polls import PollView

        register_persistent_views(bot)
        templates = bot._connection._view_store._dynamic_items

        ids = [child.item.custom_id for child in ConfessionActionView("conf_abc123def4").children]
        ids += [child.item.custom_id for child in PollView("pol_abc123", ["a", "b"]).children]
        ids += [
            "cf:agree:123456789012345678:1",
            "cf:agreecancel:123456789012345678",
            "cf:ack:ntf_abcdef0123456789",
        ]
        for custom_id in ids:
            assert any(pattern.fullmatch(custom_id) for pattern in templates), custom_id

    async def test_no_custom_id_leaks_an_identity(self, bot):
        from app.views.confession import ConfessionActionView

        for child in ConfessionActionView("conf_abc123def4").children:
            assert "usr_" not in child.item.custom_id


class TestIntents:
    def test_no_privileged_intents_are_requested(self):
        intents = build_intents()
        assert not intents.message_content
        assert not intents.members
        assert not intents.presences

    def test_only_what_is_needed_is_requested(self):
        intents = build_intents()
        assert intents.guilds and intents.guild_messages and intents.dm_messages


class TestAboutPage:
    def test_about_uses_live_values(self):
        from app.embeds.about import AboutEmbedBuilder
        from app.embeds.factory import EmbedFactory

        builder = AboutEmbedBuilder(EmbedFactory(Settings()))
        embed = builder.about(
            version=__version__,
            guild_count=42,
            started_at=utcnow() - timedelta(days=4, hours=7),
        )
        fields = {field.name: field.value for field in embed.fields}
        assert fields["Version"] == f"v{__version__}"
        assert fields["Servers"] == "42"
        assert fields["Uptime"].startswith("4d")
        assert fields["Status"] == "Online"

    def test_about_reports_degraded_status_honestly(self):
        from app.embeds.about import AboutEmbedBuilder
        from app.embeds.factory import EmbedFactory

        builder = AboutEmbedBuilder(EmbedFactory(Settings()))
        embed = builder.about(
            version=__version__, guild_count=1, started_at=utcnow(), healthy=False
        )
        assert {f.name: f.value for f in embed.fields}["Status"] == "Degraded"

    def test_privacy_wording_is_honest(self):
        from app.embeds.about import AboutEmbedBuilder
        from app.embeds.factory import EmbedFactory

        builder = AboutEmbedBuilder(EmbedFactory(Settings()))
        embed = builder.about(version="1.0.0", guild_count=1, started_at=utcnow())
        privacy = {f.name: f.value for f in embed.fields}["Privacy"]
        assert "Anonymous to regular server members" in privacy
        assert "untraceable" not in privacy.lower()
        assert "completely anonymous" not in privacy.lower()

    def test_no_buttons_when_no_links_configured(self):
        from app.embeds.about import link_view

        assert link_view(Settings().links) is None

    def test_buttons_appear_only_for_configured_links(self):
        from app.embeds.about import link_view

        settings = Settings(
            support_server_url="https://discord.gg/example",
            github_url="   ",
            terms_url="not-a-url",
            privacy_policy_url="https://example.com/privacy",
        )
        view = link_view(settings.links)
        assert {child.label for child in view.children} == {"Support", "Privacy"}

    def test_version_comes_from_one_place(self):
        assert Settings().version == __version__
        assert Settings(hush_version="9.9.9").version == "9.9.9"


class TestStartupValidation:
    def test_missing_token_is_reported(self):
        problems = Settings(discord_token="", bot_owner_ids=[1]).validate_for_startup()
        assert any("DISCORD_TOKEN" in problem for problem in problems)

    def test_missing_owners_is_reported(self):
        problems = Settings(discord_token="x", bot_owner_ids=[]).validate_for_startup()
        assert any("BOT_OWNER_IDS" in problem for problem in problems)

    def test_production_refuses_sqlite(self):
        problems = Settings(
            discord_token="x", bot_owner_ids=[1], environment="production",
            database_url="sqlite+aiosqlite:///./hush.sqlite3",
        ).validate_for_startup()
        assert any("SQLite" in problem for problem in problems)

    def test_good_configuration_has_no_problems(self):
        problems = Settings(
            discord_token="x", bot_owner_ids=[1], environment="production",
            database_url="postgresql+asyncpg://u:p@host:5432/hush",
        ).validate_for_startup()
        assert problems == []

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("", []),
            ("   ", []),
            ("111,222", [111, 222]),
            ("111, 222 ", [111, 222]),
            ("[111, 222]", [111, 222]),
            ("garbage", []),
        ],
    )
    def test_owner_ids_parse_from_a_single_variable(self, raw, expected):
        assert Settings(bot_owner_ids=raw).bot_owner_ids == expected

    def test_token_is_never_in_a_logged_dump(self):
        dump = Settings(discord_token="super-secret-token").safe_dump()
        assert "discord_token" not in dump
        assert "super-secret-token" not in str(dump)

    def test_database_credentials_are_redacted(self):
        dump = Settings(
            database_url="postgresql+asyncpg://user:hunter2@host:5432/hush"
        ).safe_dump()
        assert "hunter2" not in str(dump)
