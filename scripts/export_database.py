#!/usr/bin/env python3
"""Run an export from the command line.

Runs at OWNER level by definition - shell access to the host already implies
full data access, so there is nothing to gate here. Every export is still
written to the audit log.

    python scripts/export_database.py --scope FULL --format zip
    python scripts/export_database.py --scope GUILD --guild 123 --format json
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import get_settings  # noqa: E402
from app.core.constants import ExportFormat, ExportScope, PermissionLevel  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.logging.setup import configure_from_settings  # noqa: E402
from app.services.export_service import ExportService  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Export Hush data.")
    parser.add_argument(
        "--scope", choices=[item.value for item in ExportScope], default=ExportScope.FULL.value
    )
    parser.add_argument(
        "--format", dest="export_format",
        choices=[item.value for item in ExportFormat], default=ExportFormat.ZIP.value,
    )
    parser.add_argument("--guild", type=int, default=None)
    parser.add_argument("--user", default=None, help="Internal user id (usr_...).")
    parser.add_argument("--alias", default=None, help="Alias id (ali_...).")
    parser.add_argument("--confession", default=None, help="Confession id (conf_...).")
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_directories()
    configure_from_settings(settings)

    database = Database.from_settings(settings)
    try:
        async with database.session() as session:
            result = await ExportService(session, settings).export(
                scope=ExportScope(args.scope),
                actor_level=PermissionLevel.BOT_OWNER,
                actor_id=0,
                export_format=ExportFormat(args.export_format),
                guild_id=args.guild,
                internal_user_id=args.user,
                alias_id=args.alias,
                confession_id=args.confession,
            )
    finally:
        await database.dispose()

    print(f"{result.path}")
    print(f"  {result.size_bytes:,} bytes")
    print(f"  rows: {({k: v for k, v in result.row_counts.items() if v})}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
