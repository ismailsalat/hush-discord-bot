"""The intermediate representation every exporter consumes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.utils.time import utcnow


@dataclass(slots=True)
class ExportBundle:
    """A named collection of tables plus provenance metadata.

    Services build a bundle; exporters render it. Adding a new output format
    means adding one writer, not touching any query.
    """

    scope: str
    target: str | None = None
    guild_id: int | None = None
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, rows: list[dict[str, Any]]) -> None:
        self.tables[name] = rows

    def row_counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in self.tables.items()}

    def finalize(self, *, requested_by: int, redacted: bool) -> "ExportBundle":
        self.metadata.update(
            {
                "scope": self.scope,
                "target": self.target,
                "guild_id": self.guild_id,
                "generated_at": utcnow().isoformat(),
                "requested_by_discord_id": requested_by,
                "identity_redacted": redacted,
                "row_counts": self.row_counts(),
            }
        )
        return self
