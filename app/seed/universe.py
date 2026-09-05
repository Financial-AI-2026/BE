"""Upserts the full ETF universe (beyond the 8 MVP codes) into `etf_master`.

Distinct from `app/seed/load.py`: this only ever touches `etf_master` — code,
isin, name, market, manager, listed_at, exchange, source. It never writes
`etf_profile` / `etf_name_token` / `evidence` — those stay seed-file-driven
and MVP-only. A code with
no `etf_profile` row simply shows up in search as not-`ready`
(`EtfReadService.list_etfs`'s `ready` field) — that's the intended "분석 중"
state, not a bug.

Existing rows whose *current* `source` is `"manual"` (the 8 curated MVP
seeds) are left completely untouched on conflict — matched via a Postgres
`ON CONFLICT ... DO UPDATE ... WHERE` guard — so this loader can be re-run
freely (daily, even) without ever clobbering the curated `display_order` or
manually-verified name/manager fields.

Two sources feed this:
- Domestic: `extraction/fetch/krx.py`'s daily universe snapshots
  (`extraction/reports/krx_etf_universe/*.json`).
- Overseas (US): `extraction/fetch/us_universe.py`'s daily universe snapshots
  (`extraction/reports/us_etf_universe/*.json`).
Each has its own `EtfListing` type; `domestic_row`/`overseas_row` adapt them
into the shared `UniverseRow` that `upsert_universe` actually writes.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import EtfMaster
from extraction.fetch.krx import EtfListing as KrxListing
from extraction.fetch.krx import latest_snapshot as latest_krx_snapshot
from extraction.fetch.krx import read_snapshot as read_krx_snapshot
from extraction.fetch.us_universe import EtfListing as UsListing
from extraction.fetch.us_universe import latest_snapshot as latest_us_snapshot
from extraction.fetch.us_universe import read_snapshot as read_us_snapshot

# Columns `upsert_universe` writes/refreshes. Deliberately excludes
# `display_order` — new rows get NULL (the DB default) and existing rows are
# never touched for it, so "8 fixed cards" stays purely a `display_order`
# concern regardless of how large the universe grows.
_UPSERT_COLUMNS = ("isin", "name", "market", "manager", "listed_at", "exchange", "source")


@dataclass(frozen=True)
class UniverseRow:
    """Normalized shape `upsert_universe` writes to `etf_master`.

    Each fetch source (krx.py today, us_universe.py next) adapts its own
    listing type into this — keeps the DB-facing loader source-agnostic.
    """

    code: str
    isin: str | None
    name: str
    market: str
    manager: str | None = None
    listed_at: date | None = None
    exchange: str | None = None
    source: str = "auto"


# 국내 ETF는 KRX 상장 규정상 이름 맨 앞에 운용사 브랜드가 항상 붙는다
# (예: "TIGER 200" → 미래에셋자산운용). data.go.kr의 가격 조회 API
# (getETFPriceInfo)엔 운용사 필드가 아예 없어서, 별도 API 승인 없이 이
# 이름 접두어만으로 운용사를 채운다 — 2026-09-04 웹 검색 두 번으로 교차
# 검증했다. 2026-08-28 스냅샷(국내 1,163종) 기준
# 커버리지 99.4%(1,156/1,163) — 나머지 7종(TREX/TRUSTON/더제이/DS/KCGI)은
# 검증 못 해서 억지로 채우지 않고 그대로 `manager=None`("운용사 확인 중")
# 으로 남긴다 (근거 없이 회사명을 만들어내지 않는다).
MANAGER_BY_NAME_PREFIX = {
    "KODEX": "삼성자산운용",
    "TIGER": "미래에셋자산운용",
    "RISE": "KB자산운용",
    "ACE": "한국투자신탁운용",
    "PLUS": "한화자산운용",
    "SOL": "신한자산운용",
    "KIWOOM": "키움투자자산운용",
    "HANARO": "NH-Amundi자산운용",
    "1Q": "하나자산운용",
    "KoAct": "삼성액티브자산운용",
    "TIME": "타임폴리오자산운용",
    "WON": "우리자산운용",
    "에셋플러스": "에셋플러스자산운용",
    "마이티": "DB자산운용",
    "IBK": "IBK자산운용",
    "BNK": "BNK자산운용",
    "HK": "흥국자산운용",
    "FOCUS": "브이아이자산운용",
    "UNICORN": "현대자산운용",
    "MIDAS": "마이다스에셋자산운용",
    "파워": "교보악사자산운용",
    "DAISHIN": "대신자산운용",
    "아이엠에셋": "아이엠에셋자산운용",
}


def manager_from_name(name: str) -> str | None:
    prefix = name.split(None, 1)[0] if name.split(None, 1) else ""
    return MANAGER_BY_NAME_PREFIX.get(prefix)


def domestic_row(listing: KrxListing) -> UniverseRow | None:
    """Adapt one `krx.py` `EtfListing` — returns None for a row too broken to
    use (blank code or name; fail closed rather than seed junk rows)."""
    code = listing.code.strip()
    name = listing.name.strip()
    if not code or not name:
        return None
    return UniverseRow(
        code=code,
        isin=(listing.isin or "").strip() or None,
        name=name,
        market="KR",
        manager=manager_from_name(name),
        source="auto",
    )


def domestic_rows_from_listings(listings: Iterable[KrxListing]) -> list[UniverseRow]:
    rows: list[UniverseRow] = []
    seen_codes: set[str] = set()
    for listing in listings:
        row = domestic_row(listing)
        if row is None or row.code in seen_codes:
            continue
        seen_codes.add(row.code)
        rows.append(row)
    return rows


# 미국은 한국(KRX)과 달리 "이름 맨 앞 = 운용사 브랜드"가 상장 규정으로
# 못박혀 있진 않지만, 실무상 대부분의 발행사가 그렇게 짓는다. 국내처럼
# 접두어 하나로 끝나지 않아 다어절 브랜드(예: "First Trust", "T. Rowe
# Price")가 많아서, 각 항목은 실제 2026-09-04 스냅샷(5,656종) 샘플을
# 직접 찍어서 확인한 문자열 그대로다(예: "Franklin"이 실제로 그 한 단어로
# 끝나는지, "Northern"이 사실 "Northern Trust"인지 등 — 짐작하지 않았다).
# `manager` 값도 이 표에 있는 문자열을 그대로 쓴다(추측 번역 없이 이름에서
# 그대로 뽑아온 것이라 창작 리스크가 없다). 커버리지 81.0%(4,582/5,656) —
# 국내(99.4%)보다 낮은 건 미국 쪽 발행사 롱테일이 훨씬 길고 흩어져 있어서다.
US_ISSUER_PREFIXES = sorted(
    [
        "iShares", "Invesco", "Corgi", "Innovator", "First Trust", "State Street",
        "ProShares", "FT Vest", "Direxion", "Leverage Shares", "Global X", "Vanguard",
        "WisdomTree", "GraniteShares", "VanEck", "Defiance", "Fidelity", "Tradr",
        "JPMorgan", "Pacer", "PGIM", "Franklin", "YieldMax", "AllianzIM", "Roundhill",
        "Northern Trust", "Goldman Sachs", "Amplify", "Calamos", "Simplify",
        "Xtrackers", "Dimensional", "Harbor", "KraneShares", "T. Rowe Price",
        "MicroSectors", "Schwab", "T-REX", "Avantis", "Nuveen",
        "Virtus", "Capital Group", "Columbia", "VictoryShares", "American Century",
        "AB", "TrueShares", "BNY Mellon", "ALPS", "Horizon", "NYLIM", "BondBloxx",
        "Cambria", "John Hancock", "NEOS", "Sprott", "Janus Henderson", "F/m",
        "Nicholas", "Motley Fool", "Timothy Plan", "Federated Hermes", "LifeX",
        "Tema", "Matthews", "TCW", "ARK", "AdvisorShares", "Neuberger", "Kurv",
        "Grayscale", "Principal", "Hartford", "Aptus", "PIMCO", "VistaShares",
        "abrdn", "SEI", "MFS", "Strive", "Eaton Vance", "21Shares", "Bitwise",
        "REX", "Teucrium", "DoubleLine", "Touchstone", "Overlay Shares",
        "Truth Social", "Return Stacked",
    ],
    key=len,
    reverse=True,
)


def issuer_from_name(name: str) -> str | None:
    folded = name.casefold()
    for prefix in US_ISSUER_PREFIXES:
        folded_prefix = prefix.casefold()
        if folded == folded_prefix or folded.startswith(folded_prefix + " "):
            return prefix
    return None


def overseas_row(listing: UsListing) -> UniverseRow | None:
    """Adapt one `us_universe.py` `EtfListing` — mirrors `domestic_row`."""
    code = listing.code.strip()
    name = listing.name.strip()
    if not code or not name:
        return None
    return UniverseRow(
        code=code,
        isin=None,  # nasdaqtrader.com's symbol directories don't carry ISIN
        name=name,
        market="US",
        manager=issuer_from_name(name),
        exchange=listing.exchange,
        source="auto",
    )


def overseas_rows_from_listings(listings: Iterable[UsListing]) -> list[UniverseRow]:
    rows: list[UniverseRow] = []
    seen_codes: set[str] = set()
    for listing in listings:
        row = overseas_row(listing)
        if row is None or row.code in seen_codes:
            continue
        seen_codes.add(row.code)
        rows.append(row)
    return rows


def upsert_universe(session: Session, rows: Iterable[UniverseRow]) -> int:
    """Upsert `rows` into `etf_master`. Returns how many were sent.

    A conflicting existing row is refreshed only if its current `source` is
    not `"manual"` — the 8 MVP seed rows are always `"manual"` and are never
    touched here, by construction rather than by hardcoding their codes.
    """
    payload: list[dict[str, Any]] = [
        {
            "code": row.code,
            "isin": row.isin,
            "name": row.name,
            "market": row.market,
            "manager": row.manager,
            "listed_at": row.listed_at,
            "exchange": row.exchange,
            "source": row.source,
        }
        for row in rows
    ]
    if not payload:
        return 0

    table = EtfMaster.__table__
    stmt = insert(table).values(payload)
    update_values = {column: stmt.excluded[column] for column in _UPSERT_COLUMNS}
    stmt = stmt.on_conflict_do_update(
        index_elements=["code"],
        set_=update_values,
        where=table.c.source != "manual",
    )
    session.execute(stmt)
    return len(payload)


def load_domestic_from_snapshot(session: Session, *, snapshot_path: Path | None = None) -> int:
    path = snapshot_path or latest_krx_snapshot()
    if path is None:
        raise SystemExit(
            "no KRX universe snapshot found under extraction/reports/krx_etf_universe/ — "
            "run `python -m extraction krx-universe` first"
        )
    listings = read_krx_snapshot(path)
    rows = domestic_rows_from_listings(listings)
    return upsert_universe(session, rows)


def load_overseas_from_snapshot(session: Session, *, snapshot_path: Path | None = None) -> int:
    path = snapshot_path or latest_us_snapshot()
    if path is None:
        raise SystemExit(
            "no US universe snapshot found under extraction/reports/us_etf_universe/ — "
            "run `python -m extraction us-universe` first"
        )
    listings = read_us_snapshot(path)
    rows = overseas_rows_from_listings(listings)
    return upsert_universe(session, rows)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.seed.universe")
    parser.add_argument(
        "--market",
        choices=["KR", "US", "ALL"],
        default="ALL",
        help="적재할 시장. ALL이면 국내+해외를 모두 적재",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="특정 스냅샷 파일 경로 (KR/US 단독 지정 시에만 유효, 기본: 가장 최근 파일)",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        total = 0
        if args.market in ("KR", "ALL"):
            count = load_domestic_from_snapshot(session, snapshot_path=args.snapshot)
            print(f"upserted {count} domestic (KR) ETF rows into etf_master")
            total += count
        if args.market in ("US", "ALL"):
            count = load_overseas_from_snapshot(session, snapshot_path=args.snapshot)
            print(f"upserted {count} overseas (US) ETF rows into etf_master")
            total += count
        session.commit()
    print(f"total upserted: {total}")


if __name__ == "__main__":
    main()
