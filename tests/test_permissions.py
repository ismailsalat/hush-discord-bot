"""Permission tiers and the privileged identity path."""

from __future__ import annotations

import pytest

from app.core.constants import PermissionLevel
from app.core.exceptions import PermissionDeniedError
from app.security.permissions import (
    BACKUP_LEVEL,
    CONFIG_LEVEL,
    FULL_EXPORT_LEVEL,
    GUILD_EXPORT_LEVEL,
    IDENTITY_LOOKUP_LEVEL,
    MODERATION_LEVEL,
    ROLE_CONFIG_LEVEL,
    GuildRoleConfig,
    MemberContext,
    can_access_sensitive_identity,
    can_configure_roles,
    can_manage_server,
    can_moderate,
    require,
    resolve_level,
)
from app.services.identity_service import IdentityService
from tests.conftest import GUILD_ID

MOD_ROLE = 111
ADMIN_ROLE = 333
OTHER_ROLE = 222
OWNER_DISCORD_ID = 1


def level_for(member: MemberContext, *, config=None, owner_ids=(OWNER_DISCORD_ID,)):
    return resolve_level(member, owner_ids=owner_ids, guild_config=config or GuildRoleConfig())


def context(**overrides) -> MemberContext:
    base = dict(
        user_id=5000,
        role_ids=frozenset(),
        is_guild_admin=False,
        is_guild_owner=False,
    )
    base.update(overrides)
    return MemberContext(**base)


class TestTiers:
    def test_plain_member_is_a_user(self):
        assert level_for(context()) is PermissionLevel.USER

    def test_configured_moderator_role_grants_moderator(self):
        config = GuildRoleConfig(moderator_role_ids=frozenset({MOD_ROLE}))
        assert level_for(context(role_ids=frozenset({MOD_ROLE})), config=config) is (
            PermissionLevel.MODERATOR
        )

    def test_configured_moderator_user_grants_moderator(self):
        """A small server can trust one person without creating a role."""
        config = GuildRoleConfig(moderator_user_ids=frozenset({5000}))
        assert level_for(context(), config=config) is PermissionLevel.MODERATOR

    def test_configured_admin_role_grants_admin(self):
        config = GuildRoleConfig(admin_role_ids=frozenset({ADMIN_ROLE}))
        assert level_for(context(role_ids=frozenset({ADMIN_ROLE})), config=config) is (
            PermissionLevel.ADMIN
        )

    def test_configured_admin_user_grants_admin(self):
        config = GuildRoleConfig(admin_user_ids=frozenset({5000}))
        assert level_for(context(), config=config) is PermissionLevel.ADMIN

    def test_hush_admin_needs_no_discord_administrator(self):
        """The point of the tier: delegation without handing over the server."""
        config = GuildRoleConfig(admin_role_ids=frozenset({ADMIN_ROLE}))
        member = context(role_ids=frozenset({ADMIN_ROLE}), is_guild_admin=False)
        assert level_for(member, config=config) is PermissionLevel.ADMIN

    def test_unrelated_role_grants_nothing(self):
        config = GuildRoleConfig(moderator_role_ids=frozenset({MOD_ROLE}))
        assert level_for(context(role_ids=frozenset({OTHER_ROLE})), config=config) is (
            PermissionLevel.USER
        )

    def test_discord_administrator_is_treated_as_hush_admin(self):
        assert level_for(context(is_guild_admin=True)) is PermissionLevel.ADMIN

    def test_guild_owner_outranks_admins(self):
        assert level_for(context(is_guild_owner=True)) is PermissionLevel.SERVER_OWNER

    def test_bot_owner_outranks_everyone(self):
        member = context(user_id=OWNER_DISCORD_ID, is_guild_owner=True)
        assert level_for(member) is PermissionLevel.BOT_OWNER

    def test_owner_ids_come_from_configuration_only(self):
        """Nothing is special-cased in code - remove the id, lose the tier."""
        assert level_for(context(user_id=OWNER_DISCORD_ID), owner_ids=()) is (
            PermissionLevel.USER
        )


class TestOrdering:
    def test_levels_are_ordered(self):
        ranks = [
            PermissionLevel.USER,
            PermissionLevel.MODERATOR,
            PermissionLevel.ADMIN,
            PermissionLevel.SERVER_OWNER,
            PermissionLevel.BOT_OWNER,
        ]
        assert [level.rank for level in ranks] == sorted(level.rank for level in ranks)

    def test_every_level_has_a_human_label(self):
        assert PermissionLevel.MODERATOR.label == "Hush Moderator"
        assert PermissionLevel.ADMIN.label == "Hush Admin"
        assert PermissionLevel.BOT_OWNER.label == "Bot Owner"

    def test_meets_is_inclusive(self):
        assert PermissionLevel.ADMIN.meets(PermissionLevel.MODERATOR)
        assert PermissionLevel.ADMIN.meets(PermissionLevel.ADMIN)
        assert not PermissionLevel.MODERATOR.meets(PermissionLevel.ADMIN)

    def test_require_raises_when_short(self):
        with pytest.raises(PermissionDeniedError):
            require(PermissionLevel.MODERATOR, PermissionLevel.ADMIN)

    def test_require_passes_when_sufficient(self):
        require(PermissionLevel.BOT_OWNER, PermissionLevel.ADMIN)


