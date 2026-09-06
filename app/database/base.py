"""Declarative base, shared column types and mixins."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, JSON, MetaData, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils.time import utcnow

#: Explicit constraint naming so Alembic can autogenerate stable migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: JSONB on PostgreSQL, plain JSON everywhere else (SQLite dev/test).
JSONType = JSON().with_variant(postgresql.JSONB(), "postgresql")

#: Discord snowflakes exceed 32 bits; SQLite maps BigInteger to INTEGER.
Snowflake = BigInteger().with_variant(Integer(), "sqlite")

#: Prefixed random identifiers such as ``conf_f82c9d1a4b6e0357``.
IdType = String(64)


class Base(DeclarativeBase):
    """Root declarative class for every Hush model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        dict[str, Any]: JSONType,
        list[int]: JSONType,
    }

    def to_dict(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Serialise columns to plain Python (used by the export layer)."""
        exclude = exclude or set()
        result: dict[str, Any] = {}
        for column in self.__table__.columns:
            if column.name in exclude:
                continue
            value = getattr(self, column.name)
            result[column.name] = value.isoformat() if isinstance(value, datetime) else value
        return result

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier!r}>"


class TimestampMixin:
    """``created_at`` / ``updated_at`` in UTC on every mutable table."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CreatedAtMixin:
    """``created_at`` only - for append-only tables that are never updated."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


def enum_column(enum_class: type, length: int = 40):
    """Portable enum column.

    Stored as VARCHAR with a CHECK constraint rather than a native PostgreSQL
    ENUM: adding a value later becomes an ordinary migration instead of an
    ``ALTER TYPE`` that locks the table.
    """
    from sqlalchemy import Enum as SAEnum

    return SAEnum(
        enum_class,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )
