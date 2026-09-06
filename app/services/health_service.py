"""Modular health checks powering ``/admin health``."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Awaitable, Callable

from sqlalchemy import func, select

from app.database.models import Confession, SystemEvent
from app.database.repositories import DraftRepository, NotificationRepository
from app.database.session import Database
from app.utils.time import format_duration, utcnow


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str | None = None

    @property
    def icon(self) -> str:
        return "\u2705" if self.ok else "\u274c"


@dataclass(slots=True)
class HealthReport:
    checks: list[HealthCheck] = field(default_factory=list)
    metrics: dict[str, str] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return all(check.ok for check in self.checks)

    def add(self, name: str, ok: bool, detail: str | None = None) -> None:
        self.checks.append(HealthCheck(name, ok, detail))


#: A check is any awaitable returning ``(ok, detail)``. New checks plug in here.
CheckFn = Callable[[], Awaitable[tuple[bool, str | None]]]


class HealthService:
    def __init__(self, database: Database, *, started_at=None):
        self.database = database
        self.started_at = started_at or utcnow()
        self._extra_checks: dict[str, CheckFn] = {}

    def register(self, name: str, check: CheckFn) -> None:
        """Register an additional check (Discord API, backups, channels...)."""
        self._extra_checks[name] = check

    async def run(self) -> HealthReport:
        report = HealthReport()

        database_ok = await self.database.healthcheck()
        report.add("Database", database_ok)

        for name, check in self._extra_checks.items():
            try:
                ok, detail = await check()
            except Exception as exc:  # a failing check must not break the command
                ok, detail = False, f"check failed: {type(exc).__name__}"
            report.add(name, ok, detail)

        if database_ok:
            async with self.database.session() as session:
                pending = await NotificationRepository(session).count_pending()
                drafts = await DraftRepository(session).count_active()

                total_confessions = await session.scalar(
                    select(func.count()).select_from(Confession)
                )
                since = utcnow() - timedelta(hours=1)
                recent_errors = await session.scalar(
                    select(func.count())
                    .select_from(SystemEvent)
                    .where(SystemEvent.level == "ERROR", SystemEvent.created_at >= since)
                )

            report.metrics["Pending notifications"] = str(pending)
            report.metrics["Active drafts"] = str(drafts)
            report.metrics["Confessions"] = str(total_confessions or 0)
            report.metrics["Errors last hour"] = str(recent_errors or 0)

        report.metrics["Uptime"] = format_duration(utcnow() - self.started_at)
        return report
