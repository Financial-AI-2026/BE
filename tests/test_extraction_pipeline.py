import json
import unicodedata
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from extraction.fetch.dart import (
    DOMESTIC_DART_PRODUCT_QUERIES,
    choose_manager_corp,
    compact,
    conclude_mapping,
    date_windows,
    detect_member_kind,
    exceeds_three_months,
    fetch_corp_codes,
    filing_identity,
    filter_target_filings,
    has_ambiguous_target_filings,
    inspect_member,
    parse_pdf_download_options,
    parse_primary_dcm_no,
    product_name_tokens,
    search_target_fund_filings,
    sort_filings_latest_first,
    validate_pdf_payload,
    write_spike_report,
)
from extraction.parsers.base import PageText
from extraction.parsers.kr_prospectus import KrProspectusParser
from extraction.reporting import write_markdown_report
from extraction.schemas import SourceMetadata
from extraction.scoring import (
    score_outputs,
    summarize_reproducibility,
    write_reproducibility_report,
    write_score_report,
)
from extraction.service import build_c2_wide_context, extract_profile
from extraction.validation import ExtractionValidationError, validate_payload


class MockLlmClient:
    model = "mock-model"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def extract(self, prompt: str, context: str) -> dict[str, Any]:
        assert "근거" in prompt
        assert "제2부 9" in context
        return self.payload


@pytest.fixture()
def sections() -> list:
    data = json.loads(Path("tests/fixtures/extraction/kr_pages.json").read_text(encoding="utf-8"))
    pages = [PageText(**item) for item in data]
    return KrProspectusParser().split_sections(pages)


def test_kr_parser_splits_sections_from_toc_fixture(sections: list) -> None:
    locations = [section.location for section in sections]

    assert "제2부 9 (집합투자기구의 투자전략,위험관리 및 수익구조)" in locations
    assert "제2부 14 (이익 배분 및 과세에 관한 사항)" in locations
    assert any("총보수" in section.text for section in sections)


def test_kr_parser_reads_existing_ai_finance_test_pdf() -> None:
    pdf = next(
        path
        for path in Path("ai-finance-test/docs/prospectus").glob("*.pdf")
        if "S&P500" in unicodedata.normalize("NFC", path.name)
        and "레버리지" in unicodedata.normalize("NFC", path.name)
    )
    parser = KrProspectusParser()

    pages, report = parser.extract_pages(pdf, "PDFSMOKE")
    sections = parser.split_sections(pages)
    locations = [section.location for section in sections]

    assert report.has_text_layer is True
    assert report.page_count > 50
    assert "제2부 8 (집합투자기구의 투자대상)" in locations
    assert "제2부 9 (집합투자기구의 투자전략,위험관리 및 수익구조)" in locations
    assert "제2부 13 (보수 및 수수료에 관한 사항)" in locations
    assert "제2부 14 (이익 배분 및 과세에 관한 사항)" in locations


def test_extract_profile_passes_with_mock_response_and_writes_report(
    sections: list, tmp_path: Path
) -> None:
    result = extract_profile(
        "418660",
        sections=sections,
        llm_client=MockLlmClient(valid_payload()),
        source=SourceMetadata(filename="fixture.pdf", sha256="abc"),
        write_output=False,
    )
    report_path = write_markdown_report(result, output_dir=tmp_path)

    assert result.validationPassed is True
    assert result.issues == []
    assert report_path.endswith("418660.md")


def test_schema_failure_fails_closed(sections: list) -> None:
    with pytest.raises(ExtractionValidationError) as excinfo:
        validate_payload(
            code="418660",
            raw_payload={"name": "broken"},
            sections=sections,
            source=None,
            model="mock",
            prompt_version="test",
        )

    assert excinfo.value.issues[0].code == "SCHEMA_INVALID"


def test_missing_evidence_fails_closed(sections: list) -> None:
    payload = valid_payload()
    payload["evidence"] = [item for item in payload["evidence"] if item["field"] != "fxHedge"]

    result = extract_profile(
        "418660", sections=sections, llm_client=MockLlmClient(payload), write_output=False
    )

    assert result.validationPassed is False
    assert any(
        issue.code == "EVIDENCE_MISSING" and issue.field == "fxHedge"
        for issue in result.issues
    )


def test_quote_mismatch_fails_closed(sections: list) -> None:
    payload = valid_payload()
    payload["evidence"][0]["quote"] = "원문에 없는 문장입니다."

    result = extract_profile(
        "418660", sections=sections, llm_client=MockLlmClient(payload), write_output=False
    )

    assert result.validationPassed is False
    assert any(issue.code == "QUOTE_NOT_FOUND" and issue.field == "name" for issue in result.issues)


