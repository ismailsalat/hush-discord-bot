"""Thin service wrapper tying backups into commands and scheduled tasks."""

from __future__ import annotations

from pathlib import Path

from app.backups.manager import DAILY, HOURLY, MANUAL, WEEKLY, BackupManager, BackupRecord
from app.backups.providers import LocalBackupProvider
from app.backups.verifier import BackupVerifier, VerificationReport
from app.config.settings import Settings
from app.logging.setup import app_logger
from app.utils.time import ensure_utc, format_duration, utcnow


class BackupService:
    def __init__(self, settings: Settings, manager: BackupManager | None = None):
        self.settings = settings
        provider = LocalBackupProvider(Path(settings.backup_directory))
        self.manager = manager or BackupManager(settings, provider)
        self.verifier = BackupVerifier(self.manager.provider, is_sqlite=settings.is_sqlite)

    async def create(self, tier: str = MANUAL) -> BackupRecord:
        return await self.manager.create(tier)

    async def create_and_verify(self, tier: str = MANUAL) -> tuple[BackupRecord, VerificationReport]:
        """Create a backup and immediately prove it can be opened."""
        record = await self.manager.create(tier)
        report = await self.verifier.verify(record.name)
        if not report.ok:
            app_logger().error(
                "backup_verification_failed", name=record.name, failures=report.failures()
            )
        return record, report

    async def list(self, tier: str | None = None) -> list[BackupRecord]:
        return await self.manager.list(tier)

    async def verify(self, name: str) -> VerificationReport:
        return await self.verifier.verify(name)

    async def restore_test(self, name: str) -> tuple[bool, str]:
        return await self.manager.restore_test(name)

    async def prune(self) -> dict[str, int]:
        return await self.manager.prune()

    async def status(self) -> tuple[bool, str]:
        """Health-check hook: is there a recent, usable backup?"""
        if not self.settings.backup_enabled:
            return True, "backups disabled"
        latest = await self.manager.latest()
        if latest is None:
            return False, "no backups found"
        age = utcnow() - (ensure_utc(latest.created_at) or utcnow())
        return True, f"last backup {format_duration(age)} ago ({latest.size_display})"


__all__ = ["BackupService", "HOURLY", "DAILY", "WEEKLY", "MANUAL"]
