from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.enums import Distribution, FxHedge, Market, Replication, Strategy
from extraction.fetch.sec import SecFiling
from extraction.parsers.base import Section
from extraction.parsers.us_summary import UsSummaryParser
from extraction.schemas import EvidenceItem, ProductProfile
from extraction.service import build_us_context, extract_us_profile
from extraction.validation import (
    _validate_quotes,
    apply_us_fx_hedge_default,
    enforce_counterparty_risk_default,
    enforce_daily_rebalancing_default,
    enforce_issuer_disclosure_field_scope,
    enforce_leverage_default,
    enforce_leveraged_synthetic_replication,
    repair_or_drop_unsupported_evidence,
)

SUMMARY_PROSPECTUS_HTML = """
<html><body>
<font style="font-weight:700">INVESTMENT OBJECTIVE</font>
<p>The Fund seeks to provide investment results that correspond to the Example Index.</p>
<font style="font-weight:700">FEES AND EXPENSES</font>
<p>Total Annual Fund Operating Expenses 0.35%</p>
</body></html>
"""


def _profile(**overrides: Any) -> ProductProfile:
    defaults: dict[str, Any] = dict(
        name="Example Covered Call ETF",
        code="ABCD",
        isin=None,
        market=Market.US,
        baseIndex="Example Index",
        replication=Replication.PHYSICAL,
        leverage=0,
        dailyRebalancing=None,
        isActive=None,
        strategy=Strategy.COVERED_CALL,
        distribution=Distribution.MONTHLY,
        distributionYield=None,
        targetYear=None,
        totalExpense=0.35,
        fxHedge=FxHedge.NOT_APPLICABLE,
        counterpartyRisk=None,
        counterparty=None,
        mainAssets=[],
        isComplexProduct=None,
        evidence=[
            EvidenceItem(
                field="strategy",
                quote="옵션을 매도합니다",
                location="Principal Investment Strategies",
                sourceType="US_SUMMARY_PROSPECTUS",
                translated=True,
            )
        ],
    )
    defaults.update(overrides)
    return ProductProfile(**defaults)


def test_sec_filing_builds_archives_document_url() -> None:
    filing = SecFiling(
        ticker="QYLD",
        cik="1432353",
        accession_no="0001432353-26-000239",
        filename="a497knasdaq100coveredcall.htm",
        file_date="2026-02-27",
        display_name="Global X Funds",
    )

    assert filing.document_url == (
        "https://www.sec.gov/Archives/edgar/data/1432353/000143235326000239/"
        "a497knasdaq100coveredcall.htm"
    )


def test_us_summary_parser_extracts_full_text_as_a_single_section(tmp_path: Path) -> None:
    html_path = tmp_path / "QYLD.htm"
    html_path.write_text(SUMMARY_PROSPECTUS_HTML, encoding="utf-8")
    parser = UsSummaryParser()

    pages, report = parser.extract_pages(html_path, "QYLD")
    sections = parser.split_sections(pages)

    assert report.has_text_layer is False  # fixture text is short, well under the threshold
    assert len(sections) == 1
    assert "INVESTMENT OBJECTIVE" in sections[0].text
    assert "Total Annual Fund Operating Expenses 0.35%" in sections[0].text
    assert build_us_context(sections) == sections[0].text


def test_enforce_leverage_default_forces_one_for_non_leveraged_strategy() -> None:
    profile = _profile(strategy=Strategy.INDEX, leverage=0)

    issues = enforce_leverage_default(profile)

    assert profile.leverage == 1.0
    assert [issue.code for issue in issues] == ["LEVERAGE_FORCED_TO_ONE"]


def test_enforce_leverage_default_leaves_leveraged_strategy_alone() -> None:
    profile = _profile(strategy=Strategy.LEVERAGE, leverage=3.0)

    issues = enforce_leverage_default(profile)

    assert profile.leverage == 3.0
    assert issues == []


