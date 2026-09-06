"""Warnings, bans and the append-only ledger."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.constants import LedgerAction
from app.database.models import Ban, ModerationLedger, ModerationWarning
from app.database.repositories.base import BaseRepository
from app.utils.time import utcnow


class ModerationRepository(BaseRepository):
    # --- Warnings ----------------------------------------------------------

    async def create_warning(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        moderator_id: int,
        reason: str,
        related_confession_id: str | None = None,
    ) -> ModerationWarning:
        warning = ModerationWarning(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            moderator_id=moderator_id,
            reason=reason,
            related_confession_id=related_confession_id,
        )
        self.session.add(warning)
        await self.session.flush()
        return warning

    async def get_warning(self, warning_id: str) -> ModerationWarning | None:
        return await self.session.get(ModerationWarning, warning_id)

    async def acknowledge_warning(self, warning_id: str) -> ModerationWarning | None:
        warning = await self.get_warning(warning_id)
        if warning is not None and warning.acknowledged_at is None:
            warning.acknowledged_at = utcnow()
            await self.session.flush()
        return warning

    async def revoke_warning(self, warning_id: str, moderator_id: int) -> ModerationWarning | None:
        warning = await self.get_warning(warning_id)
        if warning is not None:
            warning.revoked_at = utcnow()
            warning.revoked_by = moderator_id
            await self.session.flush()
        return warning

    async def list_warnings(
        self, internal_user_id: str, guild_id: int | None = None
    ) -> list[ModerationWarning]:
        query = select(ModerationWarning).where(
            ModerationWarning.internal_user_id == internal_user_id
        )
        if guild_id is not None:
            query = query.where(ModerationWarning.guild_id == guild_id)
        result = await self.session.execute(query.order_by(ModerationWarning.created_at.desc()))
        return list(result.scalars().all())

    # --- Bans --------------------------------------------------------------

    async def create_ban(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        moderator_id: int,
        reason: str,
        expires_at: datetime | None,
        is_permanent: bool,
    ) -> Ban:
        ban = Ban(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            moderator_id=moderator_id,
            reason=reason,
            expires_at=expires_at,
            is_permanent=is_permanent,
        )
        self.session.add(ban)
        await self.session.flush()
        return ban

    async def get_ban(self, ban_id: str) -> Ban | None:
        return await self.session.get(Ban, ban_id)

    async def get_active_ban(self, internal_user_id: str, guild_id: int) -> Ban | None:
        """Strongest active ban, permanent first.

        The expiry comparison happens in SQL so an elapsed temporary ban stops
        blocking immediately, even if the sweeper task has not run yet.
        """
        now = utcnow()
        result = await self.session.execute(
            select(Ban)
            .where(
                Ban.internal_user_id == internal_user_id,
                Ban.guild_id == guild_id,
                Ban.revoked_at.is_(None),
                or_(Ban.is_permanent.is_(True), Ban.expires_at > now),
            )
            .order_by(Ban.is_permanent.desc(), Ban.expires_at.desc().nullsfirst())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def revoke_ban(self, ban_id: str, moderator_id: int) -> Ban | None:
        ban = await self.get_ban(ban_id)
        if ban is not None:
            ban.revoked_at = utcnow()
            ban.revoked_by = moderator_id
            await self.session.flush()
        return ban

    async def list_bans(self, internal_user_id: str, guild_id: int | None = None) -> list[Ban]:
        query = select(Ban).where(Ban.internal_user_id == internal_user_id)
        if guild_id is not None:
            query = query.where(Ban.guild_id == guild_id)
        result = await self.session.execute(query.order_by(Ban.created_at.desc()))
        return list(result.scalars().all())

    async def list_newly_expired_bans(self) -> list[Ban]:
        """Temporary bans past their expiry that have not been logged as expired."""
        now = utcnow()
        result = await self.session.execute(
            select(Ban).where(
                Ban.is_permanent.is_(False),
                Ban.revoked_at.is_(None),
                Ban.expires_at.is_not(None),
                Ban.expires_at <= now,
            )
        )
        bans = list(result.scalars().all())
        if not bans:
            return []
        logged = await self.session.execute(
            select(ModerationLedger.meta).where(
                ModerationLedger.action_type == LedgerAction.TEMP_BAN_EXPIRED
            )
        )
        already = {
            (row[0] or {}).get("ban_id") for row in logged.all() if isinstance(row[0], dict)
        }
        return [ban for ban in bans if ban.id not in already]

    # --- Ledger ------------------------------------------------------------

    async def record(
        self,
        action: LedgerAction,
        *,
        internal_user_id: str | None = None,
        guild_id: int | None = None,
        moderator_id: int | None = None,
        confession_id: str | None = None,
        alias_id: str | None = None,
        reason: str | None = None,
        meta: dict[str, Any] | None = None,
        previous_state: dict[str, Any] | None = None,
        new_state: dict[str, Any] | None = None,
    ) -> ModerationLedger:
        """Append one immutable ledger row. Never updates an existing one."""
        entry = ModerationLedger(
            action_type=action,
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            moderator_id=moderator_id,
            confession_id=confession_id,
            alias_id=alias_id,
            reason=reason,
            meta=meta,
            previous_state=previous_state,
            new_state=new_state,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_ledger(
        self,
        *,
        guild_id: int | None = None,
        internal_user_id: str | None = None,
        action: LedgerAction | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ModerationLedger]:
        query = select(ModerationLedger)
        if guild_id is not None:
            query = query.where(ModerationLedger.guild_id == guild_id)
        if internal_user_id is not None:
            query = query.where(ModerationLedger.internal_user_id == internal_user_id)
        if action is not None:
            query = query.where(ModerationLedger.action_type == action)
        if since is not None:
            query = query.where(ModerationLedger.created_at >= since)
        result = await self.session.execute(
            query.order_by(ModerationLedger.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def count_recent(self, action: LedgerAction, *, hours: int = 1) -> int:
        cutoff = utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(func.count())
            .select_from(ModerationLedger)
            .where(
                ModerationLedger.action_type == action, ModerationLedger.created_at >= cutoff
            )
        )
        return int(result.scalar_one())
