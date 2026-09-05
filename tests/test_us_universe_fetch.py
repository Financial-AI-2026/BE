"""Offline unit tests for `extraction/fetch/us_universe.py` — no network.

Fixture text mirrors the real nasdaqtrader.com column layout, including the
`File Creation Time: ...` footer line that isn't a data row.
"""

from extraction.fetch.us_universe import (
    EtfListing,
    fetch_us_etf_universe,
    parse_nasdaq_listed,
    parse_other_listed,
)

NASDAQ_LISTED_SAMPLE = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
    "QQQ|Invesco QQQ Trust|G|N|N|100|Y|N\n"
    "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
    "ZTEST|Nasdaq Test Symbol|G|Y|N|100|Y|N\n"
    "File Creation Time: 0904202609:46|||||||\n"
)

OTHER_LISTED_SAMPLE = (
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
    "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\n"
    "IBM|International Business Machines|N|IBM|N|100|N|IBM\n"
    "ZXIET|IEX Test Symbol|V|ZXIET|N|100|Y|ZXIET\n"
    "File Creation Time: 0904202609:46||||||\n"
)


def test_parse_nasdaq_listed_filters_to_etf_and_excludes_test_issues() -> None:
    listings = parse_nasdaq_listed(NASDAQ_LISTED_SAMPLE)

    assert listings == [
        EtfListing(code="QQQ", name="Invesco QQQ Trust", exchange="NASDAQ", source_file="nasdaqlisted")
    ]


def test_parse_other_listed_maps_exchange_code_to_readable_name() -> None:
    listings = parse_other_listed(OTHER_LISTED_SAMPLE)

    assert listings == [
        EtfListing(code="SPY", name="SPDR S&P 500 ETF Trust", exchange="NYSE Arca", source_file="otherlisted")
    ]


def test_fetch_us_etf_universe_unions_and_sorts_both_files() -> None:
    listings = fetch_us_etf_universe(
        nasdaq_text=NASDAQ_LISTED_SAMPLE, other_text=OTHER_LISTED_SAMPLE
    )

    assert [listing.code for listing in listings] == ["QQQ", "SPY"]


def test_fetch_us_etf_universe_nasdaq_wins_on_code_collision() -> None:
    other_text = OTHER_LISTED_SAMPLE.replace("SPY|SPDR S&P 500 ETF Trust", "QQQ|Wrong Name Here")
    nasdaq_text = NASDAQ_LISTED_SAMPLE

    listings = fetch_us_etf_universe(nasdaq_text=nasdaq_text, other_text=other_text)
    qqq = next(listing for listing in listings if listing.code == "QQQ")

    assert qqq.name == "Invesco QQQ Trust"
    assert qqq.source_file == "nasdaqlisted"
