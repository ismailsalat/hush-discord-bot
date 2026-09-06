"""Housekeeping jobs: expiry, cleanup, reconciliation, backups and metrics."""

from __future__ import annotations

from app.backups.manager import DAILY, HOURLY, WEEKLY
from app.core.constants import ConfessionStatus, ReportStatus
from app.logging.audit import log_metric
from app.logging.setup import app_logger
from app.utils.time import utcnow


class MaintenanceTasks:
    def __init__(self, runtime, client=None):
        self.runtime = runtime
        self.client = client

    # --- Moderation ---------------------------------------------------------

    async def expire_bans(self) -> str | None:
        """Lift temporary bans whose time is up, and tell the user."""
        from app.services.moderation_service import ModerationService

        async with self.runtime.session() as session:
            expired = await ModerationService(
                session, self.runtime.settings
            ).expire_due_bans()
        return f"{expired} ban(s) expired" if expired else None

    # --- Cleanup ------------------------------------------------------------

    async def cleanup(self) -> str | None:
        """Delete expired drafts and export files."""
        from app.database.repositories import DraftRepository
        from app.services.export_service import ExportService

        async with self.runtime.session() as session:
            drafts = await DraftRepository(session).delete_expired()
            exports = await ExportService(session, self.runtime.settings).cleanup_expired()

        if drafts or exports:
            return f"removed {drafts} draft(s), {exports} export file(s)"
        return None

    # --- Consistency --------------------------------------------------------

    async def reconcile(self) -> str | None:
        """Repair confessions stuck between the database and Discord.

        A PENDING row older than a few minutes means the process died between
        writing the record and posting the message. Rather than leave a ghost,
        the row is marked FAILED and the author's text is preserved as a draft
        so they can simply try again.
        """
        from app.database.repositories import ConfessionRepository, DraftRepository

        repaired = 0
        async with self.runtime.session() as session:
            confessions = ConfessionRepository(session)
            drafts = DraftRepository(session)

            for confession in await confessions.find_pending(older_than_minutes=5):
                await drafts.save(
                    internal_user_id=confession.internal_user_id,
                    guild_id=confession.guild_id,
                    content=confession.content,
                    expiry_minutes=self.runtime.settings.draft_expiry_minutes,
                    parent_confession_id=confession.parent_confession_id,
                    last_error="recovered_after_restart",
                )
                await confessions.mark_failed(confession.id)
                repaired += 1

        if repaired:
            app_logger().warning("confessions_reconciled", count=repaired)
            return f"reconciled {repaired} stuck confession(s)"
        return None

    # --- Backups ------------------------------------------------------------

    async def hourly_backup(self) -> str | None:
        return await self._backup(HOURLY)

    async def daily_backup(self) -> str | None:
        return await self._backup(DAILY)

    async def weekly_backup(self) -> str | None:
        result = await self._backup(WEEKLY)
        pruned = await self.runtime.backups.prune()
        if pruned:
            return f"{result or 'backup created'}; pruned {pruned}"
        return result

    async def _backup(self, tier: str) -> str | None:
        if not self.runtime.settings.backup_enabled:
            return None
        record, report = await self.runtime.backups.create_and_verify(tier)
        if not report.ok:
            app_logger().error(
                "backup_unverified", name=record.name, failures=report.failures()
            )
            return f"{record.name} FAILED verification"
        return f"{record.name} ({record.size_display}) verified"

    # --- Metrics ------------------------------------------------------------

    async def metrics(self) -> None:
        """Write a periodic snapshot to the metrics log."""
        from sqlalchemy import func, select

        from app.database.models import Confession, Report, User

        async with self.runtime.session() as session:
            confessions = await session.scalar(
                select(func.count())
                .select_from(Confession)
                .where(Confession.status == ConfessionStatus.POSTED)
            )
            users = await session.scalar(select(func.count()).select_from(User))
            open_reports = await session.scalar(
                select(func.count()).select_from(Report).where(Report.status == ReportStatus.OPEN)
            )
            from app.database.repositories import NotificationRepository

            pending_notifications = await NotificationRepository(session).count_pending()

        log_metric(
            "snapshot",
            confessions=confessions or 0,
            users=users or 0,
            open_reports=open_reports or 0,
            pending_notifications=pending_notifications,
            guilds=len(self.client.guilds) if self.client else 0,
            uptime_seconds=int((utcnow() - self.runtime.started_at).total_seconds()),
        )
