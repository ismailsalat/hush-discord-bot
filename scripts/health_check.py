#!/usr/bin/env python3
"""Health check for container probes and monitoring.

Exits 0 when healthy and 1 otherwise, so it can be used directly as a Docker
HEALTHCHECK command.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import get_settings  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.services.backup_service import BackupService  # noqa: E402
from app.services.health_service import HealthService  # noqa: E402


async def main() -> int:
    settings = get_settings()
    database = Database.from_settings(settings)
    try:
        health = HealthService(database)
        health.register("backups", BackupService(settings).status)
        report = await health.run()
    finally:
        await database.dispose()

    for check in report.checks:
        print(f"{check.icon} {check.name}: {check.detail}")
    return 0 if report.healthy else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