def test_enforce_leveraged_synthetic_replication_forces_synthetic() -> None:
    # Regression: confirmed 10/10 across two live TQQQ reproducibility runs that
    # the LLM reads "Equity Securities" language as physical replication for a
    # 3x leveraged fund, even with a schema description warning against it.
    profile = _profile(
        strategy=Strategy.LEVERAGE,
        leverage=3.0,
        replication=Replication.PHYSICAL,
        evidence=[
            EvidenceItem(
                field="mainAssets",
                quote="the Fund invests in swap agreements and futures contracts",
                location="Principal Investment Strategies",
                sourceType="US_SUMMARY_PROSPECTUS",
                translated=False,
            )
        ],
    )

    issues = enforce_leveraged_synthetic_replication(profile)

    assert profile.replication == Replication.SYNTHETIC
    assert [issue.code for issue in issues] == ["REPLICATION_FORCED_TO_SYNTHETIC"]
    replication_evidence = [item for item in profile.evidence if item.field == "replication"]
    assert len(replication_evidence) == 1
    assert "swap" in replication_evidence[0].quote.lower()


def test_enforce_leveraged_synthetic_replication_falls_back_to_rule_based_evidence() -> None:
    profile = _profile(
        strategy=Strategy.INVERSE,
        leverage=-1.0,
        replication=Replication.PHYSICAL,
        evidence=[],
    )

    issues = enforce_leveraged_synthetic_replication(profile)

    assert profile.replication == Replication.SYNTHETIC
    assert [issue.code for issue in issues] == ["REPLICATION_FORCED_TO_SYNTHETIC"]
    replication_evidence = [item for item in profile.evidence if item.field == "replication"]
    assert replication_evidence[0].location == "규칙 기반 보정 (원문에 직접 서술 없음)"


def test_enforce_leveraged_synthetic_replication_is_a_noop_for_non_leveraged_strategy() -> None:
    profile = _profile(strategy=Strategy.INDEX, replication=Replication.PHYSICAL)

    issues = enforce_leveraged_synthetic_replication(profile)

    assert profile.replication == Replication.PHYSICAL
    assert issues == []


def test_apply_us_fx_hedge_default_corrects_not_applicable_with_labeled_evidence() -> None:
    profile = _profile(fxHedge=FxHedge.NOT_APPLICABLE)

    issues = apply_us_fx_hedge_default(profile)

    assert profile.fxHedge == FxHedge.UNHEDGED
    assert [issue.code for issue in issues] == ["FX_HEDGE_DERIVED"]
    fx_evidence = [item for item in profile.evidence if item.field == "fxHedge"]
    assert len(fx_evidence) == 1
    assert fx_evidence[0].location == "규칙 기반 보정 (원문에 직접 서술 없음)"


def test_apply_us_fx_hedge_default_respects_explicit_hedge_disclosure() -> None:
    profile = _profile(
        fxHedge=FxHedge.NOT_APPLICABLE,
        evidence=[
            EvidenceItem(
                field="fxHedge",
                quote="이 펀드는 currency hedge 전략을 사용합니다",
                location="Principal Investment Strategies",
                sourceType="US_SUMMARY_PROSPECTUS",
                translated=True,
            )
        ],
    )

    issues = apply_us_fx_hedge_default(profile)

    assert profile.fxHedge == FxHedge.NOT_APPLICABLE  # left as the LLM found it
    assert issues == []


def test_enforce_daily_rebalancing_default_fills_null_for_leveraged_strategy() -> None:
    profile = _profile(strategy=Strategy.LEVERAGE, dailyRebalancing=None)

    issues = enforce_daily_rebalancing_default(profile)

    assert profile.dailyRebalancing is True
    assert [issue.code for issue in issues] == ["DAILY_REBALANCING_DERIVED"]


def test_enforce_daily_rebalancing_default_fills_null_false_for_non_leveraged_strategy() -> None:
    profile = _profile(strategy=Strategy.INDEX, dailyRebalancing=None)

    issues = enforce_daily_rebalancing_default(profile)

    assert profile.dailyRebalancing is False
    assert [issue.code for issue in issues] == ["DAILY_REBALANCING_DERIVED"]


