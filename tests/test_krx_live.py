"""Live data.go.kr regression — hits the real GetSecuritiesProductInfoService
API. Skipped by default so `pytest` stays network-free; run explicitly:

    KRX_LIVE_TESTS=1 .venv/bin/python -m pytest tests/test_krx_live.py -v
"""

from __future__ import annotations

import os

import pytest

from extraction.fetch.krx import DataGoKrClient, fetch_etf_universe, load_data_go_kr_key
from extraction.scoring import DOMESTIC_CODES

pytestmark = pytest.mark.skipif(
    os.environ.get("KRX_LIVE_TESTS") != "1" or not load_data_go_kr_key(),
    reason=(
        "live data.go.kr regression is opt-in: set KRX_LIVE_TESTS=1 with a "
        "DATA_GO_KR_API_KEY in .env to run it"
    ),
)


def test_domestic_six_codes_appear_in_the_current_etf_universe() -> None:
    client = DataGoKrClient(load_data_go_kr_key())
    # A recent past business day — the API returns nothing for a date that
    # hasn't been published yet (see extraction/fetch/krx.py's empty-response
    # guard), so "today" isn't safe to hardcode here.
    listings = fetch_etf_universe(client, bas_dd="20260828")

    codes = {listing.code for listing in listings}
    missing = set(DOMESTIC_CODES) - codes
    assert not missing, f"missing from live KRX ETF universe: {sorted(missing)}"
    assert len(listings) > 1000, f"suspiciously small ETF universe: {len(listings)}"
