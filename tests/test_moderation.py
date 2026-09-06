"""Reports, warnings, bans, expiry and the closed-DM guarantee."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.constants import BanDuration, NotificationKind, ReportReason
from app.services.access_service import AccessService
from app.services.moderation_service import ModerationService
from app.services.notification_service import NotificationService
from app.utils.time import utcnow
from tests.conftest import GUILD_ID


async def clear_notices(session, internal_user_id: str, guild_id: int = GUILD_ID) -> None:
    """Acknowledge any queued notice so a test can assert on ban state itself.

    Notices deliberately take priority over everything else, so without this a
    ban assertion would only ever see the notice.
    """
    notifications = NotificationService(session)
    while (notice := await notifications.outstanding_blocking(internal_user_id, guild_id)):
        await notifications.acknowledge(notice.id)

MODERATOR_ID = 4242424242


@pytest.fixture
def moderation(session, settings):
    return ModerationService(session, settings)


class TestReports:
    async def test_report_is_recorded(self, moderation, factory):
        confession = await factory.confession()
        reporter, _ = await factory.member()
        report = await moderation.report(
            confession_id=confession.id,
            reporter_internal_user_id=reporter.id,
            reason=ReportReason.HARASSMENT,
        )
        assert report.confession_id == confession.id

    async def test_reporting_does_not_remove_the_confession(self, moderation, factory):
        """Reports are a signal, never an automatic takedown."""
        confession = await factory.confession()
        reporter, _ = await factory.member()
        await moderation.report(
            confession_id=confession.id,
            reporter_internal_user_id=reporter.id,
            reason=ReportReason.HARASSMENT,
        )
        assert not (await factory.confessions.get_by_id(confession.id)).is_deleted

    async def test_same_person_cannot_report_twice(self, moderation, factory):
        confession = await factory.confession()
        reporter, _ = await factory.member()
        await moderation.report(
            confession_id=confession.id,
            reporter_internal_user_id=reporter.id, reason=ReportReason.HARASSMENT,
        )
        with pytest.raises(Exception):
            await moderation.report(
                confession_id=confession.id, guild_id=GUILD_ID,
                reporter_internal_user_id=reporter.id, reason=ReportReason.HARASSMENT,
            )

    async def test_open_reports_are_listed_for_moderators(self, moderation, factory):
        confession = await factory.confession()
        reporter, _ = await factory.member()
        await moderation.report(
            confession_id=confession.id,
            reporter_internal_user_id=reporter.id, reason=ReportReason.OTHER,
            details="just wrong",
        )
        rows = await moderation.open_reports(GUILD_ID)
        assert len(rows) == 1


class TestWarnings:
    async def test_warning_queues_a_notice(self, moderation, session, factory):
        user, _ = await factory.member()
        await moderation.warn(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, reason="be nicer",
        )
        notice = await NotificationService(session).outstanding_blocking(user.id, GUILD_ID)
        assert notice is not None
        assert notice.kind == NotificationKind.WARNING

    async def test_warning_appears_in_history(self, moderation, factory):
        user, _ = await factory.member()
        await moderation.warn(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, reason="first",
        )
        history = await moderation.punishment_history(user.id, GUILD_ID)
        assert history.warning_count == 1

    async def test_history_never_exposes_identity(self, moderation, factory):
        user, _ = await factory.member(discord_id=123456789012345678)
        await moderation.warn(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, reason="x",
        )
        history = await moderation.punishment_history(user.id, GUILD_ID)
        assert "123456789012345678" not in repr(history)


class TestBans:
    async def test_temp_ban_blocks_access(self, moderation, session, settings, factory):
        user, _ = await factory.member()
        await moderation.ban(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, duration=BanDuration.DAY,
            reason="rule break",
        )
        await clear_notices(session, user.id)
        decision = await AccessService(session, settings).check(
            internal_user_id=user.id, guild_id=GUILD_ID, require_agreement=False
        )
        assert not decision.allowed
        assert decision.ban_reason

    @pytest.mark.parametrize(
        "duration,hours",
        [
            (BanDuration.HOUR, 1),
            (BanDuration.DAY, 24),
            (BanDuration.WEEK, 168),
            (BanDuration.MONTH, 720),
        ],
    )
    async def test_durations_map_to_expiry(self, moderation, factory, duration, hours):
        user, _ = await factory.member()
        ban = await moderation.ban(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, duration=duration, reason="x",
        )
        delta = ban.expires_at.replace(tzinfo=ban.expires_at.tzinfo or None) - utcnow()
        assert abs(delta - timedelta(hours=hours)) < timedelta(minutes=2)

    async def test_permanent_ban_has_no_expiry(self, moderation, factory):
        user, _ = await factory.member()
        ban = await moderation.ban(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, duration=BanDuration.PERMANENT,
            reason="x",
        )
        assert ban.is_permanent
        assert ban.expires_at is None

    async def test_expired_ban_stops_blocking(
        self, moderation, session, settings, factory
    ):
        user, _ = await factory.member()
        ban = await moderation.ban(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, duration=BanDuration.HOUR,
            reason="x",
        )
        # Wind the clock forward by editing the row directly.
        ban.expires_at = utcnow() - timedelta(minutes=1)
        await session.flush()

        expired = await moderation.expire_due_bans()
        assert expired == 1
        await clear_notices(session, user.id)

        decision = await AccessService(session, settings).check(
            internal_user_id=user.id, guild_id=GUILD_ID, require_agreement=False
        )
        assert decision.allowed

    async def test_revoking_a_ban_restores_access(
        self, moderation, session, settings, factory
    ):
        user, _ = await factory.member()
        ban = await moderation.ban(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, duration=BanDuration.PERMANENT,
            reason="x",
        )
        await moderation.revoke_ban(ban.id, MODERATOR_ID)
        await clear_notices(session, user.id)
        decision = await AccessService(session, settings).check(
            internal_user_id=user.id, guild_id=GUILD_ID, require_agreement=False
        )
        assert decision.allowed

    async def test_ban_is_scoped_to_one_guild(
        self, moderation, session, settings, factory
    ):
        from app.database.repositories import GuildRepository
        from tests.conftest import OTHER_GUILD_ID

        guilds = GuildRepository(session)
        await guilds.get_or_create_settings(OTHER_GUILD_ID, settings, name="Elsewhere")
        await guilds.update_settings(OTHER_GUILD_ID, confession_channel_id=999)
        user, _ = await factory.member()
        await moderation.ban(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, duration=BanDuration.PERMANENT,
            reason="x",
        )
        await clear_notices(session, user.id, OTHER_GUILD_ID)
        elsewhere = await AccessService(session, settings).check(
            internal_user_id=user.id, guild_id=OTHER_GUILD_ID, require_agreement=False
        )
        assert elsewhere.allowed


class TestClosedDmGuarantee:
    """A user with closed DMs must still receive moderation notices."""

    async def test_notice_blocks_until_seen(
        self, moderation, session, settings, factory
    ):
        user, _ = await factory.member()
        await moderation.warn(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, reason="read this",
        )
        decision = await AccessService(session, settings).check(
            internal_user_id=user.id, guild_id=GUILD_ID, require_agreement=False
        )
        assert decision.blocking_notice is not None

    async def test_acknowledging_clears_the_block(
        self, moderation, session, settings, factory
    ):
        user, _ = await factory.member()
        await moderation.warn(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, reason="read this",
        )
        notifications = NotificationService(session)
        notice = await notifications.outstanding_blocking(user.id, GUILD_ID)
        await notifications.acknowledge(notice.id)

        decision = await AccessService(session, settings).check(
            internal_user_id=user.id, guild_id=GUILD_ID, require_agreement=False
        )
        assert decision.blocking_notice is None

    async def test_failed_delivery_does_not_discard_the_notice(
        self, moderation, session, factory
    ):
        from app.database.repositories import NotificationRepository

        user, _ = await factory.member()
        await moderation.warn(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, reason="dm closed",
        )
        notifications = NotificationRepository(session)
        notice = await notifications.get_outstanding_blocking(user.id, GUILD_ID)
        await notifications.mark_failed(notice.id, "Forbidden")

        still_there = await notifications.get_outstanding_blocking(user.id, GUILD_ID)
        assert still_there is not None
        assert still_there.id == notice.id

    async def test_notice_order_puts_moderation_first(
        self, moderation, session, settings, factory
    ):
        """A warned, banned, unagreed user sees the warning first."""
        user, _ = await factory.member()
        await moderation.warn(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, reason="notice",
        )
        await moderation.ban(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, duration=BanDuration.DAY,
            reason="ban",
        )
        decision = await AccessService(session, settings).check(
            internal_user_id=user.id, guild_id=GUILD_ID, require_agreement=True
        )
        assert decision.blocking_notice is not None


class TestLedger:
    async def test_every_action_is_recorded(self, moderation, session, factory):
        from sqlalchemy import func, select

        from app.database.models import ModerationLedger

        user, _ = await factory.member()
        before = await session.scalar(select(func.count()).select_from(ModerationLedger))

        await moderation.warn(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, reason="a",
        )
        await moderation.ban(
            internal_user_id=user.id, guild_id=GUILD_ID,
            moderator_id=MODERATOR_ID, duration=BanDuration.HOUR, reason="b",
        )
        after = await session.scalar(select(func.count()).select_from(ModerationLedger))
        assert after >= before + 2
