"""Alias creation, rotation and lookup."""

from __future__ import annotations

from sqlalchemy import func, select, update

from app.core.exceptions import AliasPoolExhaustedError
from app.database.models import AnonAlias
from app.database.repositories.base import BaseRepository
from app.security.identifiers import ALIAS_FORMATS, generate_alias_candidate
from app.utils.time import utcnow

#: Attempts per format tier before widening the alias format.
_ATTEMPTS_PER_TIER = 12


class AliasRepository(BaseRepository):
    async def get(self, alias_id: str) -> AnonAlias | None:
        return await self.session.get(AnonAlias, alias_id)

    async def get_current(self, internal_user_id: str, guild_id: int) -> AnonAlias | None:
        result = await self.session.execute(
            select(AnonAlias).where(
                AnonAlias.internal_user_id == internal_user_id,
                AnonAlias.guild_id == guild_id,
                AnonAlias.is_current.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_public_alias(self, guild_id: int, public_alias: str) -> AnonAlias | None:
        """Look up by the public body (``A17``), current or retired."""
        result = await self.session.execute(
            select(AnonAlias).where(
                AnonAlias.guild_id == guild_id,
                func.upper(AnonAlias.public_alias) == public_alias.upper(),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, internal_user_id: str, guild_id: int) -> list[AnonAlias]:
        """Full alias history for one user. Privileged/system use only."""
        result = await self.session.execute(
            select(AnonAlias)
            .where(
                AnonAlias.internal_user_id == internal_user_id,
                AnonAlias.guild_id == guild_id,
            )
            .order_by(AnonAlias.created_at.desc())
        )
        return list(result.scalars().all())

    async def _is_taken(self, guild_id: int, candidate: str) -> bool:
        result = await self.session.execute(
            select(AnonAlias.id).where(
                AnonAlias.guild_id == guild_id, AnonAlias.public_alias == candidate
            )
        )
        return result.first() is not None

    async def allocate_public_alias(self, guild_id: int) -> str:
        """Find an unused alias body, widening the format if a tier fills up.

        Bodies are never reused, so this checks retired aliases too.
        """
        for tier in range(len(ALIAS_FORMATS)):
            for _ in range(_ATTEMPTS_PER_TIER):
                candidate = generate_alias_candidate(tier)
                if not await self._is_taken(guild_id, candidate):
                    return candidate
        raise AliasPoolExhaustedError()

    async def create(
        self, internal_user_id: str, guild_id: int, *, reason: str | None = None
    ) -> AnonAlias:
        """Create a new current alias. Caller must retire any existing one first."""
        alias = AnonAlias(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            public_alias=await self.allocate_public_alias(guild_id),
            rotation_reason=reason,
            is_current=True,
        )
        self.session.add(alias)
        await self.session.flush()
        return alias

    async def retire(self, alias_id: str, *, reason: str | None = None) -> None:
        await self.session.execute(
            update(AnonAlias)
            .where(AnonAlias.id == alias_id)
            .values(is_current=False, retired_at=utcnow(), rotation_reason=reason)
        )
        await self.session.flush()
