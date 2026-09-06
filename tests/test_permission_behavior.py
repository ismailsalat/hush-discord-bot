"""End-to-end permission behaviour.

Rather than asserting on the decorator's metadata, these tests actually invoke
command callbacks as each tier of user and check who gets through. A fake
interaction stands in for Discord.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.config.settings import Settings
from app.core.constants import PermissionLevel
from app.core.exceptions import GuildOnlyError, PermissionDeniedError
from app.core.runtime import Runtime
from app.database.repositories import GuildRepository
from app.database.session import Database
from app.services.permission_service import resolve_permission_level
from tests.conftest import GUILD_ID

BOT_OWNER_ID = 111_111_111_111_111_111
SERVER_OWNER_ID = 222_222_222_222_222_222
HUSH_ADMIN_ID = 333_333_333_333_333_333
HUSH_MOD_ID = 444_444_444_444_444_444
NORMAL_USER_ID = 555_555_555_555_555_555

ADMIN_ROLE_ID = 900_001
MOD_ROLE_ID = 900_002


class FakeResponse:
    def __init__(self):
        self.deferred = False

    def is_done(self) -> bool:
        return self.deferred

    async def defer(self, **_kwargs) -> None:
        self.deferred = True


class FakeFollowup:
    """Captures what a permitted command sends, so tests can assert on it."""

    def __init__(self):
        self.messages: list[dict] = []

    async def send(self, **kwargs) -> None:
        self.messages.append(kwargs)


class FakeInteraction:
    """The smallest thing that behaves like an interaction for permissions."""

    def __init__(self, runtime, *, user_id: int, role_ids=(), is_admin=False,
                 guild_id: int | None = GUILD_ID):
        self.guild_id = guild_id
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.client = SimpleNamespace(runtime=runtime)
        self.user = SimpleNamespace(
            id=user_id,
            roles=[SimpleNamespace(id=role_id) for role_id in role_ids],
            guild_permissions=SimpleNamespace(administrator=is_admin),
        )
        self.guild = (
            SimpleNamespace(id=guild_id, name="Test Server", owner_id=SERVER_OWNER_ID)
            if guild_id
            else None
        )


@pytest_asyncio.fixture
async def runtime(tmp_path):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        discord_token="x",
        bot_owner_ids=[BOT_OWNER_ID],
        backup_directory=tmp_path / "b",
        export_directory=tmp_path / "e",
        log_directory=tmp_path / "l",
    )
    database = Database(settings.database_url)
    await database.create_all()

    async with database.session() as session:
        guilds = GuildRepository(session)
        await guilds.get_or_create_settings(GUILD_ID, settings, name="Test Server")
        await guilds.update_settings(
            GUILD_ID,
            confession_channel_id=555,
            admin_role_ids=[ADMIN_ROLE_ID],
            moderator_role_ids=[MOD_ROLE_ID],
        )

    instance = Runtime(settings, database)
    try:
        yield instance
    finally:
        await database.dispose()


async def level_of(runtime, **kwargs) -> PermissionLevel:
    return await resolve_permission_level(FakeInteraction(runtime, **kwargs))


class TestTierResolution:
    async def test_normal_user(self, runtime):
        assert await level_of(runtime, user_id=NORMAL_USER_ID) is PermissionLevel.USER

    async def test_hush_moderator_via_role(self, runtime):
        level = await level_of(runtime, user_id=HUSH_MOD_ID, role_ids=[MOD_ROLE_ID])
        assert level is PermissionLevel.MODERATOR

    async def test_hush_admin_via_role_without_discord_admin(self, runtime):
        """The delegation case: trusted with Hush, not with the server."""
        level = await level_of(
            runtime, user_id=HUSH_ADMIN_ID, role_ids=[ADMIN_ROLE_ID], is_admin=False
        )
        assert level is PermissionLevel.ADMIN

    async def test_server_owner(self, runtime):
        assert await level_of(runtime, user_id=SERVER_OWNER_ID) is PermissionLevel.SERVER_OWNER

    async def test_bot_owner(self, runtime):
        assert await level_of(runtime, user_id=BOT_OWNER_ID) is PermissionLevel.BOT_OWNER

    async def test_bot_owner_is_recognised_in_dms(self, runtime):
        level = await level_of(runtime, user_id=BOT_OWNER_ID, guild_id=None)
        assert level is PermissionLevel.BOT_OWNER

    async def test_normal_user_gains_nothing_in_dms(self, runtime):
        level = await level_of(runtime, user_id=NORMAL_USER_ID, guild_id=None)
        assert level is PermissionLevel.USER


class TestCommandAccess:
    """Invoke real command callbacks and check who is refused."""

    @staticmethod
    async def call(cog_class, runtime, command_name: str, **who):
        cog = cog_class.__new__(cog_class)
        cog.bot = SimpleNamespace(runtime=runtime, guilds=[])
        interaction = FakeInteraction(runtime, **who)
        callback = getattr(cog_class, command_name).callback
        await callback(cog, interaction)
        return interaction

    async def test_normal_user_cannot_use_mod(self, runtime):
        from app.cogs.moderation import ModerationCog

        with pytest.raises(PermissionDeniedError):
            await self.call(ModerationCog, runtime, "reports", user_id=NORMAL_USER_ID)

    async def test_normal_user_cannot_use_admin(self, runtime):
        from app.cogs.admin import AdminCog

        with pytest.raises(PermissionDeniedError):
            await self.call(AdminCog, runtime, "status", user_id=NORMAL_USER_ID)

    async def test_normal_user_cannot_use_owner(self, runtime):
        from app.cogs.owner import OwnerCog

        with pytest.raises(PermissionDeniedError):
            await self.call(OwnerCog, runtime, "guilds", user_id=NORMAL_USER_ID)

    async def test_moderator_may_review_reports(self, runtime):
        from app.cogs.moderation import ModerationCog

        interaction = await self.call(
            ModerationCog, runtime, "reports", user_id=HUSH_MOD_ID, role_ids=[MOD_ROLE_ID]
        )
        # The gate let them through and they actually got the report queue.
        assert interaction.followup.messages

    async def test_moderator_cannot_change_settings(self, runtime):
        from app.cogs.admin import AdminCog

        with pytest.raises(PermissionDeniedError):
            await self.call(
                AdminCog, runtime, "status", user_id=HUSH_MOD_ID, role_ids=[MOD_ROLE_ID]
            )

    async def test_moderator_cannot_use_owner_commands(self, runtime):
        from app.cogs.owner import OwnerCog

        with pytest.raises(PermissionDeniedError):
            await self.call(
                OwnerCog, runtime, "guilds", user_id=HUSH_MOD_ID, role_ids=[MOD_ROLE_ID]
            )

    async def test_hush_admin_may_view_status(self, runtime):
        from app.cogs.admin import AdminCog

        interaction = await self.call(
            AdminCog, runtime, "status", user_id=HUSH_ADMIN_ID, role_ids=[ADMIN_ROLE_ID]
        )
        assert interaction.followup.messages

    async def test_hush_admin_may_moderate(self, runtime):
        from app.cogs.moderation import ModerationCog

        interaction = await self.call(
            ModerationCog, runtime, "reports", user_id=HUSH_ADMIN_ID, role_ids=[ADMIN_ROLE_ID]
        )
        assert interaction.followup.messages

    async def test_hush_admin_cannot_change_who_moderates(self, runtime):
        """A Hush Admin must not be able to promote themselves or others."""
        from app.cogs.admin import AdminCog

        cog = AdminCog.__new__(AdminCog)
        cog.bot = SimpleNamespace(runtime=runtime, guilds=[])
        interaction = FakeInteraction(
            runtime, user_id=HUSH_ADMIN_ID, role_ids=[ADMIN_ROLE_ID]
        )
        with pytest.raises(PermissionDeniedError):
            await AdminCog.roles_command.callback(
                cog, interaction,
                action=SimpleNamespace(value="grant", name="Grant"),
                level=SimpleNamespace(value="admin", name="Hush Admin"),
                role=None, user=None,
            )

    async def test_hush_admin_cannot_use_owner_commands(self, runtime):
        from app.cogs.owner import OwnerCog

        with pytest.raises(PermissionDeniedError):
            await self.call(
                OwnerCog, runtime, "guilds", user_id=HUSH_ADMIN_ID, role_ids=[ADMIN_ROLE_ID]
            )

    async def test_server_owner_may_configure_roles(self, runtime):
        from app.cogs.admin import AdminCog

        cog = AdminCog.__new__(AdminCog)
        cog.bot = SimpleNamespace(runtime=runtime, guilds=[])
        interaction = FakeInteraction(runtime, user_id=SERVER_OWNER_ID)
        await AdminCog.roles_command.callback(
            cog, interaction,
            action=SimpleNamespace(value="grant", name="Grant"),
            level=SimpleNamespace(value="moderator", name="Hush Moderator"),
            role=SimpleNamespace(id=777, mention="<@&777>"), user=None,
        )

        async with runtime.session() as session:
            settings = await GuildRepository(session).get_settings(GUILD_ID)
        assert 777 in settings.moderator_role_ids

    async def test_server_owner_cannot_use_owner_commands(self, runtime):
        from app.cogs.owner import OwnerCog

        with pytest.raises(PermissionDeniedError):
            await self.call(OwnerCog, runtime, "guilds", user_id=SERVER_OWNER_ID)

    async def test_bot_owner_may_use_owner_commands(self, runtime):
        from app.cogs.owner import OwnerCog

        interaction = await self.call(OwnerCog, runtime, "guilds", user_id=BOT_OWNER_ID)
        assert interaction.followup.messages

    async def test_guild_commands_refuse_dms(self, runtime):
        from app.cogs.admin import AdminCog

        with pytest.raises(GuildOnlyError):
            await self.call(
                AdminCog, runtime, "status", user_id=BOT_OWNER_ID, guild_id=None
            )


class TestDeniedMessage:
    def test_denial_names_the_required_level(self):
        from app.security.permissions import require

        with pytest.raises(PermissionDeniedError) as caught:
            require(PermissionLevel.USER, PermissionLevel.ADMIN, action="do that")
        message = caught.value.user_message
        assert "Hush Admin" in message
        assert "Member" in message
