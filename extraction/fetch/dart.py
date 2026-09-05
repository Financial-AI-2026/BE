from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from extraction.paths import REPORTS_DIR, ensure_output_dirs
from extraction.scoring import DOMESTIC_CODES

BASE_URL = "https://opendart.fss.or.kr/api"
DART_WEB_URL = "https://dart.fss.or.kr"
DEFAULT_MANAGER_QUERY = "미래에셋자산운용"
KEY_NAMES = ("OPENDART_API_KEY", "OPEN_DART_API_KEY", "DART_API_KEY", "DART_CRTFC_KEY")
DOMESTIC_DART_PRODUCT_QUERIES = {
    "418660": "TIGER미국나스닥100레버리지증권상장지수투자신탁",
    "441680": "TIGER미국나스닥100커버드콜증권상장지수투자신탁",
    "435420": "TIGER미국나스닥100채권혼합50증권상장지수투자신탁",
    # Trailing "(주식)" is required: without it this also substring-matches a
    # different, currency-hedged fund whose report_nm ends in
    # "...투자신탁(주식파생형)(H))" — the new ambiguous-filing check caught this
    # as a live regression (2026-09-01) before it could silently pick either one.
    "133690": "TIGER미국나스닥100증권상장지수투자신탁(주식)",
    "448290": "TIGER미국S&P500증권상장지수투자신탁(주식-파생형)(H)",
    "102110": "TIGER200증권상장지수투자신탁",
}


@dataclass(frozen=True)
class CorpCode:
    corp_code: str
    corp_name: str
    stock_code: str | None
    modify_date: str | None


@dataclass(frozen=True)
class ZipMemberInspection:
    filename: str
    size: int
    kind: str
    mentions_code: bool
    mentions_product_name: bool


class OpenDartError(RuntimeError):
    pass


