from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from app.api.routes.etfs import get_etf_service
from app.domain.enums import Purpose
from app.main import app
from app.models import (
    EtfHiddenInsight,
    EtfMaster,
    EtfNameToken,
    EtfProfile,
    Evidence,
    RuleConfig,
    RuleConfigVariant,
)
from app.services.etfs import EtfNotFoundError, EtfReadService


class FakeEtfReadService(EtfReadService):
    def __init__(self) -> None:
        self.masters = {
            "102110": _master("102110", "TIGER 200", "KR", 6, "지수추종", "해당없음"),
            "QYLD": _master(
                "QYLD",
                "Global X NASDAQ 100 Covered Call ETF",
                "US",
                8,
                "커버드콜",
                "미헤지",
            ),
        }
        self.configs = _rule_configs()

    def list_etfs(self, q: str | None = None) -> dict[str, list[dict[str, Any]]]:
        rows = sorted(self.masters.values(), key=lambda item: item.display_order or 0)
        if q:
            rows = [item for item in rows if q in item.code or q in item.name]
        domestic = []
        overseas = []
        for master in rows:
            item = {
                "code": master.code,
                "name": master.name,
                "manager": master.manager,
                "market": master.market,
                "ready": master.profile is not None and master.profile.reviewed_at is not None,
                "displayOrder": master.display_order,
            }
            if master.market == "US":
                overseas.append(item)
            else:
                domestic.append(item)
        return {"domestic": domestic, "overseas": overseas}

    def _reviewed_master(self, code: str) -> EtfMaster:
        try:
            return self.masters[code]
        except KeyError as exc:
            raise EtfNotFoundError(code) from exc

    def _rule_configs(self, codes: list[str]) -> dict[str, RuleConfig]:
        return {code: self.configs[code] for code in codes}


def test_list_etfs_groups_by_market_and_keeps_display_order() -> None:
    client = _client(FakeEtfReadService())

    response = client.get("/api/v1/etfs")

    assert response.status_code == 200
    assert response.json()["domestic"] == [
        {
            "code": "102110",
            "name": "TIGER 200",
            "manager": "미래에셋자산운용",
            "market": "KR",
            "ready": True,
            "displayOrder": 6,
        }
    ]
    assert response.json()["overseas"][0]["code"] == "QYLD"


def test_get_etf_detail_renders_name_and_structure_contract() -> None:
    client = _client(FakeEtfReadService())

    response = client.get("/api/v1/etfs/QYLD")

    assert response.status_code == 200
    body = response.json()
    assert body["tokens"][1] == {
        "seq": 2,
        "text": None,
        "absent": "H",
        "translation": "환율에 따라 수익이 달라집니다",
    }
    assert body["hiddenInsight"]["summary"] == "분배금은 옵션 프리미엄에서 나옵니다"
    assert body["structure"]["baseIndex"]["question"] == "무엇을 따라가나요"
    assert body["structure"]["totalExpense"]["value"] == "0.6%"
    assert body["evidence"][0]["sourceType"] == "US_SUMMARY_PROSPECTUS"


