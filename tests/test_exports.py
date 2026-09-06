"""Exports: permission tiers, identity redaction and audit records."""

from __future__ import annotations

import json
import zipfile

import pytest

from app.core.constants import ExportFormat, ExportScope, PermissionLevel
from app.core.exceptions import ExportPermissionError
from app.services.export_service import ExportService
from tests.conftest import GUILD_ID

OWNER_ID = 1


@pytest.fixture
def exports(session, settings):
    return ExportService(session, settings)


class TestPermissions:
    async def test_full_export_requires_owner(self, exports, factory):
        await factory.confession()
        with pytest.raises(ExportPermissionError):
            await exports.export(
                scope=ExportScope.FULL,
                actor_level=PermissionLevel.ADMIN,
                actor_id=99,
            )

    async def test_owner_may_export_everything(self, exports, factory):
        await factory.confession()
        result = await exports.export(
            scope=ExportScope.FULL, actor_level=PermissionLevel.BOT_OWNER, actor_id=OWNER_ID
        )
        assert result.path.exists()

    async def test_moderator_cannot_export_a_guild(self, exports, factory):
        await factory.confession()
        with pytest.raises(ExportPermissionError):
            await exports.export(
                scope=ExportScope.GUILD,
                actor_level=PermissionLevel.MODERATOR,
                actor_id=99,
                guild_id=GUILD_ID,
            )

    async def test_admin_may_export_their_guild(self, exports, factory):
        await factory.confession()
        result = await exports.export(
            scope=ExportScope.GUILD,
            actor_level=PermissionLevel.ADMIN,
            actor_id=99,
            guild_id=GUILD_ID,
        )
        assert result.row_counts.get("confessions", 0) >= 1


class TestRedaction:
    async def test_admin_export_hides_discord_ids(self, exports, factory):
        """Only an owner may see who is behind an anonymous profile."""
        await factory.confession(content="something identifying")
        result = await exports.export(
            scope=ExportScope.GUILD,
            actor_level=PermissionLevel.ADMIN,
            actor_id=99,
            guild_id=GUILD_ID,
            export_format=ExportFormat.JSON,
        )
        payload = result.path.read_text(encoding="utf-8")
        assert result.redacted is True
        assert "discord_user_id" not in payload

    async def test_owner_user_export_includes_the_discord_id(self, exports, factory):
        """The one export tier that is allowed to link an identity."""
        user, alias = await factory.member(discord_id=123456789012345678)
        await factory.confession(user=user, alias=alias)
        result = await exports.export(
            scope=ExportScope.USER,
            actor_level=PermissionLevel.BOT_OWNER,
            actor_id=OWNER_ID,
            guild_id=GUILD_ID,
            internal_user_id=user.id,
            export_format=ExportFormat.JSON,
        )
        assert result.redacted is False
        assert "123456789012345678" in result.path.read_text(encoding="utf-8")

    async def test_admin_user_export_strips_the_discord_id(self, exports, factory):
        user, alias = await factory.member(discord_id=123456789012345678)
        await factory.confession(user=user, alias=alias)
        result = await exports.export(
            scope=ExportScope.USER,
            actor_level=PermissionLevel.ADMIN,
            actor_id=99,
            guild_id=GUILD_ID,
            internal_user_id=user.id,
            export_format=ExportFormat.JSON,
        )
        assert result.redacted is True
        assert "123456789012345678" not in result.path.read_text(encoding="utf-8")

    async def test_guild_export_never_carries_identities(self, exports, factory):
        """Even for the owner, a whole-server dump stays alias-only."""
        user, alias = await factory.member(discord_id=123456789012345678)
        await factory.confession(user=user, alias=alias)
        result = await exports.export(
            scope=ExportScope.GUILD,
            actor_level=PermissionLevel.BOT_OWNER,
            actor_id=OWNER_ID,
            guild_id=GUILD_ID,
            export_format=ExportFormat.JSON,
        )
        assert "123456789012345678" not in result.path.read_text(encoding="utf-8")


class TestFormats:
    @pytest.mark.parametrize(
        "export_format", [ExportFormat.JSON, ExportFormat.CSV, ExportFormat.TXT]
    )
    async def test_each_format_produces_a_file(self, exports, factory, export_format):
        await factory.confession()
        result = await exports.export(
            scope=ExportScope.GUILD,
            actor_level=PermissionLevel.BOT_OWNER,
            actor_id=OWNER_ID,
            guild_id=GUILD_ID,
            export_format=export_format,
        )
        assert result.path.exists()
        assert result.size_bytes > 0

    async def test_zip_contains_metadata_and_data(self, exports, factory):
        await factory.confession()
        result = await exports.export(
            scope=ExportScope.GUILD,
            actor_level=PermissionLevel.BOT_OWNER,
            actor_id=OWNER_ID,
            guild_id=GUILD_ID,
            export_format=ExportFormat.ZIP,
        )
        with zipfile.ZipFile(result.path) as archive:
            names = archive.namelist()
            assert "metadata.json" in names
            assert any(name.startswith("confessions") for name in names)
            metadata = json.loads(archive.read("metadata.json"))
        assert metadata["scope"] == ExportScope.GUILD.value
        assert "generated_at" in metadata


class TestAudit:
    async def test_export_is_recorded(self, exports, session, factory):
        from sqlalchemy import func, select

        from app.database.models import ExportRecord

        await factory.confession()
        await exports.export(
            scope=ExportScope.GUILD,
            actor_level=PermissionLevel.BOT_OWNER,
            actor_id=OWNER_ID,
            guild_id=GUILD_ID,
        )
        count = await session.scalar(select(func.count()).select_from(ExportRecord))
        assert count == 1

    async def test_denied_export_produces_no_file(self, exports, settings, factory):
        from pathlib import Path

        await factory.confession()
        with pytest.raises(ExportPermissionError):
            await exports.export(
                scope=ExportScope.FULL,
                actor_level=PermissionLevel.USER,
                actor_id=5,
            )
        directory = Path(settings.export_directory)
        assert not directory.exists() or not list(directory.iterdir())
