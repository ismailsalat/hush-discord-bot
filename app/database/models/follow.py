"""Follows target a public *alias*, never a user.

This is what makes alias rotation a genuine privacy reset: followers are
attached to the retired alias row and are never carried across to the new one.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdType, Snowflake, TimestampMixin
from app.security.identifiers import new_id


class Follow(Base, TimestampMixin):
    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("follower_internal_user_id", "alias_id", name="uq_follow_follower_alias"),
        Index("ix_follow_alias", "alias_id"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("fol_"))
    follower_internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("anon_aliases.id", ondelete="CASCADE"), nullable=False
    )
    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )
    notifications_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
