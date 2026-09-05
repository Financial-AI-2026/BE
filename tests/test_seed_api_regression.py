"""Regression tests against the *real* `app/seed/etfs/*.json` and
`app/seed/rules.json` content — not hand-typed test fixtures.

`test_rules_matrix.py` and `test_etfs_api.py::FakeEtfReadService` both use
hand-typed profile/rule-config data. Nothing previously asserted that the real
seed files actually produce the documented 96-cell warning matrix through the
real API — so a seed edit could silently drift from what those other tests
check without either of them noticing.

No DB, no network: seed files are parsed with the same Pydantic schemas
`app/seed/load.py` uses, then held in memory as plain (unpersisted) SQLAlchemy
model instances — the same pattern `FakeEtfReadService` already uses for its
synthetic data, just built from the real files instead.
"""

from itertools import product
from typing import Any

from fastapi.testclient import TestClient

from app.api.routes.etfs import get_etf_service
from app.domain.enums import Distribution, FxHedge, Market, Replication, Strategy
from app.domain.rules import EtfRuleProfile
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
from app.seed.load import ETF_DIR, RULES_PATH, read_etf_seeds, read_rule_seeds
from app.seed.schemas import EtfSeed, RuleSeed
from app.services.etfs import EtfNotFoundError, EtfReadService
from tests.test_rules_matrix import EXPECTED_WARNINGS, HORIZONS, PROFILES, PURPOSES

ETF_SEEDS = read_etf_seeds(ETF_DIR)
RULE_SEEDS = read_rule_seeds(RULES_PATH)


class SeedFileEtfReadService(EtfReadService):
    """EtfReadService backed by the real seed files, held in memory (no DB)."""

    def __init__(self) -> None:
        self.masters = {seed.master.code: _build_master(seed) for seed in ETF_SEEDS}
        self.configs = _build_rule_configs(RULE_SEEDS)

    def list_etfs(self, q: str | None = None) -> dict[str, list[dict[str, Any]]]:
        rows = sorted(self.masters.values(), key=lambda item: item.display_order or 0)
        if q:
            rows = [item for item in rows if q in item.code or q in item.name]
        domestic: list[dict[str, Any]] = []
        overseas: list[dict[str, Any]] = []
        for master in rows:
            item = {
                "code": master.code,
                "name": master.name,
                "manager": master.manager,
                "market": master.market,
                "ready": master.profile is not None and master.profile.reviewed_at is not None,
                "displayOrder": master.display_order,
            }
            (overseas if master.market == "US" else domestic).append(item)
        return {"domestic": domestic, "overseas": overseas}

    def _reviewed_master(self, code: str) -> EtfMaster:
        try:
            master = self.masters[code]
        except KeyError as exc:
            raise EtfNotFoundError(code) from exc
        if master.profile is None or master.profile.reviewed_at is None:
            raise EtfNotFoundError(code)
        return master

    def _rule_configs(self, codes: list[str]) -> dict[str, RuleConfig]:
        return {code: self.configs[code] for code in codes}


def _build_master(seed: EtfSeed) -> EtfMaster:
    code = seed.master.code
    master = EtfMaster(**seed.master.model_dump())
    master.profile = (
        EtfProfile(code=code, **seed.profile.model_dump()) if seed.profile is not None else None
    )
    master.name_tokens = [EtfNameToken(code=code, **token.model_dump()) for token in seed.tokens]
    master.hidden_insight = (
        EtfHiddenInsight(code=code, **seed.hidden_insight.model_dump())
        if seed.hidden_insight is not None
        else None
    )
    master.evidence = [
        Evidence(id=idx, code=code, **evidence.model_dump())
        for idx, evidence in enumerate(seed.evidence, start=1)
    ]
    return master


def _build_rule_configs(rule_seeds: list[RuleSeed]) -> dict[str, RuleConfig]:
    configs: dict[str, RuleConfig] = {}
    for seed in rule_seeds:
        config = RuleConfig(**seed.model_dump(exclude={"variants"}))
        config.variants = [
            RuleConfigVariant(rule_code=seed.code, **variant.model_dump())
            for variant in seed.variants
        ]
        configs[seed.code] = config
    return configs


def _client() -> TestClient:
    app.dependency_overrides[get_etf_service] = lambda: SeedFileEtfReadService()
    return TestClient(app)


def test_real_seed_covers_all_eight_mvp_codes() -> None:
    assert {seed.master.code for seed in ETF_SEEDS} == set(PROFILES)


def test_real_seed_profile_matches_documented_rule_matrix() -> None:
    # Guards against test_rules_matrix.py's hand-typed PROFILES silently
    # drifting from what's actually in app/seed/etfs/*.json.
    for seed in ETF_SEEDS:
        code = seed.master.code
        profile = seed.profile
        assert profile is not None, f"{code}: seed has no profile"
        real = EtfRuleProfile(
            code=code,
            market=Market(seed.master.market),
            replication=Replication(profile.replication),
            leverage=profile.leverage,
            strategy=Strategy(profile.strategy),
            distribution=Distribution(profile.distribution),
            distribution_yield=profile.distribution_yield,
            fx_hedge=FxHedge(profile.fx_hedge),
        )
        assert real == PROFILES[code], (
            f"{code}: seed profile diverged from test_rules_matrix.PROFILES — "
            f"seed={real} vs matrix={PROFILES[code]}"
        )


