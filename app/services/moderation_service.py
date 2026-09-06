"""Moderator actions.

Every action here works on an *internal user id*. A moderator can warn, ban and
remove without ever learning who the account belongs to. Identity lookup is a
separate, owner-only, always-logged capability that lives in
:mod:`app.services.identity_service`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.core.constants import BanDuration, LedgerAction, ReportReason, ReportStatus
from app.core.exceptions import (
    AlreadyReportedError,
    ConfessionNotFoundError,
    RateLimitedError,
)
from app.database.models import Ban, ModerationWarning, Report
from app.database.repositories import (
    AliasRepository,
    ConfessionRepository,
    ModerationRepository,
    ReportRepository,
)
from app.logging.audit import log_moderation
from app.security.identifiers import format_alias
from app.services.confession_service import ConfessionService
from app.services.dto import PunishmentHistory
from app.services.notification_service import NotificationService
from app.utils.time import in_hours, utcnow


@dataclass(frozen=True, slots=True)
class ModerationOutcome:
    ok: bool
    record_id: str | None = None
    alias_display: str | None = None
    detail: str | None = None


class ModerationService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.moderation = ModerationRepository(session)
        self.reports = ReportRepository(session)
        self.confessions = ConfessionRepository(session)
        self.aliases = AliasRepository(session)
        self.notifications = NotificationService(session)
        self.confession_service = ConfessionService(session, settings)

    # --- Reports -----------------------------------------------------------

    async def report(
        self,
        *,
        confession_id: str,
        reporter_internal_user_id: str,
        reason: ReportReason,
        details: str | None = None,
    ) -> Report:
        """File a report. This never removes anything - humans decide."""
        confession = await self.confessions.get_by_id(confession_id)
        if confession is None or confession.is_deleted:
            raise ConfessionNotFoundError()

        if await self.reports.get_existing(confession_id, reporter_internal_user_id) is not None:
            raise AlreadyReportedError()

        recent = await self.reports.count_recent_by_reporter(reporter_internal_user_id, minutes=60)
        if recent >= self.settings.rate_limit_reports_per_hour:
            raise RateLimitedError(3600, "reporting")

        report = await self.reports.create(
            confession_id=confession_id,
            reporter_internal_user_id=reporter_internal_user_id,
            guild_id=confession.guild_id,
            reason=reason,
            details=details,
        )
        await self.moderation.record(
            LedgerAction.REPORT_CREATED,
            guild_id=confession.guild_id,
            confession_id=confession_id,
            meta={"reason": reason.value, "report_id": report.id},
        )
        log_moderation(
            "REPORT_CREATED", guild_id=confession.guild_id, confession_id=confession_id,
            reason=reason.value,
        )
        return report

    async def open_reports(self, guild_id: int, limit: int = 25):
        return await self.reports.list_open(guild_id, limit=limit)

    async def resolve_report(
        self, report_id: str, *, moderator_id: int, dismissed: bool = False, note: str | None = None
    ) -> Report | None:
        status = ReportStatus.DISMISSED if dismissed else ReportStatus.RESOLVED
        report = await self.reports.resolve(
            report_id, moderator_id=moderator_id, status=status, note=note
        )
        if report is not None:
            await self.moderation.record(
                LedgerAction.REPORT_RESOLVED,
                guild_id=report.guild_id,
                confession_id=report.confession_id,
                moderator_id=moderator_id,
                reason=note,
                meta={"report_id": report_id, "status": status.value},
            )
        return report

    # --- Removal -----------------------------------------------------------

    async def remove_confession(
        self, confession_id: str, *, moderator_id: int, reason: str, guild_name: str | None = None
    ) -> ModerationOutcome:
        confession = await self.confession_service.get(confession_id)
        alias = await self.aliases.get(confession.alias_id)

        await self.confession_service.remove(
            confession_id, moderator_id=moderator_id, reason=reason
        )
        await self.reports.resolve_for_confession(
            confession_id, moderator_id=moderator_id, note="confession removed"
        )
        await self.notifications.queue_confession_removed(
            internal_user_id=confession.internal_user_id,
            guild_id=confession.guild_id,
            public_number=confession.public_number,
            reason=reason,
        )
        log_moderation(
            "CONFESSION_REMOVED", guild_id=confession.guild_id, confession_id=confession_id,
            moderator_id=moderator_id,
        )
        return ModerationOutcome(
            ok=True,
            record_id=confession_id,
            alias_display=format_alias(alias.public_alias) if alias else None,
            detail=f"Confession #{confession.public_number} removed",
        )

    # --- Warnings ----------------------------------------------------------

    async def warn(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        moderator_id: int,
        reason: str,
        related_confession_id: str | None = None,
        guild_name: str | None = None,
    ) -> ModerationWarning:
        warning = await self.moderation.create_warning(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            moderator_id=moderator_id,
            reason=reason,
            related_confession_id=related_confession_id,
        )
        await self.moderation.record(
            LedgerAction.WARNING_CREATED,
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            moderator_id=moderator_id,
            confession_id=related_confession_id,
            reason=reason,
            meta={"warning_id": warning.id},
        )
        # Queued, not sent: delivery is retried and replayed if DMs are closed.
        await self.notifications.queue_warning(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            warning_id=warning.id,
            reason=reason,
            guild_name=guild_name,
        )
        log_moderation(
            "WARNING_CREATED", guild_id=guild_id, internal_user_id=internal_user_id,
            moderator_id=moderator_id,
        )
        return warning

    async def acknowledge_warning(self, warning_id: str) -> ModerationWarning | None:
        warning = await self.moderation.acknowledge_warning(warning_id)
        if warning is not None:
            await self.moderation.record(
                LedgerAction.WARNING_ACKNOWLEDGED,
                internal_user_id=warning.internal_user_id,
                guild_id=warning.guild_id,
                meta={"warning_id": warning_id},
            )
        return warning

    async def revoke_warning(self, warning_id: str, moderator_id: int) -> ModerationWarning | None:
        warning = await self.moderation.revoke_warning(warning_id, moderator_id)
        if warning is not None:
            await self.moderation.record(
                LedgerAction.WARNING_REVOKED,
                internal_user_id=warning.internal_user_id,
                guild_id=warning.guild_id,
                moderator_id=moderator_id,
                meta={"warning_id": warning_id},
            )
            await self.notifications.dismiss_warning_notice(
                warning.internal_user_id, warning_id
            )
        return warning

    # --- Bans --------------------------------------------------------------

    async def ban(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        moderator_id: int,
        reason: str,
        duration: BanDuration,
        guild_name: str | None = None,
    ) -> Ban:
        """Apply a Hush feature ban. Never touches Discord membership."""
        is_permanent = duration is BanDuration.PERMANENT
        expires_at: datetime | None = None if is_permanent else in_hours(duration.hours or 24)

        ban = await self.moderation.create_ban(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            moderator_id=moderator_id,
            reason=reason,
            expires_at=expires_at,
            is_permanent=is_permanent,
        )
        await self.moderation.record(
            LedgerAction.PERMANENT_BAN_CREATED if is_permanent else LedgerAction.TEMP_BAN_CREATED,
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            moderator_id=moderator_id,
            reason=reason,
            meta={
                "ban_id": ban.id,
                "duration": duration.value,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
        await self.notifications.queue_ban(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            ban_id=ban.id,
            reason=reason,
            duration_label=duration.label,
            expires_at=expires_at.isoformat() if expires_at else None,
            guild_name=guild_name,
        )
        log_moderation(
            "PERMANENT_BAN_CREATED" if is_permanent else "TEMP_BAN_CREATED",
            guild_id=guild_id, internal_user_id=internal_user_id, moderator_id=moderator_id,
            duration=duration.value,
        )
        return ban

    async def revoke_ban(
        self,
        ban_id: str,
        moderator_id: int,
        *,
        guild_name: str | None = None,
    ) -> Ban | None:
        ban = await self.moderation.revoke_ban(ban_id, moderator_id)
        if ban is not None:
            await self.moderation.record(
                LedgerAction.BAN_REVOKED,
                internal_user_id=ban.internal_user_id,
                guild_id=ban.guild_id,
                moderator_id=moderator_id,
                meta={"ban_id": ban_id},
            )
            # If the original ban DM never arrived, do not replay an obsolete
            # blocking notice after the ban has already been revoked.
            await self.notifications.dismiss_ban_notice(
                ban.internal_user_id, ban_id
            )
            await self.notifications.queue_ban_revoked(
                internal_user_id=ban.internal_user_id,
                guild_id=ban.guild_id,
                guild_name=guild_name,
            )
        return ban

    async def expire_due_bans(self) -> int:
        """Log temporary bans that have lapsed. Called by the background task."""
        expired = await self.moderation.list_newly_expired_bans()
        for ban in expired:
            await self.moderation.record(
                LedgerAction.TEMP_BAN_EXPIRED,
                internal_user_id=ban.internal_user_id,
                guild_id=ban.guild_id,
                meta={"ban_id": ban.id, "expired_at": utcnow().isoformat()},
            )
        return len(expired)

    # --- History -----------------------------------------------------------

    async def punishment_history(
        self, internal_user_id: str, guild_id: int
    ) -> PunishmentHistory:
        """Account history for moderators - identity-free by construction."""
        alias = await self.aliases.get_current(internal_user_id, guild_id)
        warnings = await self.moderation.list_warnings(internal_user_id, guild_id)
        bans = await self.moderation.list_bans(internal_user_id, guild_id)
        confessions = await self.confessions.list_for_user(internal_user_id, guild_id)
        reports = await self.reports.list_involving_user(internal_user_id)

        entries: list[str] = []
        for warning in warnings[:5]:
            state = "revoked" if warning.revoked_at else (
                "acknowledged" if warning.acknowledged_at else "pending"
            )
            entries.append(f"Warning ({state}): {warning.reason[:60]}")
        for ban in bans[:5]:
            label = "Permanent ban" if ban.is_permanent else "Temporary ban"
            state = "revoked" if ban.revoked_at else ("active" if ban.is_active else "expired")
            entries.append(f"{label} ({state}): {ban.reason[:60]}")

        return PunishmentHistory(
            alias_display=format_alias(alias.public_alias) if alias else "Unknown",
            warning_count=len(warnings),
            active_warnings=sum(1 for w in warnings if w.is_active),
            temp_ban_count=sum(1 for b in bans if not b.is_permanent),
            permanent_ban_count=sum(1 for b in bans if b.is_permanent),
            is_currently_banned=await self.moderation.get_active_ban(internal_user_id, guild_id)
            is not None,
            removed_confession_count=sum(1 for c in confessions if c.is_deleted),
            report_count=len(reports),
            entries=entries,
        )
