"""Owner-only reverse identity lookup.

Isolated in its own module so the capability is easy to find, easy to audit and
impossible to reach by accident from ordinary moderation code. Every call is
logged to both the ledger and the security log before the value is returned.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LedgerAction, PermissionLevel
from app.core.exceptions import PermissionDeniedError
from app.database.repositories import AliasRepository, ModerationRepository, UserRepository
from app.logging.audit import log_identity_lookup
from app.security.permissions import IDENTITY_LOOKUP_LEVEL


@dataclass(frozen=True, slots=True)
class IdentityResult:
    internal_user_id: str
    discord_user_id: int


class IdentityService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.aliases = AliasRepository(session)
        self.ledger = ModerationRepository(session)

    async def lookup(
        self,
        *,
        actor_level: PermissionLevel,
        actor_id: int,
        guild_id: int,
        internal_user_id: str | None = None,
        public_alias: str | None = None,
        reason: str,
    ) -> IdentityResult:
        """Resolve an alias or internal id to a Discord user id.

        Requires ``OWNER``. Refuses without a stated reason so the audit trail
        is always meaningful.
        """
        if not actor_level.meets(IDENTITY_LOOKUP_LEVEL):
            raise PermissionDeniedError(
                "identity lookup requires owner level",
                user_message="Identity lookup is restricted to the bot owner.",
            )
        if not reason.strip():
            raise PermissionDeniedError(
                "identity lookup requires a reason",
                user_message="A reason is required for an identity lookup.",
            )

        resolved_internal_id = internal_user_id
        if resolved_internal_id is None and public_alias:
            alias = await self.aliases.get_by_public_alias(guild_id, public_alias)
            if alias is None:
                raise PermissionDeniedError(
                    "alias not found",
                    user_message="No matching account was found.",
                )
            resolved_internal_id = alias.internal_user_id

        if resolved_internal_id is None:
            raise PermissionDeniedError(
                "no target supplied", user_message="Specify an alias or internal id."
            )

        user = await self.users.get(resolved_internal_id)
        if user is None:
            raise PermissionDeniedError(
                "user not found", user_message="No matching account was found."
            )

        await self.ledger.record(
            LedgerAction.IDENTITY_LOOKUP,
            internal_user_id=resolved_internal_id,
            guild_id=guild_id,
            moderator_id=actor_id,
            reason=reason,
            meta={"public_alias": public_alias},
        )
        log_identity_lookup(
            actor_id=actor_id,
            target=public_alias or resolved_internal_id,
            guild_id=guild_id,
            reason=reason,
        )
        return IdentityResult(
            internal_user_id=resolved_internal_id, discord_user_id=user.discord_user_id
        )
