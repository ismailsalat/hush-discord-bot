"""Backups must be creatable, verifiable and actually restorable."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.backups.manager import DAILY, HOURLY
from app.config.settings import Settings
from app.database.repositories import ConfessionRepository, GuildRepository, UserRepository
from app.database.session import Database
from app.services.backup_service import BackupService
from tests.conftest import GUILD_ID


@pytest.fixture
def live_settings(tmp_path) -> Settings:
    """Backups need a file-backed database, not an in-memory one."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'live.sqlite3'}",
        backup_directory=tmp_path / "backups",
        export_directory=tmp_path / "exports",
        log_directory=tmp_path / "logs",
    )


@pytest.fixture
async def populated(live_settings):
    database = Database(live_settings.database_url)
    await database.create_all()
    async with database.session() as session:
        await GuildRepository(session).get_or_create_settings(
            GUILD_ID, live_settings, name="Backup Test"
        )
        user = await UserRepository(session).get_or_create(555000111)
        from app.database.repositories import AliasRepository

        alias = await AliasRepository(session).create(user.id, GUILD_ID)
        await ConfessionRepository(session).create_pending(
            guild_id=GUILD_ID,
            internal_user_id=user.id,
            alias_id=alias.id,
            content="this must survive",
            content_fingerprint="fp",
        )
    await database.dispose()
    return live_settings


class TestCreation:
    async def test_backup_is_created_and_verified(self, populated):
        service = BackupService(populated)
        record, report = await service.create_and_verify(DAILY)
        assert record.size_bytes > 0
        assert report.ok, report.failures()

    async def test_live_database_is_untouched(self, populated):
        live = Path(populated.database_url.split("///")[-1])
        before = live.read_bytes()
        await BackupService(populated).create(HOURLY)
        assert live.read_bytes() == before

    async def test_backups_are_listed_by_tier(self, populated):
        service = BackupService(populated)
        await service.create(HOURLY)
        await service.create(DAILY)
        assert len(await service.list()) == 2
        assert len(await service.list(HOURLY)) == 1


class TestVerification:
    async def test_verification_checks_content(self, populated):
        service = BackupService(populated)
        record = await service.create(DAILY)
        report = await service.verify(record.name)
        assert report.ok
        assert report.row_counts["confessions"] == 1
        assert report.row_counts["users"] == 1

    async def test_corruption_is_detected(self, populated):
        """A backup that cannot be opened must never be reported as fine."""
        service = BackupService(populated)
        record = await service.create(DAILY)

        archive = Path(populated.backup_directory) / record.name
        data = bytearray(archive.read_bytes())
        data[len(data) // 2] ^= 0xFF
        archive.write_bytes(bytes(data))

        report = await service.verify(record.name)
        assert not report.ok
        assert any("checksum" in failure for failure in report.failures())

    async def test_missing_backup_is_reported(self, populated):
        report = await BackupService(populated).verify("does-not-exist.gz")
        assert not report.ok


class TestRestore:
    async def test_restore_test_succeeds(self, populated):
        service = BackupService(populated)
        record = await service.create(DAILY)
        ok, detail = await service.restore_test(record.name)
        assert ok, detail
        assert "21 tables" in detail

    async def test_restore_does_not_touch_the_live_database(self, populated):
        live = Path(populated.database_url.split("///")[-1])
        service = BackupService(populated)
        record = await service.create(DAILY)
        before = live.read_bytes()
        await service.restore_test(record.name)
        assert live.read_bytes() == before


class TestRetention:
    async def test_old_backups_are_pruned(self, populated):
        from datetime import timedelta

        import json

        from app.utils.time import utcnow

        service = BackupService(populated)
        record = await service.create(HOURLY)

        # Backdate the sidecar beyond the hourly retention window.
        meta = Path(populated.backup_directory) / f"{record.name}.meta.json"
        payload = json.loads(meta.read_text())
        payload["created_at"] = (
            utcnow() - timedelta(hours=populated.backup_hourly_retention_hours + 1)
        ).isoformat()
        meta.write_text(json.dumps(payload))

        removed = await service.prune()
        assert removed.get(HOURLY) == 1
        assert await service.list(HOURLY) == []

    async def test_recent_backups_are_kept(self, populated):
        service = BackupService(populated)
        await service.create(HOURLY)
        await service.prune()
        assert len(await service.list(HOURLY)) == 1


class TestStatus:
    async def test_status_reports_no_backups(self, live_settings):
        ok, detail = await BackupService(live_settings).status()
        assert not ok
        assert "no backups" in detail

    async def test_status_reports_the_latest(self, populated):
        service = BackupService(populated)
        await service.create(DAILY)
        ok, detail = await service.status()
        assert ok
        assert "last backup" in detail
