"""Private bookmarks. Never surfaced to anyone but their owner."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, CreatedAtMixin, IdType
from app.security.identifiers import new_id


class Bookmark(Base, CreatedAtMixin):
    __tablename__ = "bookmarks"
    __table_args__ = (
        UniqueConstraint("internal_user_id", "confession_id", name="uq_bookmark_user_confession"),
        Index("ix_bookmark_user", "internal_user_id"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("bmk_"))
    internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    confession_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("confessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
