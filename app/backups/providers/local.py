"""Local filesystem backup provider."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.backups.providers.base import BackupProvider, StoredBackup
from app.core.exceptions import BackupError

#: Sidecar file holding the checksum and tier for each archive.
META_SUFFIX = ".meta.json"


def checksum_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 of a file, streamed so large backups do not load into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class LocalBackupProvider(BackupProvider):
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, name: str) -> Path:
        return self.directory / f"{name}{META_SUFFIX}"

    async def store(self, source: Path, name: str, tier: str) -> StoredBackup:
        destination = self.directory / name

        def _copy() -> None:
            shutil.copy2(source, destination)

        await asyncio.to_thread(_copy)
        digest = await asyncio.to_thread(checksum_file, destination)
        created = datetime.now(UTC)

        metadata = {
            "name": name,
            "tier": tier,
            "checksum": digest,
            "created_at": created.isoformat(),
            "size_bytes": destination.stat().st_size,
        }
        self._meta_path(name).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        return StoredBackup(
            name=name,
            path=str(destination),
            size_bytes=metadata["size_bytes"],
            created_at=created,
            tier=tier,
            checksum=digest,
        )

    async def list(self, tier: str | None = None) -> list[StoredBackup]:
        backups: list[StoredBackup] = []
        for meta_file in sorted(self.directory.glob(f"*{META_SUFFIX}")):
            try:
                metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            archive = self.directory / metadata["name"]
            if not archive.exists():
                continue
            if tier and metadata.get("tier") != tier:
                continue
            backups.append(
                StoredBackup(
                    name=metadata["name"],
                    path=str(archive),
                    size_bytes=int(metadata.get("size_bytes", 0)),
                    created_at=datetime.fromisoformat(metadata["created_at"]),
                    tier=metadata.get("tier", "unknown"),
                    checksum=metadata.get("checksum"),
                )
            )
        backups.sort(key=lambda item: item.created_at, reverse=True)
        return backups

    async def retrieve(self, name: str) -> Path:
        path = self.directory / name
        if not path.exists():
            raise BackupError(f"backup not found: {name}")
        return path

    async def delete(self, name: str) -> bool:
        path = self.directory / name
        meta = self._meta_path(name)
        removed = path.exists()
        path.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        return removed

    async def exists(self, name: str) -> bool:
        return (self.directory / name).exists()
