"""Backup creation, retention and restore-testing.

SQLite snapshots use ``VACUUM INTO``, which produces a consistent copy without
stopping writes. PostgreSQL uses ``pg_dump``. Both are then gzipped and handed
to a :class:`BackupProvider`.
"""

from __future__ import annotations

import asyncio
import gzip
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.engine import make_url

from app.backups.providers import BackupProvider, LocalBackupProvider, StoredBackup
from app.config.settings import Settings
from app.core.exceptions import BackupError
from app.logging.setup import app_logger

HOURLY = "hourly"
DAILY = "daily"
WEEKLY = "weekly"
MANUAL = "manual"
TIERS = (HOURLY, DAILY, WEEKLY, MANUAL)


@dataclass(frozen=True, slots=True)
class BackupRecord:
    name: str
    tier: str
    size_bytes: int
    created_at: datetime
    checksum: str | None

    @property
    def size_display(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


def sqlite_path_from_url(url: str) -> Path:
    """Extract the file path from a SQLAlchemy SQLite URL.

    Uses SQLAlchemy's own parser rather than slicing slashes by hand. Hand
    parsing breaks on Windows, where ``sqlite:///C:/Users/...`` must keep its
    drive letter - stripping the leading slash naively produced ``\\C:\\Users``
    and the backup could never find the database.
    """
    database = make_url(url).database
    if not database:
        raise BackupError(f"no database file in URL: {url}")
    return Path(database)


class BackupManager:
    def __init__(self, settings: Settings, provider: BackupProvider | None = None):
        self.settings = settings
        self.provider = provider or LocalBackupProvider(Path(settings.backup_directory))

    @property
    def is_sqlite(self) -> bool:
        return self.settings.is_sqlite

    # --- Creation ----------------------------------------------------------

    async def create(self, tier: str = MANUAL) -> BackupRecord:
        """Create and store one compressed backup."""
        if tier not in TIERS:
            raise BackupError(f"unknown backup tier: {tier}")

        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        suffix = "sqlite" if self.is_sqlite else "sql"
        name = f"hush-{tier}-{stamp}.{suffix}.gz"

        with tempfile.TemporaryDirectory(prefix="hush-backup-") as workspace:
            raw = Path(workspace) / f"dump.{suffix}"
            if self.is_sqlite:
                await self._dump_sqlite(raw)
            else:
                await self._dump_postgres(raw)

            compressed = Path(workspace) / name
            await asyncio.to_thread(self._compress, raw, compressed)
            stored = await self.provider.store(compressed, name, tier)

        app_logger().info(
            "backup_created", name=stored.name, tier=tier, size_bytes=stored.size_bytes
        )
        return self._to_record(stored)

    async def _dump_sqlite(self, destination: Path) -> None:
        """``VACUUM INTO`` gives a consistent snapshot of a live database."""
        source = sqlite_path_from_url(self.settings.database_url)
        if not source.exists():
            raise BackupError(f"sqlite database not found: {source}")

        def _vacuum() -> None:
            connection = sqlite3.connect(str(source))
            try:
                connection.execute("VACUUM INTO ?", (str(destination),))
            finally:
                connection.close()

        await asyncio.to_thread(_vacuum)

    async def _dump_postgres(self, destination: Path) -> None:
        parsed = urlparse(self.settings.database_url.replace("+asyncpg", ""))
        if shutil.which("pg_dump") is None:
            raise BackupError(
                "pg_dump is not installed",
                user_message="Backups need the PostgreSQL client tools (pg_dump) installed.",
            )

        environment = os.environ.copy()
        if parsed.password:
            environment["PGPASSWORD"] = parsed.password

        command = [
            "pg_dump",
            "--host", parsed.hostname or "localhost",
            "--port", str(parsed.port or 5432),
            "--username", parsed.username or "postgres",
            "--dbname", (parsed.path or "/hush").lstrip("/"),
            "--no-owner", "--no-privileges",
            "--file", str(destination),
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise BackupError(f"pg_dump failed: {stderr.decode(errors='replace')[:400]}")

    @staticmethod
    def _compress(source: Path, destination: Path) -> None:
        with source.open("rb") as raw, gzip.open(destination, "wb", compresslevel=6) as archive:
            shutil.copyfileobj(raw, archive)

    # --- Listing and retention --------------------------------------------

    async def list(self, tier: str | None = None) -> list[BackupRecord]:
        return [self._to_record(item) for item in await self.provider.list(tier)]

    async def latest(self) -> BackupRecord | None:
        backups = await self.list()
        return backups[0] if backups else None

    async def prune(self) -> dict[str, int]:
        """Apply the retention policy to each tier. Returns per-tier delete counts."""
        policy = {
            HOURLY: timedelta(hours=self.settings.backup_hourly_retention_hours),
            DAILY: timedelta(days=self.settings.backup_daily_retention_days),
            WEEKLY: timedelta(days=self.settings.backup_weekly_retention_days),
        }
        now = datetime.now(UTC)
        removed: dict[str, int] = {}

        for tier, keep_for in policy.items():
            cutoff = now - keep_for
            count = 0
            for backup in await self.provider.list(tier):
                created = backup.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if created < cutoff:
                    await self.provider.delete(backup.name)
                    count += 1
            if count:
                removed[tier] = count
                app_logger().info("backup_pruned", tier=tier, removed=count)
        return removed

    async def restore_test(self, name: str) -> tuple[bool, str]:
        """Restore a backup into a throwaway location.

        Never touches the live database - the restore target is always a fresh
        temporary file that is deleted afterwards.
        """
        archive = await self.provider.retrieve(name)
        with tempfile.TemporaryDirectory(prefix="hush-restore-") as workspace:
            target = Path(workspace) / "restored.sqlite"

            def _decompress() -> None:
                with gzip.open(archive, "rb") as source, target.open("wb") as out:
                    shutil.copyfileobj(source, out)

            await asyncio.to_thread(_decompress)

            if not self.is_sqlite:
                # A plain SQL dump cannot be opened as SQLite; verify it looks
                # like a complete dump instead of silently claiming success.
                text = target.read_text(encoding="utf-8", errors="replace")
                if "CREATE TABLE" not in text:
                    return False, "dump contains no CREATE TABLE statements"
                return True, "SQL dump structure looks valid (full restore needs psql)"

            def _check() -> tuple[bool, str]:
                connection = sqlite3.connect(str(target))
                try:
                    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if integrity != "ok":
                        return False, f"integrity check failed: {integrity}"
                    tables = connection.execute(
                        "SELECT count(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0]
                    return True, f"restored successfully with {tables} tables"
                finally:
                    connection.close()

            return await asyncio.to_thread(_check)

    @staticmethod
    def _to_record(stored: StoredBackup) -> BackupRecord:
        return BackupRecord(
            name=stored.name,
            tier=stored.tier,
            size_bytes=stored.size_bytes,
            created_at=stored.created_at,
            checksum=stored.checksum,
        )
