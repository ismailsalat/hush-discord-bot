"""Human-readable text output, used for the audit trail in user exports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_SEPARATOR = "=" * 70


def dumps(bundle_metadata: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = [_SEPARATOR, "HUSH DATA EXPORT", _SEPARATOR, ""]

    for key, value in bundle_metadata.items():
        lines.append(f"{key}: {value}")
    lines.append("")

    for name, rows in tables.items():
        lines.append(_SEPARATOR)
        lines.append(f"{name.upper()}  ({len(rows)} rows)")
        lines.append(_SEPARATOR)
        if not rows:
            lines.append("(none)")
            lines.append("")
            continue
        for index, row in enumerate(rows, start=1):
            lines.append(f"[{index}]")
            for key, value in row.items():
                lines.append(f"  {key}: {value}")
            lines.append("")
    return "\n".join(lines)


def write_txt(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
