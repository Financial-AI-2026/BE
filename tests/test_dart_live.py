"""Live OpenDART regression — hits real DART endpoints over the network.

This is Gate D-2: for each of the 6 domestic MVP codes, does the production fetch
path (`run_domestic_dart_pdf_spike`, `download_limit=1`) still resolve to a filing
whose PDF is byte-identical to the pipeline's current `extraction/raw/{code}/{code}.pdf`?
It also guards the two concrete failure modes found while building this path:
DART listing a stale/wrong-version filing (the 448290 incident) and the fetch
matching more than one distinct fund (`ambiguous`).

Skipped by default so `pytest` stays network-free — network-dependent tests
should stay out of the default unit test run.

Run explicitly:
    DART_LIVE_TESTS=1 .venv/bin/python -m pytest tests/test_dart_live.py -v
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from extraction.fetch.dart import load_opendart_key, run_domestic_dart_pdf_spike
from extraction.scoring import DOMESTIC_CODES

pytestmark = pytest.mark.skipif(
    os.environ.get("DART_LIVE_TESTS") != "1" or not load_opendart_key(),
    reason=(
        "live DART regression is opt-in: set DART_LIVE_TESTS=1 with a DART API key "
        "in .env to run it"
    ),
)


def test_domestic_six_codes_resolve_to_current_raw_pdf_hash() -> None:
    results = run_domestic_dart_pdf_spike(codes=DOMESTIC_CODES, download_limit=1)
    failures: list[str] = []

    for result in results:
        code = result["code"]
        raw_path = Path("extraction/raw") / code / f"{code}.pdf"
        if not raw_path.exists():
            failures.append(f"{code}: no raw PDF at {raw_path} to compare against")
            continue
        if result.get("ambiguous"):
            failures.append(f"{code}: DART match is ambiguous — {result.get('targetIdentities')}")
            continue

        downloads = [
            download
            for web_pdf in result["webPdfs"]
            for download in web_pdf["downloads"]
            if download["isPdf"] and download["contentTypeOk"]
        ]
        if not downloads:
            failures.append(f"{code}: no valid PDF downloaded from DART")
            continue

        dart_hash = downloads[0]["sha256"]
        raw_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if dart_hash != raw_hash:
            failures.append(
                f"{code}: DART PDF ({dart_hash[:12]}...) no longer matches "
                f"raw/ pipeline input ({raw_hash[:12]}...) — re-check whether "
                f"raw/ needs a deliberate refresh, not an automatic overwrite"
            )

    assert not failures, "\n".join(failures)
