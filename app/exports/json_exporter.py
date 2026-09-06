"""JSON output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _default(value: Any) -> str:
    return str(value)


def dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=_default)


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(payload), encoding="utf-8")
    return path
