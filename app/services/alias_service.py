"""Alias assignment and rotation.

Rotation is the privacy reset. It retires the old alias and mints a new one;
the old profile, its confessions and its followers stay exactly where they are.
Nothing public connects the two.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LedgerAction
from app.core.exceptions import AliasNotFoundError, AliasRotationCooldownError
from app.database.models import AnonAlias
from app.database.repositories import AliasRepository, GuildRepository, ModerationRepository
from app.security.identifiers import normalize_alias
from app.utils.time import ensure_utc, utcnow


class AliasService:
    def __init__(self, session: AsyncSession, *, default_rotation_days: int = 14):
        self.session = session
        self.aliases = AliasRepository(session)
        self.guilds = GuildRepository(session)
        self.ledger = ModerationRepository(session)
        self.default_rotation_days = default_rotation_days

    async def _rotation_days(self, guild_id: int) -> int:
        settings = await self.guilds.get_settings(guild_id)
        return settings.alias_rotation_days if settings else self.default_rotation_days

    async def get_or_create_current(self, internal_user_id: str, guild_id: int) -> AnonAlias:
        """Every user gets exactly one live alias per guild, created on demand."""
        alias = await self.aliases.get_current(internal_user_id, guild_id)
        if alias is not None:
            return alias

        alias = await self.aliases.create(internal_user_id, guild_id)
        await self.ledger.record(
            LedgerAction.ALIAS_CREATED,
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            alias_id=alias.id,
            meta={"public_alias": alias.public_alias},
        )
        return alias

    async def get_by_id(self, alias_id: str) -> AnonAlias:
        alias = await self.aliases.get(alias_id)
        if alias is None:
            raise AliasNotFoundError()
        return alias

    async def find_public(self, guild_id: int, raw_alias: str) -> AnonAlias | None:
        """Resolve ``A17`` / ``#A17`` / ``Anon #A17`` to an alias row."""
        normalized = normalize_alias(raw_alias)
        if normalized is None:
            return None
        return await self.aliases.get_by_public_alias(guild_id, normalized)

    async def next_rotation_at(self, alias: AnonAlias, guild_id: int):
        days = await self._rotation_days(guild_id)
        created = ensure_utc(alias.created_at)
        return created + timedelta(days=days)

    async def can_rotate(self, alias: AnonAlias, guild_id: int) -> tuple[bool, object]:
        """``(allowed, available_at)`` for the settings screen."""
        available_at = await self.next_rotation_at(alias, guild_id)
        return utcnow() >= available_at, available_at

    async def rotate(
        self, internal_user_id: str, guild_id: int, *, reason: str | None = None,
        force: bool = False,
    ) -> tuple[AnonAlias, AnonAlias]:
        """Retire the current alias and create a new one.

        Returns ``(old_alias, new_alias)``. Followers and confession history are
        intentionally *not* migrated - that separation is the entire point.
        """
        current = await self.get_or_create_current(internal_user_id, guild_id)

        if not force:
            allowed, available_at = await self.can_rotate(current, guild_id)
            if not allowed:
                raise AliasRotationCooldownError(available_at)

        old_alias_body = current.public_alias
        await self.aliases.retire(current.id, reason=reason or "user_requested")

        new_alias = await self.aliases.create(internal_user_id, guild_id, reason=reason)

        await self.ledger.record(
            LedgerAction.ALIAS_ROTATED,
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            alias_id=new_alias.id,
            reason=reason,
            previous_state={"public_alias": old_alias_body, "alias_id": current.id},
            new_state={"public_alias": new_alias.public_alias, "alias_id": new_alias.id},
        )
        await self.session.refresh(current)
        return current, new_alias

    async def history(self, internal_user_id: str, guild_id: int) -> list[AnonAlias]:
        """Full alias history. Privileged surfaces only, never public."""
        return await self.aliases.list_for_user(internal_user_id, guild_id)
