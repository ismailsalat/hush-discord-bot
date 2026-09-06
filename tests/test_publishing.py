"""End-to-end submission, using a fake Discord layer.

These are the tests that prove the database and Discord cannot disagree: either
a confession is posted and recorded, or it is not posted and the author's text
is safe in a draft.
"""

from __future__ import annotations

import pytest

from app.core.constants import ConfessionStatus
from app.core.exceptions import ConfessionTooLongError
from app.database.repositories import ConfessionRepository, DraftRepository
from app.services.agreement_service import AgreementService
from app.services.publishing_service import (
    PublishedMessage,
    PublishingService,
    PublishTarget,
)
from tests.conftest import GUILD_ID


class FakePublisher:
    """Stands in for Discord. Can be told to fail."""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.published: list[str] = []
        self.refreshed: list[int] = []
        self.withdrawn: list[int] = []
        self._next_id = 10_000

    async def publish(self, view, target: PublishTarget) -> PublishedMessage:
        if self.fail:
            raise RuntimeError("Discord is down")
        self._next_id += 1
        self.published.append(view.confession_id)
        return PublishedMessage(message_id=self._next_id, channel_id=target.channel_id)

    async def refresh(self, view, message_id: int, channel_id: int) -> None:
        self.refreshed.append(message_id)

    async def withdraw(self, message_id: int, channel_id: int) -> None:
        self.withdrawn.append(message_id)


@pytest.fixture
async def agreed_user(session, settings, guild, factory):
    user, alias = await factory.member()
    await AgreementService(session).accept(user.id, GUILD_ID, guild.rules_version)
    return user, alias


def publishing(database, settings, publisher) -> PublishingService:
    return PublishingService(database, settings, publisher)


class TestSuccessfulSubmission:
    async def test_confession_is_posted_and_recorded(
        self, database, settings, agreed_user, session
    ):
        user, _alias = agreed_user
        publisher = FakePublisher()
        result = await publishing(database, settings, publisher).submit(
            internal_user_id=user.id, guild_id=GUILD_ID, content="my first confession"
        )

        assert result.ok
        assert result.confession_id in publisher.published

        row = await ConfessionRepository(session).get_by_id(result.confession_id)
        assert row.status == ConfessionStatus.POSTED
        assert row.discord_message_id is not None

    async def test_no_draft_is_left_behind_on_success(
        self, database, settings, agreed_user, session
    ):
        user, _alias = agreed_user
        await publishing(database, settings, FakePublisher()).submit(
            internal_user_id=user.id, guild_id=GUILD_ID, content="clean run"
        )
        assert await DraftRepository(session).get_for_user(user.id, GUILD_ID) is None

    async def test_public_number_is_returned(self, database, settings, agreed_user):
        user, _alias = agreed_user
        result = await publishing(database, settings, FakePublisher()).submit(
            internal_user_id=user.id, guild_id=GUILD_ID, content="numbered"
        )
        assert result.public_number >= 1


class TestFailedSubmission:
    async def test_failure_saves_the_draft(self, database, settings, agreed_user, session):
        """The single most important failure guarantee: never lose their words."""
        user, _alias = agreed_user
        text = "something I was brave enough to type once"

        result = await publishing(database, settings, FakePublisher(fail=True)).submit(
            internal_user_id=user.id, guild_id=GUILD_ID, content=text
        )

        assert not result.ok
        draft = await DraftRepository(session).get_for_user(user.id, GUILD_ID)
        assert draft is not None
        assert draft.content == text

    async def test_failure_marks_the_row_failed_not_posted(
        self, database, settings, agreed_user, session
    ):
        user, _alias = agreed_user
        await publishing(database, settings, FakePublisher(fail=True)).submit(
            internal_user_id=user.id, guild_id=GUILD_ID, content="doomed"
        )

        confessions = ConfessionRepository(session)
        rows = await confessions.list_for_user(user.id, GUILD_ID)
        assert rows
        assert all(row.status != ConfessionStatus.POSTED for row in rows)

    async def test_failure_produces_an_error_id(self, database, settings, agreed_user):
        user, _alias = agreed_user
        result = await publishing(database, settings, FakePublisher(fail=True)).submit(
            internal_user_id=user.id, guild_id=GUILD_ID, content="doomed"
        )
        assert result.error_report is not None
        assert result.error_report.error_id.startswith("ERR-")

    async def test_validation_failure_also_saves_the_draft(
        self, database, settings, agreed_user, session
    ):
        user, _alias = agreed_user
        long_text = "x" * 5000
        result = await publishing(database, settings, FakePublisher()).submit(
            internal_user_id=user.id, guild_id=GUILD_ID, content=long_text
        )
        assert not result.ok
        assert isinstance(result.error, ConfessionTooLongError)
        draft = await DraftRepository(session).get_for_user(user.id, GUILD_ID)
        assert draft is not None


class TestRefreshAndWithdraw:
    async def test_refresh_updates_the_message(self, database, settings, agreed_user):
        user, _alias = agreed_user
        publisher = FakePublisher()
        service = publishing(database, settings, publisher)
        result = await service.submit(
            internal_user_id=user.id, guild_id=GUILD_ID, content="to be refreshed"
        )
        assert await service.refresh_message(result.confession_id)
        assert publisher.refreshed

    async def test_withdraw_removes_the_message(self, database, settings, agreed_user):
        user, _alias = agreed_user
        publisher = FakePublisher()
        service = publishing(database, settings, publisher)
        result = await service.submit(
            internal_user_id=user.id, guild_id=GUILD_ID, content="to be withdrawn"
        )
        assert await service.withdraw_message(result.confession_id)
        assert publisher.withdrawn


class TestReconciliation:
    async def test_stuck_pending_rows_are_repaired(
        self, database, settings, agreed_user, session
    ):
        """Simulates the process dying between writing the row and posting."""
        from datetime import timedelta

        from app.core.runtime import Runtime
        from app.tasks.maintenance import MaintenanceTasks
        from app.utils.time import utcnow

        user, alias = agreed_user
        confessions = ConfessionRepository(session)
        stuck = await confessions.create_pending(
            guild_id=GUILD_ID,
            internal_user_id=user.id,
            alias_id=alias.id,
            content="interrupted mid-post",
            content_fingerprint="fp-stuck",
        )
        stuck.created_at = utcnow() - timedelta(minutes=30)
        await session.flush()

        runtime = Runtime(settings, database)
        detail = await MaintenanceTasks(runtime).reconcile()

        assert detail and "1" in detail
        repaired = await ConfessionRepository(session).get_by_id(stuck.id)
        await session.refresh(repaired)
        assert repaired.status == ConfessionStatus.FAILED

        draft = await DraftRepository(session).get_for_user(user.id, GUILD_ID)
        assert draft is not None
        assert draft.content == "interrupted mid-post"
