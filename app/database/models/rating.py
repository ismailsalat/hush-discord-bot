"""Ratings: one per user per confession, updated in place when changed."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdType, TimestampMixin
from app.security.identifiers import new_id


class Rating(Base, TimestampMixin):
    __tablename__ = "ratings"
    __table_args__ = (
        # The database, not application logic, is what guarantees one vote each.
        UniqueConstraint("confession_id", "voter_internal_user_id", name="uq_rating_confession_voter"),
        Index("ix_rating_confession", "confession_id"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("rat_"))
    confession_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("confessions.id", ondelete="CASCADE"), nullable=False
    )
    voter_internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[int] = mapped_column(nullable=False)
