"""Async engine and session management.

Services receive an ``AsyncSession`` and never build their own engine. The
``session()`` context manager owns the transaction boundary: it commits on
success and rolls back on any exception, so a service can never leave a
half-applied write behind.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config.settings import Settings
from app.core.exceptions import DatabaseOperationError
from app.logging.setup import app_logger


class Database:
    """Owns the engine and hands out sessions."""

    def __init__(self, url: str, *, echo: bool = False, pool_size: int = 10,
                 max_overflow: int = 20, in_memory: bool = False):
        self.url = url
        self._is_sqlite = url.startswith("sqlite")

        kwargs: dict = {"echo": echo, "future": True}
        if self._is_sqlite:
            # SQLite has no real pooling; an in-memory DB must reuse one
            # connection or each session would see an empty database.
            if in_memory or ":memory:" in url:
                kwargs["poolclass"] = StaticPool
                kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["pool_size"] = pool_size
            kwargs["max_overflow"] = max_overflow
            kwargs["pool_pre_ping"] = True

        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        return cls(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
        )

    @property
    def is_sqlite(self) -> bool:
        return self._is_sqlite

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Transactional session scope: commit on success, rollback on error."""
        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            app_logger().error("database_error", error=str(exc), error_type=type(exc).__name__)
            raise DatabaseOperationError(str(exc)) from exc
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def create_all(self) -> None:
        """Create the schema directly. Tests and first-run SQLite only.

        Production schema changes always go through Alembic.
        """
        from app.database import models  # noqa: F401  (registers every mapper)
        from app.database.base import Base

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        from app.database import models  # noqa: F401
        from app.database.base import Base

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def healthcheck(self) -> bool:
        """True when a trivial query succeeds."""
        from sqlalchemy import text

        try:
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()


_database: Database | None = None


def set_database(database: Database) -> None:
    global _database
    _database = database


def get_database() -> Database:
    if _database is None:
        raise RuntimeError("database has not been initialised")
    return _database