class TestCapabilities:
    """Commands ask for a capability, not a tier."""

    def test_moderator_can_moderate_but_not_configure(self):
        assert can_moderate(PermissionLevel.MODERATOR)
        assert not can_manage_server(PermissionLevel.MODERATOR)

    def test_admin_can_configure_and_moderate(self):
        assert can_manage_server(PermissionLevel.ADMIN)
        assert can_moderate(PermissionLevel.ADMIN)

    def test_admin_cannot_change_who_moderates(self):
        """Only the server owner decides who is trusted."""
        assert not can_configure_roles(PermissionLevel.ADMIN)
        assert can_configure_roles(PermissionLevel.SERVER_OWNER)

    def test_server_owner_cannot_do_system_operations(self):
        assert not can_access_sensitive_identity(PermissionLevel.SERVER_OWNER)
        assert not PermissionLevel.SERVER_OWNER.meets(BACKUP_LEVEL)
        assert not PermissionLevel.SERVER_OWNER.meets(FULL_EXPORT_LEVEL)

    def test_normal_user_can_do_none_of_it(self):
        for capability in (can_moderate, can_manage_server, can_configure_roles,
                           can_access_sensitive_identity):
            assert not capability(PermissionLevel.USER)


class TestPrivilegedLevels:
    def test_identity_lookup_is_bot_owner_only(self):
        assert IDENTITY_LOOKUP_LEVEL is PermissionLevel.BOT_OWNER

    def test_moderation_and_config_tiers(self):
        assert MODERATION_LEVEL is PermissionLevel.MODERATOR
        assert CONFIG_LEVEL is PermissionLevel.ADMIN
        assert ROLE_CONFIG_LEVEL is PermissionLevel.SERVER_OWNER

    def test_full_export_is_owner_only(self):
        assert FULL_EXPORT_LEVEL is PermissionLevel.BOT_OWNER

    def test_guild_export_needs_admin(self):
        assert GUILD_EXPORT_LEVEL is PermissionLevel.ADMIN


class TestIdentityLookup:
    async def test_lookup_returns_the_discord_id(self, session, factory):
        user, alias = await factory.member(discord_id=123456789012345678)
        result = await IdentityService(session).lookup(
            actor_level=PermissionLevel.BOT_OWNER,
            actor_id=OWNER_DISCORD_ID,
            guild_id=GUILD_ID,
            public_alias=alias.public_alias,
            reason="legal request",
        )
        assert result.discord_user_id == 123456789012345678

    async def test_lookup_requires_a_reason(self, session, factory):
        _user, alias = await factory.member()
        with pytest.raises(Exception):
            await IdentityService(session).lookup(
                actor_level=PermissionLevel.BOT_OWNER,
                actor_id=OWNER_DISCORD_ID,
                guild_id=GUILD_ID,
                public_alias=alias.public_alias,
                reason="   ",
            )

    async def test_lookup_is_written_to_the_ledger(self, session, factory):
        from sqlalchemy import select

        from app.core.constants import LedgerAction
        from app.database.models import ModerationLedger

        _user, alias = await factory.member()
        await IdentityService(session).lookup(
            actor_level=PermissionLevel.BOT_OWNER,
            actor_id=OWNER_DISCORD_ID,
            guild_id=GUILD_ID,
            public_alias=alias.public_alias,
            reason="audit trail check",
        )
        rows = (
            await session.execute(
                select(ModerationLedger).where(
                    ModerationLedger.action_type == LedgerAction.IDENTITY_LOOKUP
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert "audit trail check" in str(rows[0].reason)

    async def test_non_owner_is_refused(self, session, factory):
        _user, alias = await factory.member()
        with pytest.raises(PermissionDeniedError):
            await IdentityService(session).lookup(
                actor_level=PermissionLevel.ADMIN,
                actor_id=999,
                guild_id=GUILD_ID,
                public_alias=alias.public_alias,
                reason="curiosity",
            )

    async def test_unknown_alias_raises(self, session, settings, guild):
        with pytest.raises(Exception):
            await IdentityService(session).lookup(
                actor_level=PermissionLevel.BOT_OWNER,
                actor_id=OWNER_DISCORD_ID,
                guild_id=GUILD_ID,
                public_alias="ZZ99",
                reason="fishing",
            )
