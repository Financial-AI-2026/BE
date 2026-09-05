from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PageText:
    page: int
    text: str


@dataclass(frozen=True)
class ParseReport:
    code: str
    source_path: str
    page_count: int
    page_char_counts: list[int]
    empty_pages: list[int]
    total_chars: int
    has_text_layer: bool


@dataclass(frozen=True)
class Section:
    part: str | None
    clause: str | None
    title: str
    text: str
    page_start: int
    page_end: int

    @property
    def location(self) -> str:
        tokens = [token for token in (self.part, self.clause) if token]
        prefix = " ".join(tokens)
        if prefix and self.title:
            return f"{prefix} ({self.title})"
        return prefix or self.title or f"p.{self.page_start}"


class Parser(Protocol):
    def extract_pages(self, path: Path, code: str) -> tuple[list[PageText], ParseReport]:
        ...

    def split_sections(self, pages: list[PageText]) -> list[Section]:
        ...

