"""The single gate every user action passes through.

Order matters and is enforced here rather than scattered across cogs:

1. a pending moderation notice must be shown before anything else
2. a banned user cannot act
3. the current rules version must have been accepted

Putting this in one place is what guarantees that closing your DMs cannot be
used to dodge a punishment notice.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.core.exceptions import (
    AgreementRequiredError,
    GuildNotConfiguredError,
    PendingModerationNoticeError,
    UserHushBannedError,
)
from app.database.models import GuildSettings, Notification
from app.database.repositories import (
    GuildRepository,
    ModerationRepository,
    NotificationRepository,
)
from app.services.agreement_service import AgreementService


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    settings: GuildSettings | None = None
    blocking_notice: Notification | None = None
    needs_agreement: bool = False
    is_reacceptance: bool = False
    ban_reason: str | None = None


class AccessService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.guilds = GuildRepository(session)
        self.notifications = NotificationRepository(session)
        self.moderation = ModerationRepository(session)
        self.agreements = AgreementService(session)

    async def check(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        require_agreement: bool = True,
        require_configured: bool = True,
    ) -> AccessDecision:
        """Evaluate access without raising. Use :meth:`enforce` to raise."""
        guild_settings = await self.guilds.get_or_create_settings(guild_id, self.settings)

        if require_configured and not guild_settings.is_configured:
            raise GuildNotConfiguredError()

        notice = await self.notifications.get_outstanding_blocking(internal_user_id, guild_id)
        if notice is not None:
            return AccessDecision(
                allowed=False, settings=guild_settings, blocking_notice=notice
            )

        ban = await self.moderation.get_active_ban(internal_user_id, guild_id)
        if ban is not None:
            return AccessDecision(allowed=False, settings=guild_settings, ban_reason=ban.reason)

        if require_agreement:
            version = guild_settings.rules_version
            if not await self.agreements.has_accepted(internal_user_id, guild_id, version):
                return AccessDecision(
                    allowed=False,
                    settings=guild_settings,
                    needs_agreement=True,
                    is_reacceptance=await self.agreements.has_accepted_any(
                        internal_user_id, guild_id
                    ),
                )

        return AccessDecision(allowed=True, settings=guild_settings)

    async def enforce(
        self, *, internal_user_id: str, guild_id: int, require_agreement: bool = True
    ) -> GuildSettings:
        """Raise the appropriate domain error when access is denied."""
        decision = await self.check(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            require_agreement=require_agreement,
        )
        if decision.blocking_notice is not None:
            raise PendingModerationNoticeError(decision.blocking_notice.id)
        if decision.ban_reason is not None:
            ban = await self.moderation.get_active_ban(internal_user_id, guild_id)
            raise UserHushBannedError(
                expires_at=ban.expires_at if ban else None,
                reason=ban.reason if ban else None,
                permanent=bool(ban and ban.is_permanent),
            )
        if decision.needs_agreement:
            raise AgreementRequiredError()
        assert decision.settings is not None
        return decision.settings

    async def active_ban(self, internal_user_id: str, guild_id: int):
        return await self.moderation.get_active_ban(internal_user_id, guild_id)
