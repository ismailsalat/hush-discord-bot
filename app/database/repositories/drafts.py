"""Draft persistence so a failed post never costs someone their text."""

from __future__ import annotations

from sqlalchemy import delete, func, select

from app.database.models import Draft
from app.database.repositories.base import BaseRepository
from app.utils.time import in_minutes, utcnow


class DraftRepository(BaseRepository):
    async def get(self, draft_id: str) -> Draft | None:
        return await self.session.get(Draft, draft_id)

    async def get_for_user(self, internal_user_id: str, guild_id: int) -> Draft | None:
        result = await self.session.execute(
            select(Draft).where(
                Draft.internal_user_id == internal_user_id,
                Draft.guild_id == guild_id,
                Draft.expires_at > utcnow(),
            )
        )
        return result.scalar_one_or_none()

    async def save(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        content: str,
        expiry_minutes: int = 30,
        parent_confession_id: str | None = None,
        last_error: str | None = None,
    ) -> Draft:
        """Create or refresh the single live draft for this user and guild."""
        result = await self.session.execute(
            select(Draft).where(
                Draft.internal_user_id == internal_user_id, Draft.guild_id == guild_id
            )
        )
        draft = result.scalar_one_or_none()
        if draft is None:
            draft = Draft(
                internal_user_id=internal_user_id,
                guild_id=guild_id,
                content=content,
                expires_at=in_minutes(expiry_minutes),
                parent_confession_id=parent_confession_id,
                last_error=last_error,
            )
            self.session.add(draft)
        else:
            draft.content = content
            draft.expires_at = in_minutes(expiry_minutes)
            draft.parent_confession_id = parent_confession_id
            draft.last_error = last_error
        await self.session.flush()
        return draft

    async def delete_for_user(self, internal_user_id: str, guild_id: int) -> bool:
        result = await self.session.execute(
            delete(Draft).where(
                Draft.internal_user_id == internal_user_id, Draft.guild_id == guild_id
            )
        )
        return bool(result.rowcount)

    async def delete_expired(self) -> int:
        result = await self.session.execute(delete(Draft).where(Draft.expires_at <= utcnow()))
        return int(result.rowcount or 0)

    async def count_active(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Draft).where(Draft.expires_at > utcnow())
        )
        return int(result.scalar_one())
