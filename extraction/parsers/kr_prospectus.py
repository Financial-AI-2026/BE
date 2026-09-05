from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from extraction.parsers.base import PageText, ParseReport, Section


class ParserDependencyError(RuntimeError):
    pass


class TextLayerMissingError(RuntimeError):
    pass


class SectionMismatch(RuntimeError):
    pass


PAGE_MARKER = "===== [PAGE {n}] ====="
TABLE_MARKER = "----- [표 복원 p.{n}] -----"
EMPTY_PAGE_CHARS = 30
MAX_TOC_PAGES = 8
TOC_MAX_LINE_LEN = 50
TITLE_SIMILARITY = 0.75

C2_SECTIONS = [
    (1, 1, "명칭"),
    (2, 1, "명칭"),
    (2, 6, "구조"),
    (2, 7, "투자목적"),
    (2, 8, "투자대상"),
    (2, 9, "투자전략"),
    (2, 10, "투자위험"),
    (2, 13, "보수"),
    (2, 14, "배분"),
]

NUMERIC_CELL = re.compile(r"^-?[\d,]+\.?\d*%?$")
TOC_MARKER = re.compile(r"\[?\s*목\s*차\s*\]?")
TOC_BU = re.compile(r"^제\s*(\d+)\s*부\.?\s*(.+)$")
TOC_SUB = re.compile(r"^(\d{1,2})\.\s*(.+)$")
BODY_HEAD = re.compile(r"^(\d{1,2})\.\s*(.+)$")
BODY_BU = re.compile(r"^제\s*(\d+)\s*부\.?")


class KrProspectusParser:
    def extract_pages(self, path: Path, code: str) -> tuple[list[PageText], ParseReport]:
        try:
            import pymupdf
        except ModuleNotFoundError as exc:
            raise ParserDependencyError(
                "PyMuPDF is required for PDF text extraction. Install project dependencies first."
            ) from exc

        doc = pymupdf.open(path)
        try:
            base_pages = [page.get_text("text") for page in doc]
        finally:
            doc.close()

        table_pages = extract_tables_by_page(path)
        pages = [
            PageText(page=index, text=page_block(index, text, table_pages.get(index, [])).strip())
            for index, text in enumerate(base_pages, start=1)
        ]

        report = self._build_report(code=code, source_path=path, pages=pages)
        if not report.has_text_layer:
            raise TextLayerMissingError(f"No readable text layer found in {path}")
        return pages, report

    def split_sections(self, pages: list[PageText]) -> list[Section]:
        raw_pages = [page.text for page in pages]
        try:
            toc_page, toc_end, entries = parse_toc(raw_pages)
            found = locate_sections(raw_pages, toc_end, entries)
            body_start = min((section["start"] for section in found), default=len(raw_pages))
            summary = locate_summary(raw_pages, toc_page, toc_end, body_start)
        except (StopIteration, SectionMismatch):
            return [
                Section(
                    part=None,
                    clause=None,
                    title="C2_wide",
                    text="\n\n".join(page.text for page in pages),
                    page_start=pages[0].page if pages else 0,
                    page_end=pages[-1].page if pages else 0,
                )
            ]

        sections = [summary] + found
        return [
            Section(
                part=f"제{item['bu']}부" if item["bu"] else None,
                clause=str(item["num"]) if item["num"] else None,
                title=item["title"],
                text="\n".join(raw_pages[item["start"] - 1 : item["end"]]),
                page_start=item["start"],
                page_end=item["end"],
            )
            for item in sections
        ]

    def _build_report(self, code: str, source_path: Path, pages: list[PageText]) -> ParseReport:
        counts = [len(page.text.strip()) for page in pages]
        empty_pages = [page.page for page in pages if len(page.text.strip()) < EMPTY_PAGE_CHARS]
        total = sum(counts)
        return ParseReport(
            code=code,
            source_path=str(source_path),
            page_count=len(pages),
            page_char_counts=counts,
            empty_pages=empty_pages,
            total_chars=total,
            has_text_layer=total > 0 and len(empty_pages) < len(pages),
        )


