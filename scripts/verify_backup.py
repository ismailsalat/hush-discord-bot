#!/usr/bin/env python3
"""Verify a backup, and optionally prove it restores.

    python scripts/verify_backup.py --latest --restore-test
    python scripts/verify_backup.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import get_settings  # noqa: E402
from app.logging.setup import configure_from_settings  # noqa: E402
from app.services.backup_service import BackupService  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Hush backups.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", help="Verify one backup by filename.")
    group.add_argument("--latest", action="store_true", help="Verify the newest backup.")
    group.add_argument("--all", action="store_true", help="Verify every backup.")
    parser.add_argument(
        "--restore-test", action="store_true",
        help="Restore into a temporary location to prove it works.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_from_settings(settings)
    service = BackupService(settings)

    backups = await service.list()
    if not backups:
        print("No backups found.")
        return 1

    if args.name:
        targets = [args.name]
    elif args.latest:
        targets = [backups[0].name]
    else:
        targets = [backup.name for backup in backups]

    failures = 0
    for name in targets:
        report = await service.verify(name)
        status = "OK " if report.ok else "BAD"
        print(f"[{status}] {name}  ({report.summary})")
        for check, ok, detail in report.checks:
            print(f"        {'PASS' if ok else 'FAIL'}  {check}: {detail}")
        if report.row_counts:
            populated = {k: v for k, v in report.row_counts.items() if v}
            print(f"        rows: {populated}")
        if args.restore_test:
            restored, detail = await service.restore_test(name)
            print(f"        {'PASS' if restored else 'FAIL'}  restore-test: {detail}")
            if not restored:
                failures += 1
        if not report.ok:
            failures += 1

    print(f"\n{len(targets) - failures}/{len(targets)} verified")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
