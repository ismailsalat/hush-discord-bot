"""Public anonymous aliases and their history.

An alias is the *only* identity server members ever see. Rotating an alias
retires the old row and creates a new one; both rows point at the same internal
user, but nothing public connects them. That link is visible to the system and
privileged staff only - which is what makes the privacy reset real for members
while keeping the account accountable to moderators.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdType, Snowflake
from app.security.identifiers import format_alias, new_alias_id
from app.utils.time import utcnow


class AnonAlias(Base):
    """One public identity for one user in one guild."""

    __tablename__ = "anon_aliases"
    __table_args__ = (
        # An alias body is never reused inside a guild, even after retirement,
        # so an old profile can never be confused with a different person.
        UniqueConstraint("guild_id", "public_alias", name="uq_alias_guild_public"),
        # At most one *current* alias per user per guild. This must be a
        # partial index: a user legitimately owns many aliases over time, but
        # only ever one live one.
        Index(
            "uq_alias_current_per_user",
            "internal_user_id",
            "guild_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current = true"),
        ),
        Index("ix_alias_user_guild", "internal_user_id", "guild_id"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_alias_id)
    internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )

    #: Body only, e.g. ``A17``. Rendered as ``Anon #A17``.
    public_alias: Mapped[str] = mapped_column(String(8), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    rotation_reason: Mapped[str | None] = mapped_column(String(200), default=None)
    is_current: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    @property
    def display(self) -> str:
        return format_alias(self.public_alias)