def test_enforce_daily_rebalancing_default_is_a_noop_when_already_correct() -> None:
    profile = _profile(strategy=Strategy.LEVERAGE, dailyRebalancing=True)

    issues = enforce_daily_rebalancing_default(profile)

    assert profile.dailyRebalancing is True
    assert issues == []


def test_enforce_counterparty_risk_default_corrects_false_positive_on_physical_fund() -> None:
    # Regression for the bug found 2026-09-02: the LLM read generic KRX
    # boilerplate ("what a synthetic ETF's counterparty must meet, if it uses
    # one") as if it described this specific physically-replicated fund.
    profile = _profile(replication=Replication.PHYSICAL, counterpartyRisk=True)

    issues = enforce_counterparty_risk_default(profile)

    assert profile.counterpartyRisk is False
    assert [issue.code for issue in issues] == ["COUNTERPARTY_RISK_DERIVED"]


def test_enforce_counterparty_risk_default_fills_null_true_for_synthetic_fund() -> None:
    profile = _profile(replication=Replication.SYNTHETIC, counterpartyRisk=None)

    issues = enforce_counterparty_risk_default(profile)

    assert profile.counterpartyRisk is True
    assert [issue.code for issue in issues] == ["COUNTERPARTY_RISK_DERIVED"]


def test_enforce_issuer_disclosure_field_scope_keeps_performance_dependent_fields() -> None:
    profile = _profile(
        evidence=[
            EvidenceItem(
                field="distribution",
                quote="월 1회 분배",
                location="운용사 법정 공시 영역 — 분배금 지급 내역",
                sourceType="ISSUER_DISCLOSURE",
                translated=True,
            )
        ],
    )

    issues = enforce_issuer_disclosure_field_scope(profile)

    assert issues == []
    assert [item.field for item in profile.evidence] == ["distribution"]


def test_enforce_issuer_disclosure_field_scope_drops_it_for_other_fields() -> None:
    # Regression: Q10's exception is narrow -- ISSUER_DISCLOSURE must not be usable to
    # back a structural/contractual field like baseIndex that must come from the
    # prospectus itself, or fail-closed erodes field by field.
    profile = _profile(
        evidence=[
            EvidenceItem(
                field="baseIndex",
                quote="Example Index",
                location="운용사 홈페이지",
                sourceType="ISSUER_DISCLOSURE",
                translated=True,
            )
        ],
    )

    issues = enforce_issuer_disclosure_field_scope(profile)

    assert [issue.code for issue in issues] == ["ISSUER_DISCLOSURE_OUT_OF_SCOPE"]
    assert profile.evidence == []


def test_validate_quotes_skips_issuer_disclosure_evidence() -> None:
    profile = _profile(
        evidence=[
            EvidenceItem(
                field="distribution",
                quote="월 1회 분배",
                location="운용사 법정 공시 영역",
                sourceType="ISSUER_DISCLOSURE",
                translated=True,
            )
        ],
    )

    issues = _validate_quotes(profile, ENGLISH_SECTION)

    assert issues == []


def test_repair_or_drop_unsupported_evidence_keeps_issuer_disclosure_evidence() -> None:
    profile = _profile(
        evidence=[
            EvidenceItem(
                field="distribution",
                quote="월 1회 분배",
                location="운용사 법정 공시 영역",
                sourceType="ISSUER_DISCLOSURE",
                translated=True,
            )
        ],
    )

    issues = repair_or_drop_unsupported_evidence(profile, ENGLISH_SECTION)

    assert issues == []
    assert [item.field for item in profile.evidence] == ["distribution"]


def test_apply_us_fx_hedge_default_is_a_noop_for_kr_market() -> None:
    profile = _profile(market=Market.KR, fxHedge=FxHedge.NOT_APPLICABLE)

    issues = apply_us_fx_hedge_default(profile)

    assert profile.fxHedge == FxHedge.NOT_APPLICABLE
    assert issues == []


ENGLISH_SECTION = [
    Section(
        part=None,
        clause=None,
        title="Summary Prospectus",
        text="The Fund invests in swap agreements and futures contracts.",
        page_start=1,
        page_end=1,
    )
]


