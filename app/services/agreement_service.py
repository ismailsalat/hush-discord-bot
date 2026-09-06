"""First-time and re-acceptance handling for the rules agreement."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LedgerAction
from app.database.models import Agreement
from app.database.repositories import GuildRepository, ModerationRepository
from sqlalchemy import select


class AgreementService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.guilds = GuildRepository(session)
        self.ledger = ModerationRepository(session)

    async def current_version(self, guild_id: int, default: int = 1) -> int:
        settings = await self.guilds.get_settings(guild_id)
        return settings.rules_version if settings else default

    async def get_acceptance(
        self, internal_user_id: str, guild_id: int, version: int
    ) -> Agreement | None:
        result = await self.session.execute(
            select(Agreement).where(
                Agreement.internal_user_id == internal_user_id,
                Agreement.guild_id == guild_id,
                Agreement.agreement_version == version,
                Agreement.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def has_accepted(self, internal_user_id: str, guild_id: int, version: int) -> bool:
        return await self.get_acceptance(internal_user_id, guild_id, version) is not None

    async def has_accepted_any(self, internal_user_id: str, guild_id: int) -> bool:
        """True if a previous version was accepted - distinguishes new users
        from returning users who only need to re-accept updated rules."""
        result = await self.session.execute(
            select(Agreement.id).where(
                Agreement.internal_user_id == internal_user_id,
                Agreement.guild_id == guild_id,
                Agreement.revoked_at.is_(None),
            )
        )
        return result.first() is not None

    async def accept(self, internal_user_id: str, guild_id: int, version: int) -> Agreement:
        """Record acceptance. Idempotent - re-clicking never duplicates a row."""
        existing = await self.get_acceptance(internal_user_id, guild_id, version)
        if existing is not None:
            return existing

        is_reacceptance = await self.has_accepted_any(internal_user_id, guild_id)
        agreement = Agreement(
            internal_user_id=internal_user_id, guild_id=guild_id, agreement_version=version
        )
        self.session.add(agreement)
        await self.session.flush()

        await self.ledger.record(
            LedgerAction.RULES_REACCEPTED if is_reacceptance else LedgerAction.RULES_ACCEPTED,
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            meta={"version": version},
        )
        return agreement

    async def list_for_user(self, internal_user_id: str) -> list[Agreement]:
        result = await self.session.execute(
            select(Agreement)
            .where(Agreement.internal_user_id == internal_user_id)
            .order_by(Agreement.accepted_at.desc())
        )
        return list(result.scalars().all())
