from __future__ import annotations

import hashlib
import json
import ssl
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from extraction.paths import RAW_DIR, ensure_output_dirs

FULLTEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
USER_AGENT = "FinancialAIChallenge research contact: research@example.com"
SUMMARY_PROSPECTUS_FORM = "497K"


class SecEdgarError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecFiling:
    ticker: str
    cik: str
    accession_no: str
    filename: str
    file_date: str
    display_name: str

    @property
    def document_url(self) -> str:
        accession_compact = self.accession_no.replace("-", "")
        cik_compact = str(int(self.cik))
        return f"{ARCHIVES_URL}/{cik_compact}/{accession_compact}/{self.filename}"


def find_latest_summary_prospectus(
    ticker: str,
    *,
    start_date: str = "2000-01-01",
    end_date: str | None = None,
    form: str = SUMMARY_PROSPECTUS_FORM,
) -> SecFiling:
    """Find the most recent Summary Prospectus (497K) filing that mentions this
    ticker, via SEC EDGAR full-text search. No API key needed -- only a
    descriptive User-Agent per SEC's fair-access policy.

    Full-text search can surface hits from *other* funds that merely mention
    this ticker (e.g. a comparison fund). Callers should sanity-check the
    returned filing's content mentions the ticker as its own before trusting it.
    """
    end_date = end_date or date.today().isoformat()
    params = {
        "q": f'"{ticker}"',
        "forms": form,
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
    }
    url = f"{FULLTEXT_SEARCH_URL}?{urlencode(params)}"
    data = _get_json(url)
    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        raise SecEdgarError(f"No {form} filings found for ticker {ticker!r}")

    # hits are relevance-ranked, not date-ranked -- take the most recently filed
    def file_date(hit: dict[str, Any]) -> str:
        return str(hit.get("_source", {}).get("file_date", ""))

    best = max(hits, key=file_date)
    source = best["_source"]
    doc_id = best["_id"]  # "{accession_no}:{filename}"
    accession_no, filename = doc_id.split(":", 1)
    cik = str(source["ciks"][0])
    return SecFiling(
        ticker=ticker,
        cik=cik,
        accession_no=accession_no,
        filename=filename,
        file_date=source.get("file_date", ""),
        display_name=str(source.get("display_names", [""])[0]),
    )


def fetch_filing_html(filing: SecFiling) -> bytes:
    request = Request(filing.document_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30, context=_ssl_context()) as response:
        return response.read()


def save_raw_document(code: str, filing: SecFiling, html: bytes) -> Path:
    ensure_output_dirs()
    out_dir = RAW_DIR / code
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{code}.htm"
    path.write_bytes(html)

    sources_path = out_dir / "sources.json"
    sources_path.write_text(
        json.dumps(
            [
                {
                    "filename": path.name,
                    "sha256": hashlib.sha256(html).hexdigest(),
                    "collectedAt": date.today().isoformat(),
                    "sourceUrl": filing.document_url,
                    "secTicker": filing.ticker,
                    "secCik": filing.cik,
                    "secAccessionNo": filing.accession_no,
                    "secFileDate": filing.file_date,
                    "secDisplayName": filing.display_name,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def fetch_and_save_summary_prospectus(code: str, ticker: str) -> Path:
    filing = find_latest_summary_prospectus(ticker)
    html = fetch_filing_html(filing)
    return save_raw_document(code, filing, html)


def _get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=15, context=_ssl_context()) as response:
        payload = response.read()
    return json.loads(payload)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ModuleNotFoundError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())