def test_real_seed_api_lists_all_eight_as_ready() -> None:
    response = _client().get("/api/v1/etfs")

    assert response.status_code == 200
    body = response.json()
    codes = {item["code"] for item in body["domestic"] + body["overseas"]}
    assert codes == set(PROFILES)
    assert len(body["domestic"]) == 6
    assert len(body["overseas"]) == 2
    assert all(item["ready"] for item in body["domestic"] + body["overseas"])


def test_real_seed_api_detail_succeeds_for_all_eight_codes() -> None:
    client = _client()
    for code in PROFILES:
        response = client.get(f"/api/v1/etfs/{code}")
        assert response.status_code == 200, f"{code}: {response.text}"
        assert response.json()["code"] == code


def test_real_seed_api_diagnosis_matches_documented_96_cell_matrix() -> None:
    client = _client()
    for code in PROFILES:
        for horizon, purpose in product(HORIZONS, PURPOSES):
            purpose_index = PURPOSES.index(purpose)
            expected = EXPECTED_WARNINGS[code][horizon][purpose_index]

            response = client.get(
                f"/api/v1/etfs/{code}/diagnosis",
                params={"horizon": horizon.value, "purpose": purpose.value, "fund_nature": "SPARE"},
            )

            assert response.status_code == 200, f"{code}/{horizon}/{purpose}: {response.text}"
            warning_codes = tuple(item["code"] for item in response.json()["warnings"])
            assert warning_codes == expected, f"{code}/{horizon}/{purpose}"


def test_composite_banner_matches_documented_worked_example() -> None:
    # 기획 정본의 "조합별 실제 문장 예시" — "경고 3개 — #2 / 5년 이상 /
    # 매달 현금 / 목적자금 → LEV + TR + FX". Byte-for-byte against the 정본 문서.
    response = _client().get(
        "/api/v1/etfs/418660/diagnosis",
        params={"horizon": "LONG", "purpose": "INCOME", "fund_nature": "PURPOSE"},
    )

    assert response.status_code == 200
    banner = response.json()["banner"]
    assert banner["text"] == "이런 점이 회원님 계획과 다릅니다."
    assert banner["sentences"] == [
        "5년 이상 두실 계획이라고 하셨는데, 이 상품은 지수의 2배로 움직이고 한 번 크게 "
        "떨어지면 원래대로 돌아오기 어려워서, 오래 둘수록 지수와 차이가 벌어질 수 있어요.",
        "매달 현금을 받고 싶다고 하셨는데, 이 상품도 돈을 나눠주긴 하지만 1년에 한 번 적은 "
        "금액이라서, 생활비로 쓰기에는 부족할 수 있어요.",
        "매달 일정한 돈이 필요하다고 하셨는데, 이 상품은 환율이 오르내리는 만큼 수익도 같이 "
        "흔들려서, 받는 금액이 환율 따라 왔다 갔다 해요.",
    ]
    assert banner["note"] == (
        "나중에 꼭 써야 할 돈이라면, 필요한 시점에 원하는 금액이 안 될 수도 있다는 점을 "
        "감안해주세요."
    )


def test_composite_banner_zero_warnings_spare_fund_nature_matches_documented_example() -> None:
    # 같은 문서 — "경고 0개 / 여윳돈 — #10 / 1~5년 / 시세차익" → 마무리 문장 한 줄만.
    response = _client().get(
        "/api/v1/etfs/102110/diagnosis",
        params={"horizon": "MID", "purpose": "CAPITAL_GAIN", "fund_nature": "SPARE"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["banner"]["text"] == "회원님 계획과 어긋나는 점은 없었어요."
    assert body["banner"]["note"] == "다만 모든 투자에는 원금 손실 가능성이 있습니다."
    checklist_by_rule = {item["rule"]: item["value"] for item in body["checklist"]["items"]}
    assert checklist_by_rule["W-FX"] == "해당없음 (국내 상품)"


def test_real_seed_api_batch_diagnosis_covers_all_eight_codes() -> None:
    response = _client().get(
        "/api/v1/etfs/diagnosis/batch",
        params={
            "codes": ",".join(PROFILES),
            "horizon": "MID",
            "purpose": "GROWTH",
            "fund_nature": "SPARE",
        },
    )

    assert response.status_code == 200
    body = response.json()
    seen = {item["code"] for item in body["matched"] + body["unmatched"]}
    assert seen == set(PROFILES)


def test_real_seed_api_context_succeeds_for_all_eight_codes() -> None:
    client = _client()
    for code in PROFILES:
        response = client.get(
            f"/api/v1/etfs/{code}/context",
            params={"horizon": "MID", "purpose": "GROWTH", "fund_nature": "SPARE"},
        )
        assert response.status_code == 200, f"{code}: {response.text}"
        assert response.json()["code"] == code
