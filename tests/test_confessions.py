"""Submitting confessions: limits, duplicates, drafts, updates and removal."""

from __future__ import annotations

import pytest

from app.core.exceptions import (
    ConfessionTooLongError,
    DuplicateSubmissionError,
    ConfessionEmptyError,
)
from app.database.repositories import GuildRepository
from app.services.agreement_service import AgreementService
from app.services.confession_service import ConfessionService
from tests.conftest import GUILD_ID


@pytest.fixture
def confessions(session, settings):
    return ConfessionService(session, settings)


async def _agreed_member(session, factory):
    user, alias = await factory.member()
    await AgreementService(session).accept(user.id, GUILD_ID, 1)
    return user, alias


async def _prepare(confessions, user, alias, content, **kwargs):
    return await confessions.prepare(
        internal_user_id=user.id,
        guild_id=GUILD_ID,
        alias_id=alias.id,
        content=content,
        **kwargs,
    )


class TestValidation:
    async def test_empty_confession_is_rejected(self, confessions, session, factory):
        user, alias = await _agreed_member(session, factory)
        with pytest.raises(ConfessionEmptyError):
            await _prepare(confessions, user, alias, "   ")

    async def test_over_limit_is_rejected(self, confessions, session, factory):
        user, alias = await _agreed_member(session, factory)
        with pytest.raises(ConfessionTooLongError):
            await _prepare(confessions, user, alias, "x" * 1501)

    async def test_guild_can_lower_the_limit(self, confessions, session, factory):
        user, alias = await _agreed_member(session, factory)
        await GuildRepository(session).update_settings(
            GUILD_ID, confession_character_limit=100
        )
        with pytest.raises(ConfessionTooLongError):
            await _prepare(confessions, user, alias, "x" * 200)

    async def test_exactly_at_the_limit_is_allowed(self, confessions, session, factory):
        user, alias = await _agreed_member(session, factory)
        confession = await _prepare(confessions, user, alias, "x" * 1500)
        assert confession.public_number >= 1


class TestDuplicatePrevention:
    async def test_identical_text_twice_is_blocked(self, confessions, session, factory):
        user, alias = await _agreed_member(session, factory)
        await _prepare(confessions, user, alias, "the same thing")
        with pytest.raises(DuplicateSubmissionError):
            await _prepare(confessions, user, alias, "the same thing")

    async def test_idempotency_key_returns_the_same_row(self, confessions, session, factory):
        """A retried click must not create a second confession."""
        user, alias = await _agreed_member(session, factory)
        first = await _prepare(
            confessions, user, alias, "only once", idempotency_key="key-1"
        )
        second = await _prepare(
            confessions, user, alias, "only once", idempotency_key="key-1"
        )
        assert first.id == second.id, "a retry must not create a second confession"

    async def test_different_users_may_post_the_same_text(
        self, confessions, session, factory
    ):
        one, one_alias = await _agreed_member(session, factory)
        two, two_alias = await _agreed_member(session, factory)
        await _prepare(confessions, one, one_alias, "a common thought")
        result = await _prepare(confessions, two, two_alias, "a common thought")
        assert result is not None


class TestNumbering:
    async def test_numbers_increment_per_guild(self, factory):
        first = await factory.confession(content="one")
        second = await factory.confession(content="two")
        assert second.public_number == first.public_number + 1

    async def test_ids_are_not_derived_from_the_public_number(self, factory):
        """The public number is sequential; the internal id must not be."""
        first = await factory.confession(content="one")
        second = await factory.confession(content="two")

        assert first.id.startswith("conf_") and second.id.startswith("conf_")
        assert len(first.id) == len("conf_") + 16
        # Sequential numbers, unrelated ids.
        assert second.public_number == first.public_number + 1
        assert first.id[:10] != second.id[:10]


class TestUpdates:
    async def test_update_is_its_own_confession(self, confessions, session, factory):
        user, alias = await _agreed_member(session, factory)
        original = await factory.confession(user=user, alias=alias, content="chapter one")
        update = await _prepare(
            confessions, user, alias, "chapter two", parent_confession_id=original.id
        )
        assert update.id != original.id
        assert update.public_number != original.public_number
        assert update.parent_confession_id == original.id

    async def test_chain_links_both_directions(self, confessions, session, factory):
        user, alias = await _agreed_member(session, factory)
        original = await factory.confession(user=user, alias=alias, content="start")
        update = await _prepare(
            confessions, user, alias, "middle", parent_confession_id=original.id
        )
        await confessions.finalize_posted(update.id, message_id=1, channel_id=2)

        view = await confessions.build_view(await confessions.get(original.id))
        assert update.public_number in view.update_numbers

        update_view = await confessions.build_view(await confessions.get(update.id))
        assert update_view.parent_number == original.public_number

    async def test_only_the_author_may_update(self, confessions, session, factory):
        from app.core.exceptions import NotConfessionAuthorError

        author, alias = await _agreed_member(session, factory)
        original = await factory.confession(user=author, alias=alias)
        stranger, stranger_alias = await _agreed_member(session, factory)

        with pytest.raises(NotConfessionAuthorError):
            await _prepare(
                confessions,
                stranger,
                stranger_alias,
                "not mine to update",
                parent_confession_id=original.id,
            )


class TestRemoval:
    async def test_removal_is_a_soft_delete(self, confessions, session, factory):
        confession = await factory.confession(content="will be removed")
        await confessions.remove(confession.id, moderator_id=None, reason="test")
        row = await confessions.get(confession.id)
        assert row.is_deleted
        assert row.content == "will be removed"

    async def test_removed_confessions_are_hidden(self, confessions, factory):
        from app.core.exceptions import ConfessionNotFoundError

        confession = await factory.confession()
        await confessions.remove(confession.id, moderator_id=None, reason="test")
        with pytest.raises(ConfessionNotFoundError):
            await confessions.get_visible(confession.id)
