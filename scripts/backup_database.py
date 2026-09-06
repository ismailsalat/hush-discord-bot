#!/usr/bin/env python3
"""Create a backup from the command line (for cron, or before a deploy).

    python scripts/backup_database.py --tier daily --verify
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backups.manager import DAILY, HOURLY, MANUAL, WEEKLY  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.logging.setup import configure_from_settings  # noqa: E402
from app.services.backup_service import BackupService  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Hush backup.")
    parser.add_argument(
        "--tier", choices=[HOURLY, DAILY, WEEKLY, MANUAL], default=MANUAL
    )
    parser.add_argument("--verify", action="store_true", help="Verify after creating.")
    parser.add_argument("--prune", action="store_true", help="Apply retention afterwards.")
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_directories()
    configure_from_settings(settings)
    service = BackupService(settings)

    if args.verify:
        record, report = await service.create_and_verify(args.tier)
        print(f"{record.name}  {record.size_display}  [{report.summary}]")
        if not report.ok:
            for failure in report.failures():
                print(f"  FAILED {failure}")
            return 1
    else:
        record = await service.create(args.tier)
        print(f"{record.name}  {record.size_display}")

    if args.prune:
        removed = await service.prune()
        print(f"pruned: {removed or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