def test_validate_quotes_checks_quote_original_against_source_not_the_korean_translation() -> None:
    # Regression for the bug found 2026-09-02: quote is a Korean translation of a
    # US filing and can never literally appear in the English source text, so
    # checking `quote` against the corpus made every correctly-translated US
    # evidence item fail QUOTE_NOT_FOUND -- it only "passed" when the LLM left
    # quote untranslated in English by mistake. quoteOriginal is the literal
    # untranslated sentence and is what must be checked instead.
    profile = _profile(
        evidence=[
            EvidenceItem(
                field="replication",
                quote="펀드는 스왑 계약과 선물 계약에 투자합니다.",
                quoteOriginal="The Fund invests in swap agreements and futures contracts.",
                location="Principal Investment Strategies",
                sourceType="US_SUMMARY_PROSPECTUS",
                translated=True,
            )
        ],
    )

    issues = _validate_quotes(profile, ENGLISH_SECTION)

    assert issues == []


def test_validate_quotes_fails_closed_when_only_a_korean_translation_is_given() -> None:
    profile = _profile(
        evidence=[
            EvidenceItem(
                field="replication",
                quote="펀드는 스왑 계약과 선물 계약에 투자합니다.",
                quoteOriginal=None,
                location="Principal Investment Strategies",
                sourceType="US_SUMMARY_PROSPECTUS",
                translated=True,
            )
        ],
    )

    issues = _validate_quotes(profile, ENGLISH_SECTION)

    assert [issue.code for issue in issues] == ["QUOTE_NOT_FOUND"]


class MockUsLlmClient:
    model = "mock-us-model"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def extract(self, prompt: str, context: str) -> dict[str, Any]:
        assert "SEC 요약투자설명서" in prompt
        assert "INVESTMENT OBJECTIVE" in context
        return self.payload


def _valid_us_payload() -> dict[str, Any]:
    evidence = [
        ("name", "Example Covered Call ETF"),
        ("baseIndex", "the Example Index"),
        ("replication", "invests in the securities of the Example Index"),
        ("strategy", "writes (sells) call options"),
        ("distribution", "Total Annual Fund Operating Expenses 0.35%"),
        ("totalExpense", "Total Annual Fund Operating Expenses 0.35%"),
    ]
    return {
        "name": "Example Covered Call ETF",
        "code": "ABCD",
        "isin": None,
        "market": "US",
        "baseIndex": "Example Index",
        "replication": "실물",
        "leverage": 0,  # deliberately wrong -- should be forced to 1.0
        "dailyRebalancing": None,
        "isActive": None,
        "strategy": "커버드콜",
        "distribution": "월분배",
        "distributionYield": None,
        "targetYear": None,
        "totalExpense": 0.35,
        "fxHedge": "해당없음",  # deliberately unresolved -- should default to 미헤지
        "counterpartyRisk": None,
        "counterparty": None,
        "mainAssets": [],
        "isComplexProduct": None,
        "evidence": [
            {
                "field": field,
                "quote": quote,
                "location": "Principal Investment Strategies",
                "sourceType": "US_SUMMARY_PROSPECTUS",
                "translated": True,
            }
            for field, quote in evidence
        ],
    }


def test_extract_us_profile_forces_leverage_and_fx_hedge_defaults(tmp_path: Path) -> None:
    html_path = tmp_path / "ABCD.htm"
    html_path.write_text(SUMMARY_PROSPECTUS_HTML, encoding="utf-8")
    parser = UsSummaryParser()
    pages, _ = parser.extract_pages(html_path, "ABCD")
    sections = parser.split_sections(pages)

    result = extract_us_profile(
        "ABCD",
        sections=sections,
        llm_client=MockUsLlmClient(_valid_us_payload()),
        write_output=False,
    )

    assert result.profile.leverage == 1.0
    assert result.profile.fxHedge == FxHedge.UNHEDGED
    assert any(issue.code == "LEVERAGE_FORCED_TO_ONE" for issue in result.issues)
    assert any(issue.code == "FX_HEDGE_DERIVED" for issue in result.issues)