def test_name_correction_records_conflict_and_adopts_name_rule(sections: list) -> None:
    payload = valid_payload()
    payload["replication"] = "실물"
    payload["strategy"] = "지수추종"

    result = extract_profile(
        "418660", sections=sections, llm_client=MockLlmClient(payload), write_output=False
    )

    assert result.profile.replication == "합성"
    assert result.profile.strategy == "레버리지"
    assert result.validationPassed is True
    assert [issue.code for issue in result.issues] == [
        "NAME_CORRECTION_CONFLICT",
        "NAME_CORRECTION_CONFLICT",
    ]


def test_master_code_override_is_nonfatal(sections: list) -> None:
    payload = valid_payload()
    payload["code"] = "DQ357"

    result = extract_profile(
        "418660", sections=sections, llm_client=MockLlmClient(payload), write_output=False
    )

    assert result.profile.code == "418660"
    assert result.validationPassed is True
    assert [issue.code for issue in result.issues] == ["MASTER_CODE_OVERRIDDEN"]


def test_base_index_normalization_is_nonfatal(sections: list) -> None:
    payload = valid_payload()
    payload["baseIndex"] = "NASDAQ-100 지수(원화환산)"

    result = extract_profile(
        "418660", sections=sections, llm_client=MockLlmClient(payload), write_output=False
    )

    assert result.profile.baseIndex == "NASDAQ-100"
    assert result.validationPassed is True
    assert [issue.code for issue in result.issues] == ["BASE_INDEX_NORMALIZED"]


def test_strategy_evidence_can_be_derived_from_leverage_evidence(sections: list) -> None:
    payload = valid_payload()
    payload["evidence"] = [item for item in payload["evidence"] if item["field"] != "strategy"]

    result = extract_profile(
        "418660", sections=sections, llm_client=MockLlmClient(payload), write_output=False
    )

    assert result.validationPassed is True
    assert any(item.field == "strategy" for item in result.profile.evidence)
    assert [issue.code for issue in result.issues] == ["STRATEGY_EVIDENCE_DERIVED"]


def test_c2_wide_context_uses_validated_section_set(sections: list) -> None:
    context = build_c2_wide_context(sections)

    assert "제2부 8" in context
    assert "제2부 9" in context
    assert "제2부 14" in context


def test_score_outputs_compares_profile_fields_and_master_sanity(
    sections: list, tmp_path: Path
) -> None:
    result = extract_profile(
        "418660", sections=sections, llm_client=MockLlmClient(valid_payload()), write_output=False
    )
    out_dir = tmp_path / "out"
    seed_dir = tmp_path / "seed"
    out_dir.mkdir()
    seed_dir.mkdir()
    (out_dir / "418660.json").write_text(result.model_dump_json(), encoding="utf-8")
    (seed_dir / "418660.json").write_text(
        json.dumps(seed_payload(), ensure_ascii=False), encoding="utf-8"
    )

    report = score_outputs(codes=("418660",), out_dir=out_dir, seed_dir=seed_dir)
    _, md_path = write_score_report(report, output_dir=tmp_path / "reports")

    assert report.passed == 7
    assert report.total == 7
    assert md_path.exists()


def test_reproducibility_report_summarizes_modal_values(sections: list, tmp_path: Path) -> None:
    result = extract_profile(
        "418660", sections=sections, llm_client=MockLlmClient(valid_payload()), write_output=False
    )

    rows = summarize_reproducibility([result, result])
    _, md_path = write_reproducibility_report("418660", rows, output_dir=tmp_path)

    assert all(row.rate == 1.0 for row in rows)
    assert md_path.exists()


def test_dart_corp_code_zip_parses_stock_and_manager_entries() -> None:
    class FakeClient:
        def get_bytes(self, endpoint: str, params: dict[str, Any]) -> bytes:
            assert endpoint == "corpCode.xml"
            assert params == {}
            return zipped(
                "CORPCODE.xml",
                """
                <result>
                  <list>
                    <corp_code>001</corp_code>
                    <corp_name>미래에셋자산운용</corp_name>
                    <stock_code></stock_code>
                    <modify_date>20260101</modify_date>
                  </list>
                  <list>
                    <corp_code>002</corp_code>
                    <corp_name>샘플 ETF</corp_name>
                    <stock_code>418660</stock_code>
                    <modify_date>20260102</modify_date>
                  </list>
                </result>
                """.encode(),
            )

    rows = fetch_corp_codes(FakeClient())  # type: ignore[arg-type]
    manager = choose_manager_corp([row for row in rows if "미래에셋" in row.corp_name])

    assert rows[1].stock_code == "418660"
    assert manager is not None
    assert manager.corp_code == "001"


