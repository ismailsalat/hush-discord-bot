"""Private bookmarks. Nobody can see who saved what."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConfessionNotFoundError, FeatureDisabledError
from app.database.repositories import BookmarkRepository, ConfessionRepository, GuildRepository
from app.utils.text import one_line


class BookmarkService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.bookmarks = BookmarkRepository(session)
        self.confessions = ConfessionRepository(session)
        self.guilds = GuildRepository(session)

    async def toggle(self, *, internal_user_id: str, confession_id: str) -> bool:
        """Save/unsave. Returns True when the confession is now saved."""
        confession = await self.confessions.get_by_id(confession_id)
        if confession is None or confession.is_deleted:
            raise ConfessionNotFoundError()

        settings = await self.guilds.get_settings(confession.guild_id)
        if settings is not None and not settings.bookmarks_enabled:
            raise FeatureDisabledError(user_message="Bookmarks are turned off in this server.")

        if await self.bookmarks.get(internal_user_id, confession_id) is not None:
            await self.bookmarks.delete(internal_user_id, confession_id)
            return False
        await self.bookmarks.create(internal_user_id, confession_id)
        return True

    async def is_bookmarked(self, internal_user_id: str, confession_id: str) -> bool:
        return await self.bookmarks.get(internal_user_id, confession_id) is not None

    async def list_rows(
        self, internal_user_id: str, guild_id: int | None = None
    ) -> list[tuple[int, str, str, str]]:
        """``(number, alias_display, preview, confession_id)`` for the list embed."""
        from app.database.repositories import AliasRepository
        from app.security.identifiers import format_alias

        aliases = AliasRepository(self.session)
        rows: list[tuple[int, str, str, str]] = []
        for _bookmark, confession in await self.bookmarks.list_for_user(internal_user_id, guild_id):
            alias = await aliases.get(confession.alias_id)
            rows.append(
                (
                    confession.public_number,
                    format_alias(alias.public_alias) if alias else "Anon",
                    one_line(confession.content, 46),
                    confession.id,
                )
            )
        return rows
