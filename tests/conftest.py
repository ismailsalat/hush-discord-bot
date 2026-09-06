"""Shared test fixtures.

Tests run against an in-memory SQLite database with the real schema, so they
exercise the actual constraints (unique indexes, foreign keys, check
constraints) rather than mocks of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import Settings  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.database.repositories import (  # noqa: E402
    AliasRepository,
    ConfessionRepository,
    GuildRepository,
    UserRepository,
)

GUILD_ID = 900100200300400500
OTHER_GUILD_ID = 900100200300400501


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        backup_directory=tmp_path / "backups",
        export_directory=tmp_path / "exports",
        log_directory=tmp_path / "logs",
        bot_owner_ids=[1],
        brand_name="Hush",
    )


@pytest_asyncio.fixture
async def database(settings) -> Database:
    db = Database(settings.database_url)
    await db.create_all()
    try:
        yield db
    finally:
        await db.dispose()


@pytest_asyncio.fixture
async def session(database):
    async with database.session() as session:
        yield session


@pytest_asyncio.fixture
async def guild(session, settings):
    guilds = GuildRepository(session)
    await guilds.get_or_create_settings(GUILD_ID, settings, name="Test Server")
    # A configured confession channel is a precondition for most flows.
    return await guilds.update_settings(GUILD_ID, confession_channel_id=555000111222)


class Factory:
    """Small helpers so tests read as behaviour, not setup."""

    def __init__(self, session, settings):
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.aliases = AliasRepository(session)
        self.confessions = ConfessionRepository(session)
        self._next_discord_id = 700000000000000000

    async def user(self, discord_id: int | None = None):
        if discord_id is None:
            self._next_discord_id += 1
            discord_id = self._next_discord_id
        return await self.users.get_or_create(discord_id)

    async def member(self, guild_id: int = GUILD_ID, discord_id: int | None = None):
        """A user with a current alias in a guild."""
        user = await self.user(discord_id)
        alias = await self.aliases.get_current(user.id, guild_id)
        if alias is None:
            alias = await self.aliases.create(user.id, guild_id)
        return user, alias

    async def confession(
        self, guild_id: int = GUILD_ID, *, user=None, alias=None, content="a secret",
        parent_confession_id: str | None = None, post: bool = True,
    ):
        if user is None or alias is None:
            user, alias = await self.member(guild_id)
        confession = await self.confessions.create_pending(
            guild_id=guild_id,
            internal_user_id=user.id,
            alias_id=alias.id,
            content=content,
            content_fingerprint=f"fp-{content}-{alias.id}",
            parent_confession_id=parent_confession_id,
        )
        if post:
            await self.confessions.mark_posted(
                confession.id, message_id=abs(hash(confession.id)) % 10**18, channel_id=555
            )
        return confession


@pytest_asyncio.fixture
async def factory(session, settings, guild):
    return Factory(session, settings)
