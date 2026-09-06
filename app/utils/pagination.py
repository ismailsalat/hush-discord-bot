"""Small, dependency-free pagination helper used by profile/bookmark views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: Sequence[T]
    index: int
    total_pages: int
    total_items: int

    @property
    def human_index(self) -> int:
        return self.index + 1

    @property
    def has_previous(self) -> bool:
        return self.index > 0

    @property
    def has_next(self) -> bool:
        return self.index < self.total_pages - 1

    @property
    def label(self) -> str:
        return f"Page {self.human_index}/{self.total_pages}"


def paginate(items: Sequence[T], index: int, per_page: int = 5) -> Page[T]:
    """Clamp ``index`` into range and slice out the requested page."""
    total_items = len(items)
    total_pages = max(1, -(-total_items // per_page))
    index = max(0, min(index, total_pages - 1))
    start = index * per_page
    return Page(items[start : start + per_page], index, total_pages, total_items)