def test_dart_document_zip_inspection_detects_xml_and_target_mentions(tmp_path: Path) -> None:
    payload = zipped(
        "document.xml",
        (
            "<DOCUMENT>TIGER 미국나스닥100레버리지(합성) 투자설명서 "
            "종목코드 418660</DOCUMENT>"
        ).encode(),
    )
    zip_path = tmp_path / "document.zip"
    zip_path.write_bytes(payload)

    with zipfile.ZipFile(zip_path) as zf:
        inspection = inspect_member(
            zf,
            "document.xml",
            code="418660",
            product_name="TIGER 미국나스닥100레버리지(합성)",
        )

    assert detect_member_kind("document.xml", b"<DOCUMENT/>") == "xml"
    assert detect_member_kind("file.pdf", b"%PDF-1.7") == "pdf"
    assert product_name_tokens("TIGER 미국나스닥100레버리지(합성)") == [
        "TIGER미국나스닥100레버리지(합성)"
    ]
    assert inspection.kind == "xml"
    assert inspection.mentions_code is True
    assert inspection.mentions_product_name is True


def test_dart_spike_report_records_mapping_conclusion(tmp_path: Path) -> None:
    result = {
        "code": "418660",
        "productName": "TIGER 미국나스닥100레버리지(합성)",
        "selectedManager": {"corp_name": "미래에셋자산운용"},
        "stockCodeMatches": [],
        "filingCount": 1,
        "prospectusFilingCount": 1,
        "sampleReportNames": ["투자설명서"],
        "downloaded": [
            {
                "rceptNo": "20260101000001",
                "mentionsCodeOrProduct": True,
                "members": [
                    {
                        "filename": "document.xml",
                        "kind": "xml",
                        "size": 10,
                        "mentions_code": True,
                        "mentions_product_name": True,
                    }
                ],
            }
        ],
        "webPdfs": [
            {
                "rceptNo": "20260101000001",
                "dcmNo": "123",
                "options": [],
                "downloads": [
                    {
                        "filename": "투자설명서.pdf",
                        "contentType": "application/pdf",
                        "size": 100,
                        "isPdf": True,
                    }
                ],
            }
        ],
        "mappingConclusion": "manager_filing_mentions_target",
    }

    json_path, md_path = write_spike_report(result, tmp_path)

    assert json_path.exists()
    assert "manager_filing_mentions_target" in md_path.read_text(encoding="utf-8")
    assert conclude_mapping([], result["downloaded"], result["webPdfs"]) == "web_pdf_downloaded"


def test_dart_target_filings_prefer_product_name_tokens() -> None:
    filings = [
        {"report_nm": "[기재정정]투자설명서(집합투자증권)(미래에셋친디아인프라섹터...)"},
        {
            "report_nm": (
                "[기재정정]투자설명서(집합투자증권)"
                "(미래에셋TIGER미국나스닥100레버리지증권상장지수투자신탁"
                "(주식혼합-파생형)(합성))"
            )
        },
    ]

    matches = filter_target_filings(
        filings,
        DOMESTIC_DART_PRODUCT_QUERIES["418660"],
    )

    assert len(matches) == 1
    assert "미국나스닥100레버리지" in matches[0]["report_nm"]


def test_dart_target_filings_use_compact_long_product_name_to_reduce_overmatch() -> None:
    filings = [
        {
            "report_nm": (
                "[기재정정]투자설명서(집합투자증권)"
                "(미래에셋TIGER미국나스닥100커버드콜증권상장지수투자신탁"
                "(주식-파생형)(합성))"
            )
        },
        {
            "report_nm": (
                "[기재정정]투자설명서(집합투자증권)"
                "(미래에셋TIGER미국나스닥100증권상장지수투자신탁(주식))"
            )
        },
    ]

    matches = filter_target_filings(filings, DOMESTIC_DART_PRODUCT_QUERIES["133690"])

    assert compact("TIGER 미국나스닥100증권상장지수투자신탁") in compact(
        matches[0]["report_nm"]
    )
    assert len(matches) == 1