class OpenDartClient:
    def __init__(self, api_key: str, *, base_url: str = BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def get_json(self, endpoint: str, params: dict[str, str | int | None]) -> dict[str, Any]:
        payload = self.get_bytes(endpoint, params)
        return json.loads(payload.decode("utf-8"))

    def get_bytes(self, endpoint: str, params: dict[str, str | int | None]) -> bytes:
        query = {"crtfc_key": self.api_key}
        query.update({key: value for key, value in params.items() if value is not None})
        url = f"{self.base_url}/{endpoint}?{urlencode(query)}"
        with urlopen(url, timeout=30, context=ssl_context()) as response:
            return response.read()


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ModuleNotFoundError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def run_dart_spike(
    *,
    code: str,
    product_name: str | None = None,
    manager_query: str = DEFAULT_MANAGER_QUERY,
    bgn_de: str = "20240101",
    end_de: str | None = None,
    download_limit: int = 3,
    api_key: str | None = None,
    output_dir: Path | None = None,
    client: OpenDartClient | None = None,
    corp_codes: list[CorpCode] | None = None,
    fund_disclosures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ensure_output_dirs()
    key = api_key or load_opendart_key()
    if not key and client is None:
        raise OpenDartError(
            "OpenDART API key was not found. Set one of: " + ", ".join(KEY_NAMES)
        )

    client = client or OpenDartClient(key or "")
    end_de = end_de or date.today().strftime("%Y%m%d")
    display_name = product_name or load_product_name(code)
    product_query = DOMESTIC_DART_PRODUCT_QUERIES.get(code, display_name)
    out_dir = output_dir or REPORTS_DIR / "opendart_spike" / code
    out_dir.mkdir(parents=True, exist_ok=True)

    corp_codes = corp_codes or fetch_corp_codes(client)
    stock_code_matches = [corp for corp in corp_codes if corp.stock_code == code]
    normalized_manager_query = manager_query.replace(" ", "")
    manager_matches = [
        corp
        for corp in corp_codes
        if normalized_manager_query in corp.corp_name.replace(" ", "")
    ]
    selected_manager = choose_manager_corp(manager_matches)

    if fund_disclosures is None:
        fund_disclosures = search_target_fund_filings(
            client,
            product_query=product_query,
            bgn_de=bgn_de,
            end_de=end_de,
            limit=download_limit,
            corp_code=selected_manager.corp_code if selected_manager else None,
        )
    filings: list[dict[str, Any]] = list(fund_disclosures)
    # The `pblntf_ty=G` fund-disclosure search above already covers what we need in
    # the normal case. Only fall back to a full per-corp filing history scan (up to
    # ~2.5 years of a manager's *entire* disclosure history, hundreds of list.json
    # pages) when that search came up empty — falling back unconditionally made every
    # call redo a multi-minute scan for no benefit once fund_disclosures had already
    # found the target.
    needs_fallback_search = not fund_disclosures
    if stock_code_matches and needs_fallback_search:
        filings.extend(
            search_filings(
                client,
                bgn_de=bgn_de,
                end_de=end_de,
                corp_code=stock_code_matches[0].corp_code,
            )
        )
    if selected_manager and needs_fallback_search:
        filings.extend(
            search_filings(
                client,
                bgn_de=bgn_de,
                end_de=end_de,
                corp_code=selected_manager.corp_code,
            )
        )

    unique_filings = dedupe_filings(filings)
    prospectus_filings = [
        filing for filing in unique_filings if "투자설명서" in str(filing.get("report_nm", ""))
    ]
    target_filings = sort_filings_latest_first(
        filter_target_filings(prospectus_filings, product_query)
    )
    ambiguous = has_ambiguous_target_filings(target_filings)
    target_identities = sorted({filing_identity(f.get("report_nm", "")) for f in target_filings})
    if ambiguous:
        selected_filings: list[dict[str, Any]] = []
    else:
        selected_filings = (target_filings or prospectus_filings)[:download_limit]

    downloaded = [
        download_and_inspect_document(
            client,
            filing=filing,
            code=code,
            product_name=product_query,
            output_dir=out_dir,
        )
        for filing in selected_filings
    ]
    web_pdfs = [
        safe_inspect_web_pdf_downloads(filing=filing, output_dir=out_dir)
        for filing in selected_filings
    ]
    result = {
        "code": code,
        "productName": display_name,
        "productQuery": product_query,
        "managerQuery": manager_query,
        "bgnDe": bgn_de,
        "endDe": end_de,
        "fundDisclosureCount": len(fund_disclosures),
        "stockCodeMatches": [corp.__dict__ for corp in stock_code_matches],
        "managerMatches": [corp.__dict__ for corp in manager_matches],
        "selectedManager": selected_manager.__dict__ if selected_manager else None,
        "filingCount": len(unique_filings),
        "prospectusFilingCount": len(prospectus_filings),
        "targetFilingCount": len(target_filings),
        "sampleReportNames": sorted(
            {str(filing.get("report_nm", "")) for filing in prospectus_filings}
        )[:20],
        "targetReportNames": [
            str(filing.get("report_nm", "")) for filing in target_filings[:download_limit]
        ],
        "ambiguous": ambiguous,
        "targetIdentities": target_identities,
        "selectedFilings": selected_filings,
        "downloaded": downloaded,
        "webPdfs": web_pdfs,
        "mappingConclusion": conclude_mapping(
            stock_code_matches, downloaded, web_pdfs, ambiguous=ambiguous
        ),
    }
    write_spike_report(result, out_dir)
    return result


def run_domestic_dart_pdf_spike(
    *,
    codes: tuple[str, ...] = DOMESTIC_CODES,
    bgn_de: str = "20240101",
    end_de: str | None = None,
    download_limit: int = 1,
) -> list[dict[str, Any]]:
    key = load_opendart_key()
    if not key:
        raise OpenDartError(
            "OpenDART API key was not found. Set one of: " + ", ".join(KEY_NAMES)
        )
    client = OpenDartClient(key)
    end_de = end_de or date.today().strftime("%Y%m%d")
    corp_codes = fetch_corp_codes(client)
    return [
        run_dart_spike(
            code=code,
            bgn_de=bgn_de,
            end_de=end_de,
            download_limit=download_limit,
            client=client,
            corp_codes=corp_codes,
        )
        for code in codes
    ]


def load_opendart_key(env_path: Path = Path(".env")) -> str | None:
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


def load_product_name(code: str) -> str | None:
    seed_path = Path("app") / "seed" / "etfs" / f"{code}.json"
    if not seed_path.exists():
        return None
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    master = data.get("master", {})
    return master.get("name")


def fetch_corp_codes(client: OpenDartClient) -> list[CorpCode]:
    payload = client.get_bytes("corpCode.xml", {})
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        xml_name = zf.namelist()[0]
        root = ElementTree.fromstring(zf.read(xml_name))
    rows: list[CorpCode] = []
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip() or None
        rows.append(
            CorpCode(
                corp_code=(item.findtext("corp_code") or "").strip(),
                corp_name=(item.findtext("corp_name") or "").strip(),
                stock_code=stock_code,
                modify_date=(item.findtext("modify_date") or "").strip() or None,
            )
        )
    return rows


def choose_manager_corp(matches: list[CorpCode]) -> CorpCode | None:
    if not matches:
        return None
    preferred = [corp for corp in matches if corp.corp_name == DEFAULT_MANAGER_QUERY]
    return (preferred or matches)[0]


def search_filings(
    client: OpenDartClient,
    *,
    bgn_de: str,
    end_de: str,
    corp_code: str | None = None,
    pblntf_ty: str | None = None,
    page_count: int = 100,
) -> list[dict[str, Any]]:
    if corp_code is None and exceeds_three_months(bgn_de, end_de):
        filings: list[dict[str, Any]] = []
        for window_bgn, window_end in date_windows(bgn_de, end_de, days=90):
            filings.extend(
                search_filings(
                    client,
                    bgn_de=window_bgn,
                    end_de=window_end,
                    corp_code=corp_code,
                    pblntf_ty=pblntf_ty,
                    page_count=page_count,
                )
            )
        return dedupe_filings(filings)

    page_no = 1
    filings: list[dict[str, Any]] = []
    while True:
        data = client.get_json(
            "list.json",
            {
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "pblntf_ty": pblntf_ty,
                "page_no": page_no,
                "page_count": page_count,
            },
        )
        status = str(data.get("status", ""))
        if status != "000":
            if status == "013":
                return filings
            raise OpenDartError(f"OpenDART list.json failed: {status} {data.get('message')}")
        rows = data.get("list") or []
        filings.extend(rows)
        total_page = int(data.get("total_page") or page_no)
        if page_no >= total_page:
            return filings
        page_no += 1


def search_target_fund_filings(
    client: OpenDartClient,
    *,
    product_query: str | None,
    bgn_de: str,
    end_de: str,
    limit: int,
    corp_code: str | None = None,
    page_count: int = 100,
) -> list[dict[str, Any]]:
    """Find the ETF's own fund-disclosure filings, newest window first.

    `corp_code` narrows the `pblntf_ty=G` search to one manager when known — a
    90-day window of *every* manager's fund disclosures can run ~35+ pages
    (thousands of filings), while one manager's is usually a handful. Pass it
    whenever the caller already resolved the manager corp; only fall back to the
    unscoped market-wide search when it isn't known yet.
    """
    if not product_query:
        return []
    matches: list[dict[str, Any]] = []
    windows = list(reversed(date_windows(bgn_de, end_de, days=90)))
    for window_bgn, window_end in windows:
        page_no = 1
        while True:
            data = client.get_json(
                "list.json",
                {
                    "corp_code": corp_code,
                    "bgn_de": window_bgn,
                    "end_de": window_end,
                    "pblntf_ty": "G",
                    "page_no": page_no,
                    "page_count": page_count,
                },
            )
            status = str(data.get("status", ""))
            if status != "000":
                if status == "013":
                    break
                raise OpenDartError(
                    f"OpenDART list.json failed: {status} {data.get('message')}"
                )
            rows = [
                row
                for row in data.get("list") or []
                if "투자설명서" in str(row.get("report_nm", ""))
            ]
            matches.extend(filter_target_filings(rows, product_query))
            total_page = int(data.get("total_page") or page_no)
            if page_no >= total_page:
                break
            page_no += 1
        # Only stop once the *whole* window has been paged through — a match on an
        # earlier page must not short-circuit before a newer one later in the same
        # window is seen, or sort_filings_latest_first below has an incomplete set
        # to sort within this window.
        if len(matches) >= limit:
            return sort_filings_latest_first(dedupe_filings(matches))
    return sort_filings_latest_first(dedupe_filings(matches))


def exceeds_three_months(bgn_de: str, end_de: str) -> bool:
    return parse_yyyymmdd(end_de) - parse_yyyymmdd(bgn_de) > timedelta(days=90)


def date_windows(bgn_de: str, end_de: str, *, days: int) -> list[tuple[str, str]]:
    start = parse_yyyymmdd(bgn_de)
    end = parse_yyyymmdd(end_de)
    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=days), end)
        windows.append((format_yyyymmdd(cursor), format_yyyymmdd(window_end)))
        cursor = window_end + timedelta(days=1)
    return windows