def test_diagnosis_uses_rule_config_variant_and_no_llm_input() -> None:
    client = _client(FakeEtfReadService())

    response = client.get(
        "/api/v1/etfs/QYLD/diagnosis",
        params={"horizon": "LONG", "purpose": "GROWTH", "fund_nature": "SPARE"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["banner"]["level"] == "single"
    assert body["banner"]["subtext"] == "5년 이상 · 자산 성장 기준으로 살펴봤어요"
    assert body["warnings"][0]["code"] == "W-CC-01"
    assert body["warnings"][0]["summary"] == "오래 둘수록 지수와 차이가 벌어져요"
    assert body["warnings"][0]["title"] == "오래 묻어두는 목적과 맞지 않습니다"
    assert body["warnings"][0]["purposeAddon"] is None
    assert body["infos"][0]["code"] == "I-OVS-01"


def test_diagnosis_returns_checklist_when_no_warnings() -> None:
    client = _client(FakeEtfReadService())

    response = client.get(
        "/api/v1/etfs/102110/diagnosis",
        params={"horizon": "LONG", "purpose": "GROWTH", "fund_nature": "PURPOSE"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["banner"]["level"] == "none"
    # fund_nature=PURPOSE — 기획 정본의 "마무리 문장(경고 0건)" 표: 목적자금은
    # "꼭 필요한 돈..." 문장이 앞에 붙는다(여윳돈만 "다만 모든 투자에는..."만 나온다).
    assert body["banner"]["note"] == (
        "꼭 필요한 돈이라고 하셨는데, 어긋나는 점은 없었어요. "
        "다만 모든 투자에는 원금 손실 가능성이 있습니다."
    )
    assert body["warnings"] == []
    assert body["checklist"]["generalRisks"][0] == "모든 투자에는 원금 손실 가능성이 있습니다."


def test_diagnosis_returns_400_for_missing_and_invalid_parameters() -> None:
    client = _client(FakeEtfReadService())

    missing = client.get("/api/v1/etfs/QYLD/diagnosis")
    invalid = client.get(
        "/api/v1/etfs/QYLD/diagnosis",
        params={"horizon": "FOREVER", "purpose": "GROWTH", "fund_nature": "SPARE"},
    )

    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "MISSING_PARAMETER"
    assert invalid.status_code == 400
    assert invalid.json()["error"] == {
        "code": "INVALID_PARAMETER",
        "message": "horizon 값이 올바르지 않습니다.",
        "field": "horizon",
    }


def test_batch_diagnosis_groups_matched_and_unmatched_etfs() -> None:
    client = _client(FakeEtfReadService())

    response = client.get(
        "/api/v1/etfs/diagnosis/batch",
        params={
            "codes": "102110,QYLD",
            "horizon": "LONG",
            "purpose": "GROWTH",
            "fund_nature": "SPARE",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] == [{"code": "102110", "name": "TIGER 200", "warningCount": 0}]
    assert body["unmatched"] == [
        {
            "code": "QYLD",
            "name": "Global X NASDAQ 100 Covered Call ETF",
            "warningCount": 1,
            "warningCodes": ["W-CC-01"],
        }
    ]
    assert body["riskSummary"] == {"목적 불일치": 1}


def test_batch_diagnosis_rejects_more_than_8_codes() -> None:
    client = _client(FakeEtfReadService())

    response = client.get(
        "/api/v1/etfs/diagnosis/batch",
        params={
            "codes": "A,B,C,D,E,F,G,H,I",
            "horizon": "LONG",
            "purpose": "GROWTH",
            "fund_nature": "SPARE",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "TOO_MANY_CODES",
        "message": "codes는 최대 8개까지 가능합니다.",
        "field": "codes",
    }


def test_context_combines_structure_diagnosis_and_all_evidence_without_llm() -> None:
    client = _client(FakeEtfReadService())

    response = client.get(
        "/api/v1/etfs/QYLD/context",
        params={"horizon": "LONG", "purpose": "GROWTH", "fund_nature": "SPARE"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "QYLD"
    assert body["structure"]["baseIndex"]["value"] == "NASDAQ-100"
    assert body["diagnosis"]["warnings"][0]["code"] == "W-CC-01"
    assert [item["quote"] for item in body["evidence"]] == [
        "옵션 프리미엄을 통해 현금을 만듭니다.",
        "옵션을 매도합니다.",
    ]


def test_missing_or_unreviewed_etf_returns_404() -> None:
    client = _client(FakeEtfReadService())

    response = client.get("/api/v1/etfs/NOPE")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ETF_NOT_FOUND"


def _client(service: FakeEtfReadService) -> TestClient:
    app.dependency_overrides[get_etf_service] = lambda: service
    return TestClient(app)


def _master(
    code: str,
    name: str,
    market: str,
    display_order: int,
    strategy: str,
    fx_hedge: str,
) -> EtfMaster:
    master = EtfMaster(
        code=code,
        isin=None,
        name=name,
        market=market,
        manager="미래에셋자산운용" if market == "KR" else "Global X",
        listed_at=None,
        exchange=None,
        source="manual",
        display_order=display_order,
    )
    master.profile = EtfProfile(
        code=code,
        base_index="NASDAQ-100" if market == "US" else "KOSPI 200",
        replication="실물",
        leverage=Decimal("1.0"),
        daily_rebalancing=False,
        is_active=False,
        strategy=strategy,
        distribution="월분배" if strategy == "커버드콜" else "분기분배",
        distribution_yield=Decimal("11.5") if strategy == "커버드콜" else Decimal("2.0"),
        target_year=None,
        total_expense=Decimal("0.6") if market == "US" else Decimal("0.05"),
        fx_hedge=fx_hedge,
        counterparty_risk=False,
        counterparty=None,
        main_assets=["미국 기술주"] if market == "US" else ["국내 주식"],
        is_complex_product=False,
        extracted_by="manual",
        reviewed_at="2026-08-31T00:00:00+09:00",
    )
    master.name_tokens = [
        EtfNameToken(code=code, seq=1, text=code, absent=None, translation="상품 이름"),
        EtfNameToken(
            code=code,
            seq=2,
            text=None,
            absent="H",
            translation="환율에 따라 수익이 달라집니다",
        ),
    ]
    master.hidden_insight = EtfHiddenInsight(
        code=code,
        summary="분배금은 옵션 프리미엄에서 나옵니다",
        body="상승분 일부를 미리 파는 구조입니다.",
    )
    source_type = "US_SUMMARY_PROSPECTUS" if market == "US" else "KR_PROSPECTUS"
    master.evidence = [
        Evidence(
            id=1,
            code=code,
            field="hiddenInsight",
            rule_code=None,
            quote="옵션 프리미엄을 통해 현금을 만듭니다.",
            location="요약투자설명서",
            source_type=source_type,
            translated=market == "US",
            display_order=1,
        ),
        Evidence(
            id=2,
            code=code,
            field=None,
            rule_code="W-CC-01",
            quote="옵션을 매도합니다.",
            location="요약투자설명서",
            source_type=source_type,
            translated=market == "US",
            display_order=2,
        ),
    ]
    return master


def _rule_configs() -> dict[str, RuleConfig]:
    w_cc = RuleConfig(
        code="W-CC-01",
        level="warning",
        priority=2,
        category="목적 불일치",
        summary="가격이 올라도 그만큼 못 받아요",
        title="차익을 노리는 목적과 맞지 않습니다",
        body="기본 문구",
        purpose_addon=(
            "목표한 금액이 있으시다면, 시장이 크게 올라도 그만큼 따라가지 못한다는 점을 "
            "미리 아셔야 합니다."
        ),
        widget_type="B",
    )
    w_cc.variants = [
        RuleConfigVariant(
            rule_code="W-CC-01",
            purpose=Purpose.GROWTH,
            summary="오래 둘수록 지수와 차이가 벌어져요",
            title="오래 묻어두는 목적과 맞지 않습니다",
            body="성장 목적 문구",
        )
    ]
    return {
        "W-CC-01": w_cc,
        "I-OVS-01": RuleConfig(
            code="I-OVS-01",
            level="info",
            summary="이 상품은 미국에 상장되어 있어요",
            body="미국 공시 문서를 대신 읽어 정리했습니다.",
        ),
        "I-FX-01": RuleConfig(
            code="I-FX-01",
            level="info",
            summary="환율에 따라 수익이 달라져요",
            body="환율 변동을 막는 장치가 없습니다.",
        ),
        "I-DIV-01": RuleConfig(
            code="I-DIV-01",
            level="info",
            summary="매달 돈을 나눠줘요",
            body="매월 마지막 영업일 기준으로 분배금을 지급합니다.",
        ),
        "OK-01": RuleConfig(
            code="OK-01",
            level="ok",
            summary="선택하신 조건 기준으로 어긋나는 부분은 발견되지 않았습니다",
            body="다만 모든 투자에는 원금 손실 가능성이 있습니다.",
        ),
    }