def test_dart_133690_query_excludes_the_hedged_derivative_variant() -> None:
    # Live regression (2026-09-01): the unqualified query also substring-matched a
    # different, currency-hedged fund whose report_nm ends in "(주식파생형)(H))",
    # which `has_ambiguous_target_filings` correctly flagged instead of silently
    # picking one. The trailing "(주식)" in the query is what excludes it.
    filings = [
        {
            "report_nm": (
                "[기재정정]투자설명서(집합투자증권)"
                "(미래에셋TIGER미국나스닥100증권상장지수투자신탁(주식))"
            )
        },
        {
            "report_nm": (
                "[기재정정]투자설명서(집합투자증권)"
                "(미래에셋TIGER미국나스닥100증권상장지수투자신탁(주식파생형)(H))"
            )
        },
    ]

    matches = filter_target_filings(filings, DOMESTIC_DART_PRODUCT_QUERIES["133690"])

    assert len(matches) == 1
    assert has_ambiguous_target_filings(matches) is False
    assert matches[0]["report_nm"].endswith("(주식))")


def test_dart_web_pdf_download_options_are_parsed() -> None:
    detail_html = """
    <button onclick="openPdfDownload('20260515000037', '11380928');">다운로드</button>
    """
    popup_html = """
    <tr>
      <td class="tL">[미래에셋자산운용][정정]투자설명서(집합투자증권)(2026.05.15).pdf</td>
      <td>
        <a class="btnFile"
           href="/pdf/download/pdf.do?rcp_no=20260515000037&amp;dcm_no=11380928"></a>
      </td>
    </tr>
    <tr>
      <td class="tL">투자설명서_미래에셋tiger미국나스닥100레버리지.pdf</td>
      <td>
        <a class="btnFile"
           href="/pdf/download/file.do?rcp_no=20260515000037&amp;dcm_id=10611&amp;dcm_seq=343&amp;fl_nm=file.pdf"></a>
      </td>
    </tr>
    """

    options = parse_pdf_download_options(popup_html)

    assert parse_primary_dcm_no(detail_html, "20260515000037") == "11380928"
    assert len(options) == 2
    assert options[1]["filename"].startswith("투자설명서_미래에셋")
    assert options[1]["href"].startswith("/pdf/download/file.do")


def test_dart_market_wide_search_uses_three_month_windows() -> None:
    windows = date_windows("20240101", "20240715", days=90)

    assert exceeds_three_months("20240101", "20240715") is True
    assert windows == [
        ("20240101", "20240331"),
        ("20240401", "20240630"),
        ("20240701", "20240715"),
    ]


def test_dart_sort_filings_latest_first_orders_by_date_then_receipt_no() -> None:
    filings = [
        {"rcept_no": "20260211000180", "rcept_dt": "20260211"},
        {"rcept_no": "20260528000050", "rcept_dt": "20260528"},
        {"rcept_no": "20260528000190", "rcept_dt": "20260528"},
    ]

    ordered = sort_filings_latest_first(filings)

    assert [f["rcept_no"] for f in ordered] == [
        "20260528000190",
        "20260528000050",
        "20260211000180",
    ]


