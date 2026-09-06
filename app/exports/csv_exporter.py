"""CSV output. One file per table."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any


def dumps(rows: list[dict[str, Any]]) -> str:
    """Render rows as CSV. Returns an empty string for an empty table."""
    if not rows:
        return ""
    # Union of keys, preserving first-seen order, so sparse rows still align.
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _stringify(row.get(key)) for key in fieldnames})
    return buffer.getvalue()


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(rows), encoding="utf-8")
    return path
