"""Report storage and the moderator review queue."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.core.constants import ReportReason, ReportStatus
from app.database.models import Confession, Report
from app.database.repositories.base import BaseRepository
from app.utils.time import utcnow


class ReportRepository(BaseRepository):
    async def get(self, report_id: str) -> Report | None:
        return await self.session.get(Report, report_id)

    async def get_existing(self, confession_id: str, reporter_internal_user_id: str) -> Report | None:
        result = await self.session.execute(
            select(Report).where(
                Report.confession_id == confession_id,
                Report.reporter_internal_user_id == reporter_internal_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        confession_id: str,
        reporter_internal_user_id: str,
        guild_id: int,
        reason: ReportReason,
        details: str | None,
    ) -> Report:
        report = Report(
            confession_id=confession_id,
            reporter_internal_user_id=reporter_internal_user_id,
            guild_id=guild_id,
            reason=reason,
            details=details,
        )
        self.session.add(report)
        await self.session.flush()
        return report

    async def count_recent_by_reporter(
        self, reporter_internal_user_id: str, *, minutes: int = 60
    ) -> int:
        """Durable half of report-spam protection (survives a restart)."""
        cutoff = utcnow() - timedelta(minutes=minutes)
        result = await self.session.execute(
            select(func.count())
            .select_from(Report)
            .where(
                Report.reporter_internal_user_id == reporter_internal_user_id,
                Report.created_at >= cutoff,
            )
        )
        return int(result.scalar_one())

    async def list_open(self, guild_id: int, *, limit: int = 25) -> list[tuple[Report, Confession]]:
        result = await self.session.execute(
            select(Report, Confession)
            .join(Confession, Confession.id == Report.confession_id)
            .where(Report.guild_id == guild_id, Report.status == ReportStatus.OPEN)
            .order_by(Report.created_at.asc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def count_open(self, guild_id: int) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Report)
            .where(Report.guild_id == guild_id, Report.status == ReportStatus.OPEN)
        )
        return int(result.scalar_one())

    async def count_for_confession(self, confession_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Report).where(Report.confession_id == confession_id)
        )
        return int(result.scalar_one())

    async def resolve(
        self, report_id: str, *, moderator_id: int, status: ReportStatus, note: str | None = None
    ) -> Report | None:
        report = await self.get(report_id)
        if report is None:
            return None
        report.status = status
        report.resolved_by = moderator_id
        report.resolved_at = utcnow()
        report.resolution_note = note
        await self.session.flush()
        return report

    async def resolve_for_confession(
        self, confession_id: str, *, moderator_id: int, note: str | None = None
    ) -> int:
        """Close every open report on a confession once it has been actioned."""
        result = await self.session.execute(
            select(Report).where(
                Report.confession_id == confession_id, Report.status == ReportStatus.OPEN
            )
        )
        reports = list(result.scalars().all())
        for report in reports:
            report.status = ReportStatus.RESOLVED
            report.resolved_by = moderator_id
            report.resolved_at = utcnow()
            report.resolution_note = note
        await self.session.flush()
        return len(reports)

    async def list_for_guild(self, guild_id: int) -> list[Report]:
        result = await self.session.execute(
            select(Report).where(Report.guild_id == guild_id).order_by(Report.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_involving_user(self, internal_user_id: str) -> list[Report]:
        """Reports filed against this user's confessions."""
        result = await self.session.execute(
            select(Report)
            .join(Confession, Confession.id == Report.confession_id)
            .where(Confession.internal_user_id == internal_user_id)
            .order_by(Report.created_at.desc())
        )
        return list(result.scalars().all())