def parse_yyyymmdd(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def format_yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def dedupe_filings(filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for filing in filings:
        rcept_no = str(filing.get("rcept_no", ""))
        if not rcept_no or rcept_no in seen:
            continue
        seen.add(rcept_no)
        unique.append(filing)
    return unique


def filter_target_filings(
    filings: list[dict[str, Any]], product_query: str | None
) -> list[dict[str, Any]]:
    tokens = product_name_tokens(product_query)
    if not tokens:
        return []
    return [
        filing
        for filing in filings
        if all(token in compact(str(filing.get("report_nm", ""))) for token in tokens)
    ]


def sort_filings_latest_first(filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order filings newest-first by (rcept_dt, rcept_no).

    Window-first traversal (see `search_target_fund_filings`) only guarantees the
    *window* is newest-first — it says nothing about the order DART returns filings
    within one window. Two corrections landing in the same 90-day window must still
    be ordered explicitly, or `[:download_limit]` can silently keep the older one.
    """
    return sorted(
        filings,
        key=lambda filing: (str(filing.get("rcept_dt", "")), str(filing.get("rcept_no", ""))),
        reverse=True,
    )


def filing_identity(report_nm: str) -> str:
    """Compact report_nm with leading bracket tags (e.g. `[기재정정]`) stripped.

    Two filings for the *same* fund differ only by such tags and by date/receipt
    number as corrections accumulate. If `filter_target_filings` matches filings
    with different identities, the product_query was too loose to pin down a
    single fund and the result must not be auto-selected.
    """
    return compact(re.sub(r"^(\[[^\]]*\])+", "", report_nm))


def has_ambiguous_target_filings(target_filings: list[dict[str, Any]]) -> bool:
    identities = {filing_identity(str(filing.get("report_nm", ""))) for filing in target_filings}
    return len(identities) > 1


def download_and_inspect_document(
    client: OpenDartClient,
    *,
    filing: dict[str, Any],
    code: str,
    product_name: str | None,
    output_dir: Path,
) -> dict[str, Any]:
    rcept_no = str(filing["rcept_no"])
    payload = client.get_bytes("document.xml", {"rcept_no": rcept_no})
    zip_path = output_dir / f"{rcept_no}.zip"
    zip_path.write_bytes(payload)
    with zipfile.ZipFile(zip_path) as zf:
        inspections = [
            inspect_member(zf, name, code=code, product_name=product_name)
            for name in zf.namelist()
            if not name.endswith("/")
        ]
    return {
        "rceptNo": rcept_no,
        "zipPath": str(zip_path),
        "members": [inspection.__dict__ for inspection in inspections],
        "mentionsCodeOrProduct": any(
            inspection.mentions_code or inspection.mentions_product_name
            for inspection in inspections
        ),
    }


def inspect_web_pdf_downloads(
    *, filing: dict[str, Any], output_dir: Path
) -> dict[str, Any]:
    rcept_no = str(filing["rcept_no"])
    detail_html = fetch_dart_web(
        f"/dsaf001/main.do?{urlencode({'rcpNo': rcept_no})}",
    )
    dcm_no = parse_primary_dcm_no(detail_html, rcept_no)
    options: list[dict[str, str]] = []
    downloads: list[dict[str, Any]] = []
    if dcm_no:
        popup_html = fetch_dart_web(
            f"/pdf/download/main.do?{urlencode({'rcp_no': rcept_no, 'dcm_no': dcm_no})}",
        )
        options = parse_pdf_download_options(popup_html)
        referer = f"{DART_WEB_URL}/pdf/download/main.do?rcp_no={rcept_no}&dcm_no={dcm_no}"
        downloads = [
            download_pdf_option(option, output_dir=output_dir, referer=referer)
            for option in options
            if is_prospectus_file_download(option)
        ]
    return {
        "rceptNo": rcept_no,
        "dcmNo": dcm_no,
        "options": options,
        "downloads": downloads,
    }


def safe_inspect_web_pdf_downloads(
    *, filing: dict[str, Any], output_dir: Path
) -> dict[str, Any]:
    try:
        return inspect_web_pdf_downloads(filing=filing, output_dir=output_dir)
    except (OSError, URLError, TimeoutError) as exc:
        return {
            "rceptNo": str(filing["rcept_no"]),
            "dcmNo": None,
            "options": [],
            "downloads": [],
            "error": str(exc),
        }


def fetch_dart_web(path: str, *, timeout: int = 10) -> str:
    url = f"{DART_WEB_URL}{path}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return response.read().decode("utf-8", errors="ignore")


def parse_primary_dcm_no(html: str, rcept_no: str) -> str | None:
    match = re.search(
        rf"openPdfDownload\('{re.escape(rcept_no)}',\s*'(?P<dcm_no>\d+)'\)",
        html,
    )
    if match:
        return match.group("dcm_no")
    match = re.search(
        rf"rcpNo']\s*=\s*\"{re.escape(rcept_no)}\";.*?dcmNo']\s*=\s*\"(?P<dcm_no>\d+)\"",
        html,
        re.DOTALL,
    )
    return match.group("dcm_no") if match else None


def parse_pdf_download_options(html: str) -> list[dict[str, str]]:
    rows = re.findall(r"<tr>(.*?)</tr>", html, flags=re.DOTALL | re.IGNORECASE)
    options: list[dict[str, str]] = []
    for row in rows:
        href_match = re.search(r'href="(?P<href>/pdf/download/[^"]+)"', row)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.DOTALL | re.IGNORECASE)
        if not href_match or not cells:
            continue
        filename = re.sub(r"<[^>]+>", "", cells[0])
        filename = re.sub(r"\s+", " ", unescape(filename)).strip()
        options.append({"filename": filename, "href": unescape(href_match.group("href"))})
    return options


def is_prospectus_file_download(option: dict[str, str]) -> bool:
    return "투자설명서" in option["filename"] and option["href"].startswith(
        "/pdf/download/file.do"
    )


def download_pdf_option(
    option: dict[str, str], *, output_dir: Path, referer: str
) -> dict[str, Any]:
    url = f"{DART_WEB_URL}{option['href']}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
    with urlopen(request, timeout=30, context=ssl_context()) as response:
        payload = response.read()
        content_type = response.headers.get("content-type")
    safe_name = re.sub(r"[^0-9A-Za-z_.-]+", "_", option["filename"])
    path = output_dir / safe_name
    path.write_bytes(payload)
    is_pdf, content_type_ok = validate_pdf_payload(payload, content_type)
    return {
        "filename": option["filename"],
        "path": str(path),
        "contentType": content_type,
        "size": len(payload),
        "isPdf": is_pdf,
        "contentTypeOk": content_type_ok,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def validate_pdf_payload(payload: bytes, content_type: str | None) -> tuple[bool, bool]:
    """Return (magic-byte check, content-type check) for a downloaded file.do body.

    Both checks exist because a malformed request (e.g. a mangled `fl_nm`) doesn't
    error — DART silently returns a small `text/html` error page instead. Checking
    only the magic byte would already catch that, but keeping the two signals
    separate makes it possible to tell "not a PDF" apart from "server disagrees
    with itself" in a spike report.
    """
    is_pdf = payload.startswith(b"%PDF")
    content_type_ok = bool(content_type) and "pdf" in content_type.lower()
    return is_pdf, content_type_ok


def inspect_member(
    zf: zipfile.ZipFile, filename: str, *, code: str, product_name: str | None
) -> ZipMemberInspection:
    payload = zf.read(filename)
    kind = detect_member_kind(filename, payload)
    text = decode_text(payload) if kind in {"xml", "html", "text"} else ""
    product_tokens = product_name_tokens(product_name)
    compact_text = compact(text)
    return ZipMemberInspection(
        filename=filename,
        size=len(payload),
        kind=kind,
        mentions_code=code in text,
        mentions_product_name=bool(
            product_tokens and all(token in compact_text for token in product_tokens)
        ),
    )


def detect_member_kind(filename: str, payload: bytes) -> str:
    lower = filename.lower()
    prefix = payload[:100].lstrip()
    if prefix.startswith(b"%PDF") or lower.endswith(".pdf"):
        return "pdf"
    if prefix.startswith(b"<") or lower.endswith(".xml"):
        return "xml"
    if lower.endswith((".html", ".htm")):
        return "html"
    if lower.endswith(".txt"):
        return "text"
    return "binary"


def decode_text(payload: bytes) -> str:
    for encoding in ("utf-8", "euc-kr", "cp949"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="ignore")


def product_name_tokens(product_name: str | None) -> list[str]:
    if not product_name:
        return []
    normalized = compact(product_name)
    return [normalized] if normalized else []


def compact(value: str) -> str:
    return re.sub(r"[\s·ㆍ\-_]+", "", value)


def conclude_mapping(
    stock_code_matches: list[CorpCode],
    downloaded: list[dict[str, Any]],
    web_pdfs: list[dict[str, Any]] | None = None,
    *,
    ambiguous: bool = False,
) -> str:
    web_pdfs = web_pdfs or []
    if ambiguous:
        return "ambiguous_document"
    if any(
        download.get("isPdf")
        for item in web_pdfs
        for download in item.get("downloads", [])
    ):
        return "web_pdf_downloaded"
    if stock_code_matches:
        return "stock_code_match_found"
    if any(item["mentionsCodeOrProduct"] for item in downloaded):
        return "manager_filing_mentions_target"
    if downloaded:
        return "manager_filing_downloaded_but_target_not_confirmed"
    return "no_prospectus_filing_downloaded"


def write_spike_report(result: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    json_path = output_dir / "spike_result.json"
    md_path = output_dir / "spike_result.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# OpenDART Gate D Spike — {result['code']}",
        "",
        f"- productName: {result.get('productName')}",
        f"- productQuery: {result.get('productQuery')}",
        f"- selectedManager: {(result.get('selectedManager') or {}).get('corp_name')}",
        f"- stockCodeMatches: {len(result.get('stockCodeMatches') or [])}",
        f"- fundDisclosureCount: {result.get('fundDisclosureCount')}",
        f"- filingCount: {result.get('filingCount')}",
        f"- prospectusFilingCount: {result.get('prospectusFilingCount')}",
        f"- targetFilingCount: {result.get('targetFilingCount')}",
        f"- ambiguous: {result.get('ambiguous')}",
        f"- mappingConclusion: {result.get('mappingConclusion')}",
        "",
        "## target report_nm",
    ]
    lines.extend(f"- {name}" for name in result.get("targetReportNames", []))
    lines.extend([
        "",
        "## report_nm",
    ])
    lines.extend(f"- {name}" for name in result.get("sampleReportNames", []))
    lines.extend(["", "## downloaded"])
    for item in result.get("downloaded", []):
        lines.append(f"- {item['rceptNo']}: mentionsTarget={item['mentionsCodeOrProduct']}")
        for member in item["members"]:
            lines.append(
                f"  - {member['filename']} ({member['kind']}, {member['size']} bytes, "
                f"code={member['mentions_code']}, product={member['mentions_product_name']})"
            )
    lines.extend(["", "## web pdf downloads"])
    for item in result.get("webPdfs", []):
        lines.append(f"- {item['rceptNo']}: dcmNo={item['dcmNo']}")
        for option in item["options"]:
            lines.append(f"  - option: {option['filename']} -> {option['href']}")
        for download in item["downloads"]:
            lines.append(
                f"  - downloaded: {download['filename']} "
                f"({download['contentType']}, {download['size']} bytes, "
                f"pdf={download['isPdf']}, contentTypeOk={download.get('contentTypeOk')}, "
                f"sha256={download.get('sha256')})"
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
