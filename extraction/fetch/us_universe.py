"""Fetches the full US ETF universe from nasdaqtrader.com's daily symbol
directory files — no API key required. Mirrors `extraction/fetch/krx.py`'s shape (an `EtfListing`
dataclass + snapshot read/write helpers) so `app/seed/universe.py` can load
either source through the same loader.

Two files, unioned:
- `nasdaqlisted.txt`: NASDAQ-listed securities. `ETF` column is Y/N.
- `otherlisted.txt`: NYSE / NYSE Arca / Cboe BZX ("Z") / other exchanges.
  Also has an `ETF` column, same Y/N semantics.

Both are pipe-delimited with a header row and a trailing
`File Creation Time: ...` footer line — the footer is not a data row and must
be dropped, not parsed as a listing. Both also carry a `Test Issue` column
(Y/N) for synthetic test symbols exchanges publish alongside real ones;
those are excluded even if flagged `ETF=Y`.

As of 2026-09-04: 1,258 ETFs in nasdaqlisted.txt, 4,398 in otherlisted.txt,
zero overlapping codes between the two (checked directly against a live
pull) — `fetch_us_etf_universe` still dedupes defensively in case that
changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from extraction.fetch.krx import ssl_context
from extraction.paths import REPORTS_DIR, ensure_output_dirs

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
UNIVERSE_DIR_NAME = "us_etf_universe"
FOOTER_PREFIX = "File Creation Time:"

# otherlisted.txt's single-letter `Exchange` column, per Nasdaq Trader's
# published symbol directory spec.
_OTHER_EXCHANGE_NAMES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "CBOE",
    "V": "IEXG",
}


class NasdaqTraderError(RuntimeError):
    pass


@dataclass(frozen=True)
class EtfListing:
    """One ETF row from either symbol directory file."""

    code: str
    name: str
    exchange: str
    source_file: str  # "nasdaqlisted" | "otherlisted" — audit/debug only


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=30, context=ssl_context()) as response:
            return response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise NasdaqTraderError(f"failed to fetch {url}: {exc}") from exc


def _data_lines(text: str) -> list[str]:
    """Header and footer stripped; blank lines skipped."""
    lines = text.splitlines()
    if not lines:
        return []
    _header, *rest = lines
    return [line for line in rest if line and not line.startswith(FOOTER_PREFIX)]


def parse_nasdaq_listed(text: str) -> list[EtfListing]:
    """Columns: Symbol|Security Name|Market Category|Test Issue|Financial
    Status|Round Lot Size|ETF|NextShares"""
    listings: list[EtfListing] = []
    for line in _data_lines(text):
        cols = line.split("|")
        if len(cols) < 7:
            continue
        symbol, name, _market_category, test_issue, _financial_status, _round_lot, etf = cols[:7]
        if etf.strip() != "Y" or test_issue.strip() == "Y":
            continue
        symbol = symbol.strip()
        name = name.strip()
        if not symbol or not name:
            continue
        listings.append(
            EtfListing(code=symbol, name=name, exchange="NASDAQ", source_file="nasdaqlisted")
        )
    return listings


def parse_other_listed(text: str) -> list[EtfListing]:
    """Columns: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot
    Size|Test Issue|NASDAQ Symbol"""
    listings: list[EtfListing] = []
    for line in _data_lines(text):
        cols = line.split("|")
        if len(cols) < 7:
            continue
        act_symbol, name, exchange_code, _cqs_symbol, etf, _round_lot, test_issue = cols[:7]
        if etf.strip() != "Y" or test_issue.strip() == "Y":
            continue
        act_symbol = act_symbol.strip()
        name = name.strip()
        if not act_symbol or not name:
            continue
        exchange_code = exchange_code.strip()
        exchange = _OTHER_EXCHANGE_NAMES.get(exchange_code, exchange_code)
        listings.append(
            EtfListing(code=act_symbol, name=name, exchange=exchange, source_file="otherlisted")
        )
    return listings


def fetch_us_etf_universe(
    *, nasdaq_text: str | None = None, other_text: str | None = None
) -> list[EtfListing]:
    """Fetch (or accept pre-fetched text — offline tests pass both) and union
    the two files, deduping by code. On a collision, nasdaqlisted.txt wins —
    arbitrary but deterministic; none observed live as of 2026-09-04."""
    nasdaq_text = nasdaq_text if nasdaq_text is not None else _fetch_text(NASDAQ_LISTED_URL)
    other_text = other_text if other_text is not None else _fetch_text(OTHER_LISTED_URL)

    by_code: dict[str, EtfListing] = {}
    for listing in parse_other_listed(other_text):
        by_code[listing.code] = listing
    for listing in parse_nasdaq_listed(nasdaq_text):
        by_code[listing.code] = listing  # nasdaqlisted wins on collision
    return sorted(by_code.values(), key=lambda item: item.code)


def universe_dir() -> Path:
    ensure_output_dirs()
    path = REPORTS_DIR / UNIVERSE_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_path(as_of: str, *, output_dir: Path | None = None) -> Path:
    return (output_dir or universe_dir()) / f"{as_of}.json"


def write_snapshot(
    listings: list[EtfListing], *, as_of: str, output_dir: Path | None = None
) -> Path:
    path = snapshot_path(as_of, output_dir=output_dir)
    payload = {
        "asOf": as_of,
        "count": len(listings),
        "listings": [listing.__dict__ for listing in listings],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_snapshot(path: Path) -> list[EtfListing]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [EtfListing(**row) for row in payload["listings"]]


def latest_snapshot(*, output_dir: Path | None = None) -> Path | None:
    directory = output_dir or universe_dir()
    if not directory.exists():
        return None
    candidates = sorted(directory.glob("*.json"))
    return candidates[-1] if candidates else None


def sync_universe(*, as_of: str, output_dir: Path | None = None) -> dict[str, Any]:
    """Fetch today's (`as_of`) US ETF universe and save it. Read-only against
    the source — never touches `app/seed/` or the DB, matching
    `krx.py.sync_universe`'s split between fetch and load."""
    listings = fetch_us_etf_universe()
    if not listings:
        raise NasdaqTraderError(
            f"nasdaqtrader.com returned 0 ETFs for {as_of} — not writing a snapshot for it"
        )
    path = write_snapshot(listings, as_of=as_of, output_dir=output_dir)
    return {"asOf": as_of, "count": len(listings), "snapshotPath": str(path)}
