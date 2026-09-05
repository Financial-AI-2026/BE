from __future__ import annotations

import json
import os
import ssl
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from extraction.paths import REPORTS_DIR, ensure_output_dirs

BASE_URL = "https://apis.data.go.kr/1160100/service/GetSecuritiesProductInfoService"
KEY_NAMES = ("DATA_GO_KR_API_KEY", "DATA_GO_KR_KEY", "PUBLIC_DATA_API_KEY")
UNIVERSE_DIR_NAME = "krx_etf_universe"


class DataGoKrError(RuntimeError):
    pass


@dataclass(frozen=True)
class EtfListing:
    """One row of `getETFPriceInfo` for a single trading date.

    `srtnCd` from the API is the plain 6-character KRX ticker for ETFs (unlike the
    stock registry API, which prefixes it with "A") — it matches our `code` values
    (e.g. "418660") directly, confirmed against all 6 domestic MVP codes.
    """

    code: str
    isin: str
    name: str
    close_price: str | None
    nav: str | None
    market_cap: str | None
    listed_units: str | None
    base_index_name: str | None

    @classmethod
    def from_api_item(cls, item: dict[str, Any]) -> EtfListing:
        return cls(
            code=str(item.get("srtnCd", "")).strip(),
            isin=str(item.get("isinCd", "")).strip(),
            name=str(item.get("itmsNm", "")).strip(),
            close_price=item.get("clpr"),
            nav=item.get("nav"),
            market_cap=item.get("mrktTotAmt"),
            listed_units=item.get("stLstgCnt"),
            base_index_name=item.get("bssIdxIdxNm"),
        )


@dataclass(frozen=True)
class UniverseDiff:
    """Raw set difference between two daily snapshots.

    A code missing from `current` is only a *candidate* delisting, not a
    confirmed one — a single day can also mean a trading halt or a holiday gap
    in the source data. Callers should require a code to stay absent across
    several consecutive snapshots before treating it as delisted; this
    function deliberately does not encode that policy, only the raw diff.
    """

    as_of: str
    compared_to: str | None
    added: tuple[EtfListing, ...]
    removed_codes: tuple[str, ...]


class DataGoKrClient:
    def __init__(self, api_key: str, *, base_url: str = BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def get_json(self, operation: str, params: dict[str, str | int | None]) -> dict[str, Any]:
        query = {"serviceKey": self.api_key, "resultType": "json"}
        query.update({key: value for key, value in params.items() if value is not None})
        url = f"{self.base_url}/{operation}?{urlencode(query)}"
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=30, context=ssl_context()) as response:
            payload = response.read()
        data = json.loads(payload)
        header = data.get("response", {}).get("header", {})
        result_code = str(header.get("resultCode", ""))
        if result_code != "00":
            raise DataGoKrError(
                f"data.go.kr {operation} failed: {result_code} {header.get('resultMsg')}"
            )
        return data


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ModuleNotFoundError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def load_data_go_kr_key(env_path: Path = Path(".env")) -> str | None:
    for key_name in KEY_NAMES:
        value = os.environ.get(key_name)
        if value:
            return value.strip()
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in KEY_NAMES and value.strip():
            return value.strip().strip('"').strip("'")
    return None


def fetch_etf_universe(
    client: DataGoKrClient, *, bas_dd: str, page_count: int = 1000
) -> list[EtfListing]:
    """Fetch every ETF listed on `bas_dd` (a KRX trading day, YYYYMMDD).

    Paginates using `numOfRows`/`pageNo` against `totalCount` rather than
    trusting a single large `numOfRows` to return everything in one call —
    ~1,163 ETFs were listed as of 2026-08-28 and that count only grows.
    """
    # Safety cap on page count: a wrong/ignored request param doesn't error, it
    # just makes the API return its *entire* unfiltered history (~1.19M rows as
    # of 2026-08-28, against ~1,163 ETFs on any single day) — this bit us once
    # already (basDd vs the real param name basDt) and silently turned into an
    # hours-long pagination loop instead of a fast failure. 20 pages at
    # page_count=1000 covers the current ETF universe many times over.
    max_pages = 20
    listings: list[EtfListing] = []
    page_no = 1
    total_count: int | None = None
    while total_count is None or len(listings) < total_count:
        if page_no > max_pages:
            raise DataGoKrError(
                f"getETFPriceInfo for {bas_dd} exceeded {max_pages} pages "
                f"(totalCount={total_count}, fetched={len(listings)}) — likely a "
                "malformed request param rather than a genuine ETF count this large"
            )
        data = client.get_json(
            "getETFPriceInfo",
            {"basDt": bas_dd, "numOfRows": page_count, "pageNo": page_no},
        )
        body = data.get("response", {}).get("body", {})
        total_count = int(body.get("totalCount") or 0)
        items = (body.get("items") or {}).get("item") or []
        if isinstance(items, dict):
            items = [items]
        listings.extend(EtfListing.from_api_item(item) for item in items)
        if not items:
            break
        page_no += 1
    return listings


