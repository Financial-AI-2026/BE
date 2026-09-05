"""Offline unit tests for `app/seed/universe.py`'s pure adapters — no DB.

`manager_from_name` in particular is a regression lock for the brand-prefix
lookup: KRX requires the issuer's brand to lead the ETF name, so this is a
zero-API-cost way to fill `manager` for the ~99% of the domestic universe
that data.go.kr's price API itself doesn't carry it for (cross-checked via
web search, not invented — see the comment above `MANAGER_BY_NAME_PREFIX`).
"""

from extraction.fetch.krx import EtfListing as KrxListing
from extraction.fetch.us_universe import EtfListing as UsListing

from app.seed.universe import (
    domestic_row,
    domestic_rows_from_listings,
    issuer_from_name,
    manager_from_name,
    overseas_row,
)


def _krx_listing(code: str, name: str, isin: str = "") -> KrxListing:
    return KrxListing(
        code=code,
        isin=isin,
        name=name,
        close_price=None,
        nav=None,
        market_cap=None,
        listed_units=None,
        base_index_name=None,
    )


def test_manager_from_name_matches_known_brand_prefix() -> None:
    assert manager_from_name("TIGER 200") == "미래에셋자산운용"
    assert manager_from_name("KODEX 인도Nifty미드캡100") == "삼성자산운용"
    assert manager_from_name("KoAct 코리아밸류업액티브") == "삼성액티브자산운용"


def test_manager_from_name_returns_none_for_unknown_brand() -> None:
    # 웹 검색으로 확인 안 된 롱테일 브랜드 — 억지로 채우지 않는다 (fail closed).
    assert manager_from_name("KCGI 미국S&P500 TOP10") is None
    assert manager_from_name("") is None


def test_domestic_row_fills_manager_from_name_prefix() -> None:
    row = domestic_row(_krx_listing("102110", "TIGER 200", isin="KR7102110004"))

    assert row.manager == "미래에셋자산운용"
    assert row.market == "KR"
    assert row.source == "auto"


def test_domestic_row_returns_none_for_blank_code_or_name() -> None:
    assert domestic_row(_krx_listing("", "TIGER 200")) is None
    assert domestic_row(_krx_listing("102110", "")) is None


def test_domestic_rows_from_listings_dedupes_by_code() -> None:
    listings = [
        _krx_listing("102110", "TIGER 200"),
        _krx_listing("102110", "TIGER 200 (dup)"),
    ]

    rows = domestic_rows_from_listings(listings)

    assert len(rows) == 1
    assert rows[0].code == "102110"


def test_issuer_from_name_matches_known_issuer_prefix_case_insensitively() -> None:
    assert issuer_from_name("Invesco QQQ Trust") == "Invesco"
    assert issuer_from_name("T-Rex 2X Long Apple Daily Target ETF") == "T-REX"
    assert issuer_from_name("Global X NASDAQ 100 Covered Call ETF") == "Global X"


def test_issuer_from_name_returns_none_for_unknown_issuer() -> None:
    # 짧고 흔한 단어("The", "US", "2x" 등)는 실제 회사 식별자가 아니라서
    # 표에 일부러 안 넣었다 — 매칭 안 되는 게 맞는 동작.
    assert issuer_from_name("The Beehive ETF") is None
    assert issuer_from_name("") is None


def test_overseas_row_never_fabricates_isin_but_fills_manager_from_name() -> None:
    listing = UsListing(code="QQQ", name="Invesco QQQ Trust", exchange="NASDAQ", source_file="nasdaqlisted")

    row = overseas_row(listing)

    assert row.isin is None  # nasdaqtrader.com 심볼 디렉토리엔 ISIN이 없다
    assert row.manager == "Invesco"  # 이름에서 그대로 뽑아온 것 — 창작 아님
    assert row.exchange == "NASDAQ"
    assert row.market == "US"


def test_overseas_row_leaves_manager_none_for_unknown_issuer() -> None:
    listing = UsListing(code="ABCD", name="Some Tiny Issuer Fund ETF", exchange="NASDAQ", source_file="nasdaqlisted")

    row = overseas_row(listing)

    assert row.manager is None