def extract_tables_by_page(pdf_path: Path) -> dict[int, list[str]]:
    try:
        import pdfplumber
    except ModuleNotFoundError:
        return {}

    out: dict[int, list[str]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            rendered = []
            for raw in page.extract_tables():
                rows = normalize_table(raw)
                if rows and is_numeric_grid(rows):
                    rendered.append(render_table(rows))
            if rendered:
                out[page_number] = rendered
    return out


def normalize_table(raw: list[list]) -> list[list[str]] | None:
    rows = [[(cell or "").replace("\n", " ").strip() for cell in row] for row in raw]
    if not rows:
        return None
    width = max(len(row) for row in rows)
    keep = [index for index in range(width) if any(index < len(row) and row[index] for row in rows)]
    rows = [[row[index] if index < len(row) else "" for index in keep] for row in rows]
    rows = [row for row in rows if any(row)]
    if len(rows) < 2 or len(keep) < 2:
        return None
    if sum(1 for row in rows if sum(1 for cell in row if cell) >= 2) < 2:
        return None
    return rows


def is_numeric_grid(rows: list[list[str]]) -> bool:
    cells = [cell for row in rows for cell in row if cell]
    if len(cells) < 6:
        return False
    if sum(1 for cell in cells if NUMERIC_CELL.match(cell)) < 3:
        return False
    return sum(len(cell) for cell in cells) / len(cells) < 25


def render_table(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(row) for row in rows)


def page_block(page_number: int, text: str, tables: list[str]) -> str:
    parts = [PAGE_MARKER.format(n=page_number), text]
    for table in tables:
        parts += [TABLE_MARKER.format(n=page_number), table]
    return "\n".join(parts) + "\n"


def parse_toc(pages: list[str]) -> tuple[int, int, list[dict]]:
    toc_page = next(
        index
        for index, page in enumerate(pages, 1)
        if any(TOC_MARKER.fullmatch(line.strip()) for line in page.split("\n"))
    )
    entries: list[dict] = []
    bu = None
    toc_end = toc_page
    for page_number in range(toc_page, min(toc_page + MAX_TOC_PAGES, len(pages)) + 1):
        if page_number > toc_page and not looks_like_toc(pages[page_number - 1]):
            break
        for line in pages[page_number - 1].split("\n"):
            stripped = line.strip()
            if match := TOC_BU.match(stripped):
                bu = int(match.group(1))
            elif bu and (match := TOC_SUB.match(stripped)):
                entries.append(
                    {"bu": bu, "num": int(match.group(1)), "title": match.group(2).strip()}
                )
        toc_end = page_number
    return toc_page, toc_end, entries


def looks_like_toc(page: str) -> bool:
    lines = [line.strip() for line in page.split("\n") if line.strip()]
    if not lines or max(len(line) for line in lines) > TOC_MAX_LINE_LEN:
        return False
    return any(TOC_BU.match(line) or TOC_SUB.match(line) for line in lines)


def locate_summary(pages: list[str], toc_page: int, toc_end: int, body_start: int) -> dict:
    if before := [index for index in range(1, toc_page) if "요약정보" in pages[index - 1]]:
        start, end = before[0], toc_page - 1
    elif after := [
        index for index in range(toc_end + 1, body_start) if "요약정보" in pages[index - 1]
    ]:
        start, end = after[0], body_start - 1
    else:
        raise SectionMismatch("요약정보 구간을 찾지 못했습니다.")
    return {"bu": 0, "num": 0, "title": "요약정보", "start": start, "end": max(start, end)}


def locate_sections(pages: list[str], toc_page: int, entries: list[dict]) -> list[dict]:
    found: list[dict] = []
    cursor = toc_page + 1
    current_bu = None
    for entry in entries:
        if entry["bu"] != current_bu:
            current_bu = entry["bu"]
            cursor = find_bu_heading(pages, cursor, current_bu) or cursor
        page_number, verified = find_heading(pages, cursor, entry)
        if page_number is not None:
            found.append({**entry, "start": page_number, "title_verified": verified})
            cursor = page_number

    for index, section in enumerate(found):
        next_start = found[index + 1]["start"] - 1 if index + 1 < len(found) else len(pages)
        section["end"] = max(section["start"], next_start)
    return found


def find_bu_heading(pages: list[str], start_page: int, bu: int) -> int | None:
    for page_number in range(start_page, len(pages) + 1):
        for line in pages[page_number - 1].split("\n"):
            if (match := BODY_BU.match(line.strip())) and int(match.group(1)) == bu:
                return page_number
    return None


def find_heading(pages: list[str], start_page: int, entry: dict) -> tuple[int | None, bool]:
    fallback = None
    for page_number in range(start_page, len(pages) + 1):
        for line in pages[page_number - 1].split("\n"):
            match = BODY_HEAD.match(line.strip())
            if not match or int(match.group(1)) != entry["num"]:
                continue
            if title_match(match.group(2), entry["title"]):
                return page_number, True
            if fallback is None:
                fallback = page_number
    return fallback, False


def title_match(body: str, toc: str) -> bool:
    body_norm = norm(body)
    toc_norm = norm(toc)
    if not body_norm or not toc_norm:
        return False
    if (
        body_norm.startswith(toc_norm)
        or toc_norm.startswith(body_norm)
        or body_norm.endswith(toc_norm)
        or toc_norm.endswith(body_norm)
    ):
        return True
    return SequenceMatcher(None, body_norm, toc_norm).ratio() >= TITLE_SIMILARITY


def norm(value: str) -> str:
    return re.sub(r"[\s,.·ㆍ()\[\]:]", "", value)