def universe_dir() -> Path:
    ensure_output_dirs()
    path = REPORTS_DIR / UNIVERSE_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_path(bas_dd: str, *, output_dir: Path | None = None) -> Path:
    return (output_dir or universe_dir()) / f"{bas_dd}.json"


def write_snapshot(
    listings: list[EtfListing], *, bas_dd: str, output_dir: Path | None = None
) -> Path:
    path = snapshot_path(bas_dd, output_dir=output_dir)
    payload = {
        "basDd": bas_dd,
        "count": len(listings),
        "listings": [listing.__dict__ for listing in listings],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_snapshot(path: Path) -> list[EtfListing]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [EtfListing(**row) for row in payload["listings"]]


def latest_prior_snapshot(bas_dd: str, *, output_dir: Path | None = None) -> Path | None:
    """The most recent snapshot file strictly before `bas_dd`, if any exist."""
    directory = output_dir or universe_dir()
    if not directory.exists():
        return None
    candidates = sorted(
        (path for path in directory.glob("*.json") if path.stem < bas_dd),
        key=lambda path: path.stem,
    )
    return candidates[-1] if candidates else None


def latest_snapshot(*, output_dir: Path | None = None) -> Path | None:
    """The most recent snapshot file on disk overall, if any exist.

    Unlike `latest_prior_snapshot`, this isn't relative to any particular
    `bas_dd` — used by `app/seed/universe.py` to load "whatever we last
    fetched" without the caller having to know the date.
    """
    directory = output_dir or universe_dir()
    if not directory.exists():
        return None
    candidates = sorted(directory.glob("*.json"))
    return candidates[-1] if candidates else None


def diff_universes(previous: list[EtfListing], current: list[EtfListing]) -> UniverseDiff:
    previous_codes = {listing.code: listing for listing in previous}
    current_codes = {listing.code: listing for listing in current}
    added = tuple(
        listing for code, listing in current_codes.items() if code not in previous_codes
    )
    removed = tuple(sorted(code for code in previous_codes if code not in current_codes))
    return UniverseDiff(as_of="", compared_to=None, added=added, removed_codes=removed)


def sync_universe(
    *,
    bas_dd: str | None = None,
    api_key: str | None = None,
    output_dir: Path | None = None,
    client: DataGoKrClient | None = None,
) -> dict[str, Any]:
    """Fetch today's (or `bas_dd`'s) ETF universe, save it, and diff against
    the most recent prior snapshot on disk. Read-only against the source —
    never touches `app/seed/` or the DB. This is universe *detection* only,
    not the (separately designed, currently-deferred) review/promotion pipeline.
    """
    if client is None:
        key = api_key or load_data_go_kr_key()
        if not key:
            raise DataGoKrError(
                "data.go.kr API key not found. Set one of: " + ", ".join(KEY_NAMES)
            )
        client = DataGoKrClient(key)

    bas_dd = bas_dd or date.today().strftime("%Y%m%d")
    listings = fetch_etf_universe(client, bas_dd=bas_dd)
    if not listings:
        # Fail closed rather than write a snapshot and diff against it: an empty
        # response almost always means the date has no data yet (weekend,
        # holiday, or today before the daily publish), not that every ETF was
        # delisted at once. Writing it anyway would make the *next* real sync
        # diff against a bogus empty baseline and report a false mass-delisting.
        raise DataGoKrError(
            f"getETFPriceInfo returned 0 ETFs for {bas_dd} — likely a non-trading "
            "day or data not yet published; not writing a snapshot for it"
        )
    path = write_snapshot(listings, bas_dd=bas_dd, output_dir=output_dir)

    prior_path = latest_prior_snapshot(bas_dd, output_dir=output_dir)
    if prior_path is None:
        diff = UniverseDiff(as_of=bas_dd, compared_to=None, added=(), removed_codes=())
    else:
        previous = read_snapshot(prior_path)
        raw_diff = diff_universes(previous, listings)
        diff = UniverseDiff(
            as_of=bas_dd,
            compared_to=prior_path.stem,
            added=raw_diff.added,
            removed_codes=raw_diff.removed_codes,
        )

    return {
        "basDd": bas_dd,
        "count": len(listings),
        "snapshotPath": str(path),
        "comparedTo": diff.compared_to,
        "added": [listing.__dict__ for listing in diff.added],
        "removedCodes": list(diff.removed_codes),
    }

