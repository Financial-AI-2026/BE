from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from extraction.parsers.base import PageText, ParseReport, Section

MIN_TEXT_LENGTH = 2_000  # a real summary prospectus is tens of thousands of chars


class UsSummaryParser:
    """Parser for SEC EDGAR Summary Prospectus (497K) HTML documents.

    Unlike the Korean PDF pipeline, this does *not* split into precise
    sections. A spike (2026-09-02) tested
    style-based and canonical-name-based section splitting across 6 filers
    (Global X, ProShares, iShares, Vanguard, ARK, JPMorgan) and found no
    single heuristic that generalizes reliably -- filers wrap headers in
    different tags, and even the same SEC-mandated Item (e.g. "Principal
    Investment Strategies") is phrased as a noun phrase, an abbreviated
    word, or a plain-English question depending on the filer.

    These documents are short enough (roughly 20,000-50,000 chars) that splitting isn't
    needed for Tier 1 extraction: the whole cleaned text is fed to the LLM
    as one context block, the same way the KR pipeline's C2_wide mode feeds
    a wide (not surgically precise) context rather than betting everything
    on exact section boundaries.
    """

    def extract_pages(self, path: Path, code: str) -> tuple[list[PageText], ParseReport]:
        html = path.read_bytes()
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        page = PageText(page=1, text=text)
        report = ParseReport(
            code=code,
            source_path=str(path),
            page_count=1,
            page_char_counts=[len(text)],
            empty_pages=[] if text else [1],
            total_chars=len(text),
            has_text_layer=len(text) >= MIN_TEXT_LENGTH,
        )
        return [page], report

    def split_sections(self, pages: list[PageText]) -> list[Section]:
        if not pages:
            return []
        text = "\n\n".join(page.text for page in pages)
        return [
            Section(
                part=None,
                clause=None,
                title="Summary Prospectus",
                text=text,
                page_start=1,
                page_end=1,
            )
        ]
