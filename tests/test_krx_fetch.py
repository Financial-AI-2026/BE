"""Offline unit tests for `extraction/fetch/krx.py` — no network.

The pagination-cap test is a direct regression for a bug hit while building
this: the request used `basDd` instead of the API's actual `basDt` param. The
API didn't error on the wrong param — it silently ignored it and returned its
entire unfiltered history (~1.19M rows against ~1,163 ETFs on any single day),
turning pagination into an hours-long loop instead of a fast, visible failure.
"""

from pathlib import Path
from typing import Any

import pytest

from extraction.fetch.krx import (
    DataGoKrError,
    EtfListing,
    diff_universes,
    fetch_etf_universe,
    latest_prior_snapshot,
    read_snapshot,
    sync_universe,
    write_snapshot,
)


class FakeDataGoKrClient:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.requested_page_nos: list[int] = []

    def get_json(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        assert operation == "getETFPriceInfo"
        assert params["basDt"] == "20260828"
        page_no = params["pageNo"]
        self.requested_page_nos.append(page_no)
        page = self.pages[page_no - 1]
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {"totalCount": page["totalCount"], "items": {"item": page["items"]}},
            }
        }


def _item(code: str, name: str = "테스트ETF") -> dict[str, Any]:
    return {"srtnCd": code, "isinCd": f"KR{code}", "itmsNm": name, "clpr": "10000"}


def test_etf_listing_from_api_item_maps_srtn_cd_directly_to_code() -> None:
    # Unlike the stock registry API (srtnCd="A005930"), ETF srtnCd has no "A"
    # prefix and matches our `code` values directly — confirmed live against
    # all 6 domestic MVP codes.
    listing = EtfListing.from_api_item(_item("418660", "TIGER 미국나스닥100레버리지(합성)"))

    assert listing.code == "418660"
    assert listing.name == "TIGER 미국나스닥100레버리지(합성)"


def test_fetch_etf_universe_paginates_until_total_count_is_reached() -> None:
    client = FakeDataGoKrClient(
        pages=[
            {"totalCount": 3, "items": [_item("100000"), _item("100001")]},
            {"totalCount": 3, "items": [_item("100002")]},
        ]
    )

    listings = fetch_etf_universe(client, bas_dd="20260828", page_count=2)

    assert [listing.code for listing in listings] == ["100000", "100001", "100002"]
    assert client.requested_page_nos == [1, 2]  # stopped once totalCount was reached


def test_fetch_etf_universe_raises_instead_of_looping_forever_on_bad_params() -> None:
    # Regression: a wrong param name doesn't error, it makes totalCount huge
    # relative to what a page ever returns. This must fail fast, not hang.
    client = FakeDataGoKrClient(
        pages=[{"totalCount": 10_000_000, "items": [_item(f"{n:06d}") for n in range(50)]}] * 25
    )

    with pytest.raises(DataGoKrError, match="exceeded 20 pages"):
        fetch_etf_universe(client, bas_dd="20260828", page_count=50)


def test_diff_universes_reports_added_and_removed_codes() -> None:
    previous = [EtfListing.from_api_item(_item("102110", "TIGER 200"))]
    current = [
        EtfListing.from_api_item(_item("102110", "TIGER 200")),
        EtfListing.from_api_item(_item("418660", "TIGER 미국나스닥100레버리지(합성)")),
    ]

    diff = diff_universes(previous, current)

    assert [listing.code for listing in diff.added] == ["418660"]
    assert diff.removed_codes == ()


def test_diff_universes_flags_disappeared_codes_as_removed() -> None:
    previous = [
        EtfListing.from_api_item(_item("102110")),
        EtfListing.from_api_item(_item("418660")),
    ]
    current = [EtfListing.from_api_item(_item("102110"))]

    diff = diff_universes(previous, current)

    assert diff.added == ()
    assert diff.removed_codes == ("418660",)


def test_sync_universe_fails_closed_and_writes_nothing_on_empty_response(
    tmp_path: Path,
) -> None:
    client = FakeDataGoKrClient(pages=[{"totalCount": 0, "items": []}])

    with pytest.raises(DataGoKrError, match="returned 0 ETFs"):
        sync_universe(bas_dd="20260828", output_dir=tmp_path, client=client)  # type: ignore[arg-type]

    assert list(tmp_path.glob("*.json")) == []


def test_sync_universe_reports_added_and_removed_against_prior_snapshot(
    tmp_path: Path,
) -> None:
    write_snapshot(
        [EtfListing.from_api_item(_item("102110", "TIGER 200"))],
        bas_dd="20260827",
        output_dir=tmp_path,
    )
    client = FakeDataGoKrClient(
        pages=[
            {
                "totalCount": 1,
                "items": [_item("418660", "TIGER 미국나스닥100레버리지(합성)")],
            }
        ]
    )

    result = sync_universe(bas_dd="20260828", output_dir=tmp_path, client=client)  # type: ignore[arg-type]

    assert result["comparedTo"] == "20260827"
    assert [item["code"] for item in result["added"]] == ["418660"]
    assert result["removedCodes"] == ["102110"]


def test_sync_universe_diffs_against_the_most_recent_prior_snapshot(
    tmp_path: Path,
) -> None:
    prior = [
        EtfListing.from_api_item(_item("102110", "TIGER 200")),
        EtfListing.from_api_item(_item("133690", "TIGER 미국나스닥100")),
    ]
    write_snapshot(prior, bas_dd="20260101", output_dir=tmp_path)
    # a same-week-but-later file must NOT be picked as "prior" once it's after bas_dd
    future = [EtfListing.from_api_item(_item("999999", "미래종목"))]
    write_snapshot(future, bas_dd="20261231", output_dir=tmp_path)

    path = latest_prior_snapshot("20260828", output_dir=tmp_path)
    assert path is not None
    assert path.stem == "20260101"
    assert {listing.code for listing in read_snapshot(path)} == {"102110", "133690"}
