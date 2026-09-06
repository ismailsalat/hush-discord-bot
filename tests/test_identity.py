"""Aliases, rotation and the privacy reset it is supposed to provide."""

from __future__ import annotations

import pytest

from app.core.exceptions import AliasRotationCooldownError
from app.services.alias_service import AliasService
from app.services.follow_service import FollowService
from app.services.profile_service import ProfileService
from tests.conftest import GUILD_ID, OTHER_GUILD_ID


@pytest.fixture
def aliases(session):
    return AliasService(session, default_rotation_days=14)


class TestAliasAllocation:
    async def test_alias_is_stable_for_a_user(self, aliases, factory):
        user = await factory.user()
        first = await aliases.get_or_create_current(user.id, GUILD_ID)
        second = await aliases.get_or_create_current(user.id, GUILD_ID)
        assert first.id == second.id

    async def test_alias_differs_per_guild(self, aliases, factory, session, settings):
        from app.database.repositories import GuildRepository

        await GuildRepository(session).get_or_create_settings(
            OTHER_GUILD_ID, settings, name="Other"
        )
        user = await factory.user()
        here = await aliases.get_or_create_current(user.id, GUILD_ID)
        there = await aliases.get_or_create_current(user.id, OTHER_GUILD_ID)
        assert here.id != there.id

    async def test_aliases_are_unique_within_a_guild(self, aliases, factory):
        seen = set()
        for _ in range(25):
            user = await factory.user()
            alias = await aliases.get_or_create_current(user.id, GUILD_ID)
            assert alias.public_alias not in seen
            seen.add(alias.public_alias)

    async def test_discord_id_is_never_the_public_identity(self, aliases, factory):
        user = await factory.user(discord_id=123456789012345678)
        alias = await aliases.get_or_create_current(user.id, GUILD_ID)
        assert "123456789012345678" not in alias.public_alias
        assert user.id not in alias.public_alias


class TestRotation:
    async def test_cooldown_blocks_early_rotation(self, aliases, factory):
        user = await factory.user()
        await aliases.get_or_create_current(user.id, GUILD_ID)
        with pytest.raises(AliasRotationCooldownError):
            await aliases.rotate(user.id, GUILD_ID)

    async def test_rotation_creates_a_new_public_identity(self, aliases, factory):
        user = await factory.user()
        old, new = await aliases.rotate(user.id, GUILD_ID, force=True)
        assert old.public_alias != new.public_alias
        assert new.is_current is True
        assert old.is_current is False

    async def test_old_confessions_stay_with_the_old_alias(self, aliases, factory, session):
        user, alias = await factory.member()
        await factory.confession(user=user, alias=alias, content="before rotation")
        old, new = await aliases.rotate(user.id, GUILD_ID, force=True)

        profiles = ProfileService(session)
        old_profile = await profiles.build(old.id)
        new_profile = await profiles.build(new.id)

        assert old_profile.confession_count == 1
        assert new_profile.confession_count == 0

    async def test_followers_do_not_transfer(self, aliases, factory, session):
        """The whole point of rotation: a fresh start that nobody can follow across."""
        author, author_alias = await factory.member()
        follower, _ = await factory.member()

        follows = FollowService(session)
        await follows.follow(
            follower_internal_user_id=follower.id, alias_id=author_alias.id
        )
        assert await follows.follower_count(author_alias.id) == 1

        old, new = await aliases.rotate(author.id, GUILD_ID, force=True)

        assert await follows.follower_count(old.id) == 1
        assert await follows.follower_count(new.id) == 0
        assert not await follows.is_following(follower.id, new.id)

    async def test_moderators_can_still_link_both_internally(self, aliases, factory):
        user = await factory.user()
        old, new = await aliases.rotate(user.id, GUILD_ID, force=True)
        assert old.internal_user_id == new.internal_user_id == user.id

    async def test_only_one_current_alias_exists(self, aliases, factory, session):
        from sqlalchemy import func, select

        from app.database.models import AnonAlias

        user = await factory.user()
        await aliases.rotate(user.id, GUILD_ID, force=True)
        await aliases.rotate(user.id, GUILD_ID, force=True)

        current = await session.scalar(
            select(func.count())
            .select_from(AnonAlias)
            .where(
                AnonAlias.internal_user_id == user.id,
                AnonAlias.guild_id == GUILD_ID,
                AnonAlias.is_current.is_(True),
            )
        )
        assert current == 1

    async def test_retired_alias_body_is_not_reissued(self, aliases, factory, session):
        """Nobody should inherit a retired identity and its reputation."""
        user = await factory.user()
        old, _new = await aliases.rotate(user.id, GUILD_ID, force=True)

        used = {old.public_alias}
        for _ in range(30):
            other = await factory.user()
            alias = await aliases.get_or_create_current(other.id, GUILD_ID)
            assert alias.public_alias not in used
            used.add(alias.public_alias)
