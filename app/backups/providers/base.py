"""Storage abstraction for backups.

Only a local filesystem provider ships today, but every call site goes through
this interface so adding S3 or another offsite target later is a new class, not
a refactor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StoredBackup:
    name: str
    path: str
    size_bytes: int
    created_at: datetime
    tier: str
    checksum: str | None = None


class BackupProvider(ABC):
    """Where backups live."""

    @abstractmethod
    async def store(self, source: Path, name: str, tier: str) -> StoredBackup: ...

    @abstractmethod
    async def list(self, tier: str | None = None) -> list[StoredBackup]: ...

    @abstractmethod
    async def retrieve(self, name: str) -> Path: ...

    @abstractmethod
    async def delete(self, name: str) -> bool: ...

    @abstractmethod
    async def exists(self, name: str) -> bool: ...
