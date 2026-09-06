"""Permission resolution for Hush.

There are five tiers. Two of them (``MODERATOR`` and ``ADMIN``) are configured
per guild by the server owner, which is the point: a trusted person can manage
Hush without being handed Discord Administrator over the whole server.

Resolution order, highest wins:

1. ``BOT_OWNER``  - listed in ``BOT_OWNER_IDS``
2. ``SERVER_OWNER`` - the Discord guild owner
3. ``ADMIN``      - a configured Hush admin role/user, or Discord Administrator
4. ``MODERATOR``  - a configured Hush moderator role/user
5. ``USER``       - everyone else

Every check in the project goes through :func:`resolve_level` and
:func:`require`. Nothing re-implements this logic locally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.core.constants import PermissionLevel
from app.core.exceptions import PermissionDeniedError


@dataclass(frozen=True, slots=True)
class MemberContext:
    """Plain, Discord-free description of who is acting.

    Kept free of ``discord.py`` types so permission logic is testable without a
    gateway connection.
    """

    user_id: int
    role_ids: frozenset[int] = frozenset()
    is_guild_admin: bool = False
    is_guild_owner: bool = False


@dataclass(frozen=True, slots=True)
class GuildRoleConfig:
    """The Hush roles a guild has configured.

    Built from ``GuildSettings`` via :meth:`from_settings` so callers never have
    to remember which four columns are involved.
    """

    admin_role_ids: frozenset[int] = frozenset()
    admin_user_ids: frozenset[int] = frozenset()
    moderator_role_ids: frozenset[int] = frozenset()
    moderator_user_ids: frozenset[int] = frozenset()

    @classmethod
    def from_settings(cls, settings) -> "GuildRoleConfig":
        if settings is None:
            return cls()
        return cls(
            admin_role_ids=frozenset(settings.admin_role_ids or ()),
            admin_user_ids=frozenset(settings.admin_user_ids or ()),
            moderator_role_ids=frozenset(settings.moderator_role_ids or ()),
            moderator_user_ids=frozenset(settings.moderator_user_ids or ()),
        )


def resolve_level(
    member: MemberContext,
    *,
    owner_ids: Iterable[int],
    guild_config: GuildRoleConfig | None = None,
) -> PermissionLevel:
    """Return the effective Hush permission tier for a member in a guild."""
    config = guild_config or GuildRoleConfig()

    if member.user_id in set(owner_ids):
        return PermissionLevel.BOT_OWNER
    if member.is_guild_owner:
        return PermissionLevel.SERVER_OWNER
    if (
        member.user_id in config.admin_user_ids
        or member.role_ids & config.admin_role_ids
        or member.is_guild_admin
    ):
        return PermissionLevel.ADMIN
    if member.user_id in config.moderator_user_ids or (
        member.role_ids & config.moderator_role_ids
    ):
        return PermissionLevel.MODERATOR
    return PermissionLevel.USER


def require(
    level: PermissionLevel, required: PermissionLevel, *, action: str = "do that"
) -> None:
    """Raise :class:`PermissionDeniedError` unless ``level`` satisfies ``required``."""
    if not level.meets(required):
        raise PermissionDeniedError(
            f"{level} does not meet {required}",
            user_message=(
                f"You need to be a **{required.label}** to {action}. "
                f"You are currently a {level.label}."
            ),
        )


# --- Named capabilities -----------------------------------------------------
# Commands ask for a capability, not a tier, so changing who may do something is
# a one-line change here rather than a search across the codebase.

MODERATION_LEVEL = PermissionLevel.MODERATOR
CONFIG_LEVEL = PermissionLevel.ADMIN
GUILD_EXPORT_LEVEL = PermissionLevel.ADMIN
STATUS_LEVEL = PermissionLevel.ADMIN
ROLE_CONFIG_LEVEL = PermissionLevel.SERVER_OWNER

#: Identity lookup is deliberately separated from ordinary moderation.
#: Moderators can punish an account without ever learning who it belongs to.
IDENTITY_LOOKUP_LEVEL = PermissionLevel.BOT_OWNER
FULL_EXPORT_LEVEL = PermissionLevel.BOT_OWNER
BACKUP_LEVEL = PermissionLevel.BOT_OWNER
RESTORE_LEVEL = PermissionLevel.BOT_OWNER
SYSTEM_LEVEL = PermissionLevel.BOT_OWNER


def is_bot_owner(level: PermissionLevel) -> bool:
    return level is PermissionLevel.BOT_OWNER


def is_server_owner(level: PermissionLevel) -> bool:
    return level.meets(PermissionLevel.SERVER_OWNER)


def is_hush_admin(level: PermissionLevel) -> bool:
    return level.meets(PermissionLevel.ADMIN)


def is_hush_moderator(level: PermissionLevel) -> bool:
    return level.meets(PermissionLevel.MODERATOR)


def can_moderate(level: PermissionLevel) -> bool:
    return level.meets(MODERATION_LEVEL)


def can_manage_server(level: PermissionLevel) -> bool:
    return level.meets(CONFIG_LEVEL)


def can_configure_roles(level: PermissionLevel) -> bool:
    return level.meets(ROLE_CONFIG_LEVEL)


def can_export_guild(level: PermissionLevel) -> bool:
    return level.meets(GUILD_EXPORT_LEVEL)


def can_export_everything(level: PermissionLevel) -> bool:
    return level.meets(FULL_EXPORT_LEVEL)


def can_access_sensitive_identity(level: PermissionLevel) -> bool:
    return level.meets(IDENTITY_LOOKUP_LEVEL)


def can_restore_backup(level: PermissionLevel) -> bool:
    return level.meets(RESTORE_LEVEL)