def test_dart_search_target_fund_filings_sorts_within_a_single_window() -> None:
    # Regression for the 448290 stale-selection incident: a naive "first match in
    # scan order, return immediately" pick can keep an older filing when DART lists
    # two corrections that land in the *same* 90-day window out of date order.
    # `search_target_fund_filings` must finish paging the window and sort explicitly
    # before applying `limit`, not trust window-scan order alone.
    report_nm = DOMESTIC_DART_PRODUCT_QUERIES["448290"]
    full_report_nm = f"[기재정정]투자설명서(집합투자증권)(미래에셋{report_nm})"

    class FakeClient:
        def get_json(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
            assert endpoint == "list.json"
            if params["bgn_de"] == "20260702":  # newest window: nothing filed yet
                rows: list[dict[str, Any]] = []
            elif params["bgn_de"] == "20260402":  # window with two same-window corrections
                rows = [
                    # API returns the older correction first — this is the exact
                    # ordering that broke without an explicit sort.
                    {
                        "rcept_no": "20260415000100",
                        "rcept_dt": "20260415",
                        "report_nm": full_report_nm,
                    },
                    {
                        "rcept_no": "20260620000200",
                        "rcept_dt": "20260620",
                        "report_nm": full_report_nm,
                    },
                ]
            else:
                rows = []
            return {"status": "000", "list": rows, "total_page": 1}

    matches = search_target_fund_filings(
        FakeClient(),  # type: ignore[arg-type]
        product_query=DOMESTIC_DART_PRODUCT_QUERIES["448290"],
        bgn_de="20260101",
        end_de="20260901",
        limit=1,
    )

    assert [m["rcept_no"] for m in matches] == ["20260620000200", "20260415000100"]


def test_dart_filing_identity_ignores_correction_tags_but_not_fund_name() -> None:
    corrected = (
        "[기재정정]투자설명서(집합투자증권)(미래에셋TIGER미국S&P500증권상장지수투자신탁(주식-파생형)(H))"
    )
    original = (
        "투자설명서(집합투자증권)(미래에셋TIGER미국S&P500증권상장지수투자신탁(주식-파생형)(H))"
    )
    different_fund = "[기재정정]투자설명서(집합투자증권)(미래에셋TIGER200증권상장지수투자신탁)"

    assert filing_identity(corrected) == filing_identity(original)
    assert filing_identity(corrected) != filing_identity(different_fund)


def test_dart_ambiguous_target_filings_block_auto_selection() -> None:
    same_fund = [
        {"report_nm": "[기재정정]투자설명서(집합투자증권)(미래에셋TIGER200증권상장지수투자신탁)"},
        {"report_nm": "투자설명서(집합투자증권)(미래에셋TIGER200증권상장지수투자신탁)"},
    ]
    two_funds = same_fund + [
        {
            "report_nm": (
                "[기재정정]투자설명서(집합투자증권)(미래에셋TIGER200선물레버리지증권상장지수투자신탁)"
            )
        }
    ]

    assert has_ambiguous_target_filings(same_fund) is False
    assert has_ambiguous_target_filings(two_funds) is True
    assert conclude_mapping([], [], [], ambiguous=True) == "ambiguous_document"


def test_dart_validate_pdf_payload_flags_html_error_page_from_bad_params() -> None:
    # This is what `file.do` actually returns for a mangled `fl_nm`: a 200 response
    # with a small HTML error page, not an exception — so the check has to be on
    # payload content, not on the request succeeding.
    is_pdf, content_type_ok = validate_pdf_payload(
        b"<html>error</html>", "text/html;charset=UTF-8"
    )
    assert is_pdf is False
    assert content_type_ok is False

    is_pdf, content_type_ok = validate_pdf_payload(b"%PDF-1.7 ...", "application/pdf")
    assert is_pdf is True
    assert content_type_ok is True


def zipped(filename: str, payload: bytes) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(filename, payload)
    return buf.getvalue()


def valid_payload() -> dict[str, Any]:
    evidence = [
        ("name", "TIGER 미국나스닥100레버리지(합성)"),
        ("baseIndex", "NASDAQ-100 지수를 기초지수로 합니다."),
        ("replication", "이 투자신탁은 합성복제 방식으로 운용됩니다."),
        (
            "leverage",
            "1좌당 순자산가치의 일간변동률을 기초지수 일간변동률의 양의 2배수로 연동합니다.",
        ),
        (
            "strategy",
            "1좌당 순자산가치의 일간변동률을 기초지수 일간변동률의 양의 2배수로 연동합니다.",
        ),
        ("distribution", "이익분배금은 회계기간 종료 후 연 1회 지급합니다."),
        ("totalExpense", "총보수는 연 0.25%입니다."),
        ("fxHedge", "환율 변동위험이 있습니다."),
    ]
    return {
        "name": "TIGER 미국나스닥100레버리지(합성)",
        "code": "418660",
        "isin": None,
        "market": "KR",
        "baseIndex": "NASDAQ-100",
        "replication": "합성",
        "leverage": 2.0,
        "dailyRebalancing": True,
        "isActive": False,
        "strategy": "레버리지",
        "distribution": "연분배",
        "distributionYield": 0.8,
        "targetYear": None,
        "totalExpense": 0.25,
        "fxHedge": "미헤지",
        "counterpartyRisk": True,
        "counterparty": None,
        "mainAssets": ["미국 주식관련 장외파생상품"],
        "isComplexProduct": True,
        "evidence": [
            {
                "field": field,
                "quote": quote,
                "location": "제2부 9",
                "sourceType": "KR_PROSPECTUS",
                "translated": False,
            }
            for field, quote in evidence
        ],
    }


def seed_payload() -> dict[str, Any]:
    return {
        "master": {
            "code": "418660",
            "name": "TIGER 미국나스닥100레버리지(합성)",
            "market": "KR",
        },
        "profile": {
            "base_index": "NASDAQ-100",
            "replication": "합성",
            "leverage": 2.0,
            "strategy": "레버리지",
            "distribution": "연분배",
            "total_expense": 0.25,
            "fx_hedge": "미헤지",
        },
    }
