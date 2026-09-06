"""Export bookkeeping. Every generated export is recorded and expires."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.constants import ExportFormat, ExportScope
from app.database.models import ExportRecord
from app.database.repositories.base import BaseRepository
from app.utils.time import in_hours, utcnow


class ExportRepository(BaseRepository):
    async def create(
        self,
        *,
        requested_by_discord_id: int,
        scope: ExportScope,
        export_format: ExportFormat,
        guild_id: int | None = None,
        target: str | None = None,
        file_path: str | None = None,
        size_bytes: int | None = None,
        row_counts: dict[str, Any] | None = None,
        retention_hours: int = 24,
    ) -> ExportRecord:
        record = ExportRecord(
            requested_by_discord_id=requested_by_discord_id,
            scope=scope,
            export_format=export_format,
            guild_id=guild_id,
            target=target,
            file_path=file_path,
            size_bytes=size_bytes,
            row_counts=row_counts,
            expires_at=in_hours(retention_hours),
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_expired(self) -> list[ExportRecord]:
        result = await self.session.execute(
            select(ExportRecord).where(
                ExportRecord.expires_at <= utcnow(), ExportRecord.deleted_at.is_(None)
            )
        )
        return list(result.scalars().all())

    async def mark_deleted(self, export_id: str) -> None:
        record = await self.session.get(ExportRecord, export_id)
        if record is not None:
            record.deleted_at = utcnow()
            await self.session.flush()

    async def list_recent(self, *, limit: int = 25) -> list[ExportRecord]:
        result = await self.session.execute(
            select(ExportRecord).order_by(ExportRecord.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())
