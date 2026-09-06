"""Internal identity.

``User.id`` is the immutable internal identifier (``usr_...``). It is generated
randomly, never changes, and is never shown publicly. The Discord user id lives
only in this table - every other table references the internal id, so no other
table can be used to work out who someone is.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdType, Snowflake, TimestampMixin
from app.security.identifiers import new_id, new_internal_user_id


class User(Base, TimestampMixin):
    """One row per Discord user known to Hush."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_internal_user_id)

    #: The only place the Discord identity is stored.
    discord_user_id: Mapped[int] = mapped_column(Snowflake, unique=True, nullable=False, index=True)

    #: Global lock applied by the bot owner, independent of any guild ban.
    is_globally_blocked: Mapped[bool] = mapped_column(default=False, nullable=False)

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class GuildMembership(Base, TimestampMixin):
    """Links an internal user to a guild they have used Hush in.

    Used to resolve which servers a user can confess to from DMs without
    depending on the privileged members intent.
    """

    __tablename__ = "guild_memberships"
    __table_args__ = (
        UniqueConstraint("internal_user_id", "guild_id", name="uq_membership_user_guild"),
        Index("ix_membership_guild", "guild_id"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("mem_"))
    internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
