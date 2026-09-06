"""Backup verification.

A backup that exists is not a backup that works. Verification opens the archive,
checks the checksum, and inspects the restored schema and contents.
"""

from __future__ import annotations

import asyncio
import gzip
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.backups.providers import BackupProvider
from app.backups.providers.local import checksum_file
from app.core.exceptions import BackupVerificationError

#: Tables that must be present for a restore to be considered usable.
CRITICAL_TABLES = (
    "users",
    "guilds",
    "anon_aliases",
    "confessions",
    "ratings",
    "moderation_ledger",
)


@dataclass(slots=True)
class VerificationReport:
    name: str
    ok: bool = True
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)

    def add(self, check: str, passed: bool, detail: str = "") -> None:
        self.checks.append((check, passed, detail))
        if not passed:
            self.ok = False

    @property
    def summary(self) -> str:
        passed = sum(1 for _name, ok, _detail in self.checks if ok)
        return f"{passed}/{len(self.checks)} checks passed"

    def failures(self) -> list[str]:
        return [f"{name}: {detail}" for name, ok, detail in self.checks if not ok]


class BackupVerifier:
    def __init__(self, provider: BackupProvider, *, is_sqlite: bool = True):
        self.provider = provider
        self.is_sqlite = is_sqlite

    async def verify(self, name: str) -> VerificationReport:
        report = VerificationReport(name=name)

        try:
            archive = await self.provider.retrieve(name)
        except Exception as exc:
            report.add("exists", False, str(exc))
            return report
        report.add("exists", True, f"{archive.stat().st_size:,} bytes")

        # 1. Checksum against the sidecar recorded at store time.
        stored = next((item for item in await self.provider.list() if item.name == name), None)
        if stored and stored.checksum:
            actual = await asyncio.to_thread(checksum_file, archive)
            matches = actual == stored.checksum
            report.add(
                "checksum", matches, "matches recorded digest" if matches else "CHECKSUM MISMATCH"
            )
        else:
            report.add("checksum", False, "no recorded checksum")

        # 2. Decompress.
        with tempfile.TemporaryDirectory(prefix="hush-verify-") as workspace:
            restored = Path(workspace) / "restored.db"
            try:
                await asyncio.to_thread(self._decompress, archive, restored)
                report.add("decompress", True, f"{restored.stat().st_size:,} bytes")
            except Exception as exc:
                report.add("decompress", False, str(exc))
                return report

            if not self.is_sqlite:
                text = restored.read_text(encoding="utf-8", errors="replace")
                has_schema = "CREATE TABLE" in text
                report.add("schema", has_schema,
                           "CREATE TABLE statements found" if has_schema else "no schema in dump")
                missing = [table for table in CRITICAL_TABLES if table not in text]
                report.add("critical_tables", not missing,
                           "all present" if not missing else f"missing: {missing}")
                return report

            await asyncio.to_thread(self._inspect_sqlite, restored, report)

        return report

    @staticmethod
    def _decompress(archive: Path, destination: Path) -> None:
        with gzip.open(archive, "rb") as source, destination.open("wb") as out:
            shutil.copyfileobj(source, out)

    @staticmethod
    def _inspect_sqlite(path: Path, report: VerificationReport) -> None:
        connection = sqlite3.connect(str(path))
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            report.add("integrity", integrity == "ok", integrity)

            foreign_key_problems = connection.execute("PRAGMA foreign_key_check").fetchall()
            report.add(
                "foreign_keys",
                not foreign_key_problems,
                "consistent" if not foreign_key_problems
                else f"{len(foreign_key_problems)} violations",
            )

            present = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            missing = [table for table in CRITICAL_TABLES if table not in present]
            report.add(
                "critical_tables",
                not missing,
                f"{len(present)} tables" if not missing else f"missing: {missing}",
            )

            for table in sorted(present):
                if table.startswith("sqlite_"):
                    continue
                try:
                    count = connection.execute(f"SELECT count(*) FROM '{table}'").fetchone()[0]
                    report.row_counts[table] = int(count)
                except sqlite3.Error:
                    report.row_counts[table] = -1

            unreadable = [name for name, count in report.row_counts.items() if count < 0]
            report.add(
                "readable",
                not unreadable,
                "all tables readable" if not unreadable else f"unreadable: {unreadable}",
            )
        finally:
            connection.close()

    async def verify_or_raise(self, name: str) -> VerificationReport:
        report = await self.verify(name)
        if not report.ok:
            raise BackupVerificationError(
                f"backup {name} failed verification: {report.failures()}"
            )
        return report
