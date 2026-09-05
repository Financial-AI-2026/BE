from decimal import Decimal
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, joinedload

from app.domain.enums import FundNature, FxHedge, Horizon, Market, Purpose
from app.domain.rules import EtfRuleProfile, evaluate_rule_codes
from app.models import (
    EtfMaster,
    EtfProfile,
    Evidence,
    RuleConfig,
)

HORIZON_LABELS = {
    Horizon.SHORT: "1년 안에",
    Horizon.MID: "1~5년",
    Horizon.LONG: "5년 이상",
    Horizon.UNKNOWN: "기간 미정",
}
PURPOSE_LABELS = {
    Purpose.CAPITAL_GAIN: "시세차익",
    Purpose.INCOME: "매달 현금",
    Purpose.GROWTH: "자산 성장",
}
STRUCTURE_QUESTIONS = {
    "baseIndex": ("기초지수", "무엇을 따라가나요"),
    "leverage": ("배율", "몇 배로 움직이나요"),
    "replication": ("복제방식", "실제로 주식을 사나요"),
    "fxHedge": ("환헤지", "환율 영향을 막나요"),
    "distribution": ("분배", "돈을 나눠주나요"),
    "totalExpense": ("총보수", "비용이 얼마인가요"),
}

# S4 "구조 한눈에 보기" 카드의 보조 설명 한 줄. 기초지수는 정본 문서의 이름 토큰
# "상세 설명"에서 검증된 문구를 그대로 재사용했다 — 지어낸 게 아니다. 복제방식
# /환헤지/분배는 정본에 재사용 가능한 형태로 정의된 게 없어서 초안으로 채워뒀다
# (기획 확인 요청 중, 확정되면 이 표만 갱신할 것).
BASE_INDEX_GLOSSARY = {
    "NASDAQ-100": "미국 나스닥 시장의 기술 중심 대형기업 100개를 묶은 지수예요",
    "S&P 500": "미국에 상장된 대형 회사 500개를 묶은 지수예요",
    "코스피200": "코스피에 상장된 대표 기업 200개를 묶은 지수예요",
}
# 대소문자만 다르게 저장된 경우가 있다 (예: TQQQ의 base_index는 "Nasdaq-100",
# 418660은 "NASDAQ-100") — 실사용 중 발견. 원문 값 표기는 그대로 두고(대소문자를
# 규격화하지 않는다, 시딩 시 손대지 말라는 원칙과 같은 이유) 조회만 대소문자
# 무시하도록 별도 인덱스를 둔다.
_BASE_INDEX_GLOSSARY_CASEFOLDED = {
    key.casefold(): value for key, value in BASE_INDEX_GLOSSARY.items()
}


def _base_index_sub(base_index: str) -> str | None:
    return _BASE_INDEX_GLOSSARY_CASEFOLDED.get(base_index.casefold())
REPLICATION_GLOSSARY = {  # 초안 — 기획 확인 전
    "실물": "지수에 담긴 주식을 실제로 사서 담아요",
    "합성": "실제 주식은 안 사고, 증권사와 계약(스왑)만 맺어 수익률을 받아와요",
}
FX_HEDGE_GLOSSARY = {  # 초안 — 기획 확인 전
    "헤지": "환율이 오르내려도 수익률엔 영향을 덜 받도록 막아둔 상품이에요",
    "미헤지": "환율 변동을 막는 장치가 없어서, 환율에 따라 수익이 달라질 수 있어요",
    "해당없음": "국내 자산에 투자해서 환율 영향 자체가 없어요",
}
DISTRIBUTION_GLOSSARY = {  # 초안 — 기획 확인 전
    "무분배": "분배금을 따로 주지 않고, 수익을 계속 재투자해요",
    "월분배": "매달 분배금을 나눠줘요",
    "분기분배": "3개월마다 분배금을 나눠줘요",
    "반기분배": "6개월마다 분배금을 나눠줘요",
    "연분배": "1년에 한 번 분배금을 나눠줘요",
}
CHECKLIST_LABELS = {
    "W-LEV": "지수보다 크게 움직이는 구조",
    "W-CC": "오를 상한이 정해진 구조",
    "W-MIX": "주식과 채권을 섞은 구조",
    "W-TR": "나눠주는 돈",
    "W-FX": "환율",
}

# 진단 결과(S6) 최상단 "종합 멘트" — 기획 정본 문서 기준. 발동된 경고
# 전부(카드는 최대 2개만 노출하지만 여기는 전체)를 "{조건}이라고 하셨는데, {특성}이라서,
# {결과}" 3단 문장으로 조립한다. 조건/특성/결과는 문서 그대로이고, 상품마다 달라지는
# 부분(배율·분배주기·국내외)만 실제 값으로 채운다 — 그래서 8종 밖의 상품에도 그대로
# 재사용된다.
LEV_CONDITION_BY_HORIZON = {
    Horizon.MID: "1~5년 두실 계획이라고 하셨는데",
    Horizon.LONG: "5년 이상 두실 계획이라고 하셨는데",
    Horizon.UNKNOWN: "얼마나 두실지 아직 정하지 않으셨는데",
    # SHORT은 W-LEV-01이 발동하지 않는 조합이라 등장하지 않는다 (app/domain/rules.py).
}
CC_CONDITION_BY_PURPOSE = {
    Purpose.CAPITAL_GAIN: "올랐을 때 파실 생각이라고 하셨는데",
    Purpose.GROWTH: "오래 두고 불리실 생각이라고 하셨는데",
    # INCOME은 W-CC-01이 발동하지 않는다.
}
MIX_CONDITION = "올랐을 때 파실 생각이라고 하셨는데"  # W-MIX-01은 시세차익에서만 발동
TR_CONDITION = "매달 현금을 받고 싶다고 하셨는데"  # W-TR-01은 인컴에서만 발동
FX_CONDITION = "매달 일정한 돈이 필요하다고 하셨는데"  # W-FX-01은 인컴에서만 발동

# 분배주기 → 종합멘트 문장 속 자연어 표현. 체크리스트("나눠주는 돈")에도 재사용한다.
DISTRIBUTION_FREQUENCY_PHRASE = {
    "무분배": "나눠주지 않고",
    "월분배": "매달",
    "분기분배": "세 달에 한 번",
    "반기분배": "여섯 달에 한 번",
    "연분배": "1년에 한 번",
}

CLOSING_LINE_WITH_WARNINGS = {
    FundNature.PURPOSE: (
        "나중에 꼭 써야 할 돈이라면, 필요한 시점에 원하는 금액이 안 될 수도 있다는 "
        "점을 감안해주세요."
    ),
    FundNature.SPARE: (
        "여윳돈이라고 하셨으니 부담은 덜하겠지만, 어떤 구조인지는 알고 사시는 게 "
        "좋아요."
    ),
}
CLOSING_LINE_NO_WARNINGS = {
    FundNature.PURPOSE: (
        "꼭 필요한 돈이라고 하셨는데, 어긋나는 점은 없었어요. 다만 모든 투자에는 "
        "원금 손실 가능성이 있습니다."
    ),
    FundNature.SPARE: "다만 모든 투자에는 원금 손실 가능성이 있습니다.",
}


class EtfNotFoundError(Exception):
    pass


class EtfReadService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_etfs(self, q: str | None = None) -> dict[str, list[dict[str, Any]]]:
        # No `display_order IS NOT NULL` filter here on purpose (2026-09
        # 결정): search must cover the full universe, not just the 8 MVP
        # cards. The 8-card landing view is a FE-side concern — it takes the
        # top 8 by `displayOrder` out of this same list. `display_order.nulls`
        # sort last so the curated 8 still lead an unfiltered/no-`q` listing.
        stmt = (
            select(EtfMaster)
            .outerjoin(EtfProfile)
            .options(joinedload(EtfMaster.profile))
            .order_by(EtfMaster.display_order.is_(None), EtfMaster.display_order, EtfMaster.code)
        )
        if q:
            stmt = stmt.where(or_(EtfMaster.code.ilike(f"%{q}%"), EtfMaster.name.ilike(f"%{q}%")))

        domestic: list[dict[str, Any]] = []
        overseas: list[dict[str, Any]] = []
        for master in self.session.scalars(stmt).unique():
            item = {
                "code": master.code,
                "name": master.name,
                "manager": master.manager,
                "market": master.market,
                "ready": master.profile is not None and master.profile.reviewed_at is not None,
                "displayOrder": master.display_order,
            }
            if master.market == Market.US:
                overseas.append(item)
            else:
                domestic.append(item)

        return {"domestic": domestic, "overseas": overseas}

    def list_etf_summaries(self) -> list[dict[str, Any]]:
        """Compact per-product structure summary for all reviewed ETFs.

        Used by the chatbot to answer cross-product listing/filter questions
        (e.g. "매달 분배하는 상품 뭐 있어요?") that span beyond the single
        product currently in view.
        """
        stmt = (
            select(EtfMaster, EtfProfile)
            .join(EtfProfile)
            .where(EtfProfile.reviewed_at.is_not(None))
            .order_by(EtfMaster.display_order.is_(None), EtfMaster.display_order, EtfMaster.code)
        )
        return [
            {
                "code": master.code,
                "name": master.name,
                "market": master.market,
                "strategy": profile.strategy,
                "leverage": _format_decimal(profile.leverage),
                "replication": profile.replication,
                "distribution": profile.distribution,
                "fxHedge": profile.fx_hedge,
                "totalExpense": _format_decimal(profile.total_expense),
            }
            for master, profile in self.session.execute(stmt).all()
        ]

    def get_etf_detail(self, code: str) -> dict[str, Any]:
        master = self._reviewed_master(code)
        profile = _required_profile(master)

        return {
            "code": master.code,
            "name": master.name,
            "market": master.market,
            "tokens": _name_tokens(master),
            "hiddenInsight": _hidden_insight(master),
            "structure": _structure(profile),
            "evidence": [
                _evidence_item(evidence)
                for evidence in _sorted_evidence(master.evidence)
                if evidence.field == "hiddenInsight"
            ][:1],
            "loadingStats": None,
        }

    def get_etf_diagnosis(
        self,
        code: str,
        horizon: Horizon,
        purpose: Purpose,
        fund_nature: FundNature,
    ) -> dict[str, Any]:
        master = self._reviewed_master(code)
        profile = _required_profile(master)
        result = evaluate_rule_codes(_rule_profile(master, profile), horizon, purpose)
        rule_codes = [*result.warnings, *result.infos]
        if result.ok:
            rule_codes.append(result.ok)
        configs = self._rule_configs(rule_codes)
        evidence_by_rule = _evidence_by_rule(master.evidence)

        warnings = [
            _rule_card(
                config=configs[rule_code],
                profile=profile,
                horizon=horizon,
                purpose=purpose,
                fund_nature=fund_nature,
                evidence=evidence_by_rule.get(rule_code, []),
            )
            for rule_code in result.warnings
        ]
        infos = [
            _info_card(
                config=configs[rule_code],
                profile=profile,
                horizon=horizon,
                purpose=purpose,
                evidence=evidence_by_rule.get(rule_code, []),
            )
            for rule_code in result.infos
        ]

        return {
            "code": master.code,
            "name": master.name,
            "banner": _banner(
                list(result.warnings), master, profile, horizon, purpose, fund_nature
            ),
            "warnings": warnings,
            "warningsVisible": min(len(warnings), 2),
            "infos": infos,
            "checklist": _checklist(profile) if not warnings else None,
        }

    def get_batch_diagnosis(
        self,
        codes: list[str],
        horizon: Horizon,
        purpose: Purpose,
    ) -> dict[str, Any]:
        masters = [self._reviewed_master(code) for code in codes]
        evaluated = []
        warning_codes: set[str] = set()
        for master in masters:
            profile = _required_profile(master)
            result = evaluate_rule_codes(_rule_profile(master, profile), horizon, purpose)
            evaluated.append((master, result.warnings))
            warning_codes.update(result.warnings)

        configs = self._rule_configs(sorted(warning_codes))
        matched: list[dict[str, Any]] = []
        unmatched: list[dict[str, Any]] = []
        risk_summary: dict[str, int] = {}

        for master, warnings in evaluated:
            if not warnings:
                matched.append({"code": master.code, "name": master.name, "warningCount": 0})
                continue

            warning_list = list(warnings)
            unmatched.append(
                {
                    "code": master.code,
                    "name": master.name,
                    "warningCount": len(warning_list),
                    "warningCodes": warning_list,
                }
            )
            for rule_code in warning_list:
                category = configs[rule_code].category or "기타"
                risk_summary[category] = risk_summary.get(category, 0) + 1

        return {"matched": matched, "unmatched": unmatched, "riskSummary": risk_summary}

    def get_etf_context(
        self,
        code: str,
        horizon: Horizon,
        purpose: Purpose,
        fund_nature: FundNature,
    ) -> dict[str, Any]:
        master = self._reviewed_master(code)
        profile = _required_profile(master)
        return {
            "code": master.code,
            "name": master.name,
            "market": master.market,
            "tokens": _name_tokens(master),
            "structure": _structure(profile),
            "diagnosis": self.get_etf_diagnosis(code, horizon, purpose, fund_nature),
            "evidence": [_evidence_item(item) for item in _sorted_evidence(master.evidence)],
        }

    def _reviewed_master(self, code: str) -> EtfMaster:
        stmt = (
            select(EtfMaster)
            .options(
                joinedload(EtfMaster.profile),
                joinedload(EtfMaster.name_tokens),
                joinedload(EtfMaster.hidden_insight),
                joinedload(EtfMaster.evidence),
            )
            .where(EtfMaster.code == code)
        )
        master = self.session.scalars(stmt).unique().one_or_none()
        if master is None or master.profile is None or master.profile.reviewed_at is None:
            raise EtfNotFoundError(code)
        return master

    def _rule_configs(self, codes: list[str]) -> dict[str, RuleConfig]:
        if not codes:
            return {}
        stmt: Select[tuple[RuleConfig]] = (
            select(RuleConfig).options(joinedload(RuleConfig.variants)).where(RuleConfig.code.in_(codes))
        )
        configs = {config.code: config for config in self.session.scalars(stmt).unique()}
        missing = set(codes) - set(configs)
        if missing:
            raise RuntimeError(f"missing rule_config rows: {sorted(missing)}")
        return configs


def _required_profile(master: EtfMaster) -> EtfProfile:
    if master.profile is None:
        raise EtfNotFoundError(master.code)
    return master.profile


def _name_tokens(master: EtfMaster) -> list[dict[str, Any]]:
    return [
        {
            "seq": token.seq,
            "text": token.text,
            "absent": token.absent,
            "translation": token.translation,
        }
        for token in master.name_tokens
    ]


def _hidden_insight(master: EtfMaster) -> dict[str, str] | None:
    if master.hidden_insight is None:
        return None
    return {"summary": master.hidden_insight.summary, "body": master.hidden_insight.body}


def _structure(profile: EtfProfile) -> dict[str, dict[str, str | None]]:
    return {
        "baseIndex": _structure_item(
            "baseIndex", profile.base_index, _base_index_sub(profile.base_index)
        ),
        "leverage": _structure_item(
            "leverage", f"{_format_decimal(profile.leverage)}배", _leverage_sub(profile.leverage)
        ),
        "replication": _structure_item(
            "replication", profile.replication, REPLICATION_GLOSSARY.get(profile.replication)
        ),
        "fxHedge": _structure_item(
            "fxHedge", profile.fx_hedge, FX_HEDGE_GLOSSARY.get(profile.fx_hedge)
        ),
        "distribution": _structure_item(
            "distribution", profile.distribution, DISTRIBUTION_GLOSSARY.get(profile.distribution)
        ),
        "totalExpense": _structure_item(
            "totalExpense",
            f"{_format_decimal(profile.total_expense)}%",
            _total_expense_sub(profile.total_expense),
        ),
    }


def _structure_item(key: str, value: str, sub: str | None = None) -> dict[str, str | None]:
    label, question = STRUCTURE_QUESTIONS[key]
    return {"label": label, "question": question, "value": value, "sub": sub}


def _leverage_sub(leverage: Decimal) -> str | None:
    # 배율이 1배(그대로 추종)면 "하루 단위 계산"이 딱히 설명할 게 없다 — 레버리지/인버스
    # 상품(1배가 아닌 경우)에서만 매일 재계산되는 구조라는 걸 짚어준다.
    if leverage == Decimal("1.0"):
        return None
    return f"단, 하루 단위로 {_format_decimal(leverage)}배를 계산해요"


def _total_expense_sub(total_expense: Decimal) -> str:
    # % → 100만원 기준 원화 환산. 계산일 뿐이라 상품마다 새로 정할 필요가 없다
    # (디자인 시안·구 mock 둘 다 0.25% 예시에서 "100만원당 2,500원"으로 같은 값을 썼다).
    amount = total_expense / Decimal("100") * Decimal("1000000")
    return f"100만원당 {amount:,.0f}원이에요"


def _rule_profile(master: EtfMaster, profile: EtfProfile) -> EtfRuleProfile:
    return EtfRuleProfile(
        code=master.code,
        market=Market(master.market),
        replication=profile.replication,
        leverage=profile.leverage,
        strategy=profile.strategy,
        distribution=profile.distribution,
        distribution_yield=profile.distribution_yield,
        fx_hedge=profile.fx_hedge,
    )


def _rule_card(
    config: RuleConfig,
    profile: EtfProfile,
    horizon: Horizon,
    purpose: Purpose,
    fund_nature: FundNature,
    evidence: list[Evidence],
) -> dict[str, Any]:
    copy = _copy_for_purpose(config, purpose)
    return {
        "code": config.code,
        "priority": config.priority,
        "category": config.category,
        "summary": _render(copy["summary"], profile, horizon, purpose),
        "title": _render(copy["title"], profile, horizon, purpose) if copy["title"] else None,
        "body": _render(copy["body"], profile, horizon, purpose),
        "purposeAddon": config.purpose_addon if fund_nature == FundNature.PURPOSE else None,
        "widget": _widget(config.widget_type),
        "evidence": [_evidence_item(item) for item in evidence],
    }


def _info_card(
    config: RuleConfig,
    profile: EtfProfile,
    horizon: Horizon,
    purpose: Purpose,
    evidence: list[Evidence],
) -> dict[str, Any]:
    return {
        "code": config.code,
        "summary": _render(config.summary, profile, horizon, purpose),
        "body": _render(config.body, profile, horizon, purpose),
        "evidence": [_evidence_item(item) for item in evidence],
    }


def _copy_for_purpose(config: RuleConfig, purpose: Purpose) -> dict[str, str | None]:
    variant = next((item for item in config.variants if item.purpose == purpose), None)
    if variant is None:
        return {"summary": config.summary, "title": config.title, "body": config.body}
    return {"summary": variant.summary, "title": variant.title, "body": variant.body}


def _render(template: str, profile: EtfProfile, horizon: Horizon, purpose: Purpose) -> str:
    return (
        template.replace("{기간}", HORIZON_LABELS[horizon])
        .replace("{목적}", PURPOSE_LABELS[purpose])
        .replace("{배율}", _format_decimal(profile.leverage))
        .replace("{기초자산}", profile.base_index)
        .replace("{거래상대방}", profile.counterparty or "거래상대방")
    )


def _banner(
    warning_codes: list[str],
    master: EtfMaster,
    profile: EtfProfile,
    horizon: Horizon,
    purpose: Purpose,
    fund_nature: FundNature,
) -> dict[str, Any]:
    warning_count = len(warning_codes)
    if warning_count == 0:
        headline = "회원님 계획과 어긋나는 점은 없었어요."
    elif warning_count == 1:
        headline = "한 가지가 회원님 계획과 다릅니다."
    else:
        headline = "이런 점이 회원님 계획과 다릅니다."

    sentences = [
        sentence
        for code in warning_codes
        if (sentence := _warning_sentence(code, master, profile, horizon, purpose)) is not None
    ]
    closing = (
        CLOSING_LINE_WITH_WARNINGS[fund_nature]
        if warning_count
        else CLOSING_LINE_NO_WARNINGS[fund_nature]
    )

    return {
        "level": "none" if warning_count == 0 else ("single" if warning_count == 1 else "multiple"),
        "text": headline,
        "subtext": f"{HORIZON_LABELS[horizon]} · {PURPOSE_LABELS[purpose]} 기준으로 살펴봤어요",
        "sentences": sentences,
        "note": closing,
    }


def _warning_sentence(
    rule_code: str,
    master: EtfMaster,
    profile: EtfProfile,
    horizon: Horizon,
    purpose: Purpose,
) -> str | None:
    """기획 정본의 "문장 조립 규칙" — {조건}이라고 하셨는데, {특성}이라서,
    {결과}. 조건이 정의 안 된 조합(예: SHORT에서 LEV)은 애초에 그 규칙이 안 뜨므로
    None을 반환할 일이 실제로는 없지만, 방어적으로 처리한다(fail-closed — 자리표시자
    문장을 지어내지 않는다)."""
    if rule_code == "W-LEV-01":
        condition = LEV_CONDITION_BY_HORIZON.get(horizon)
        if condition is None:
            return None
        return (
            f"{condition}, 이 상품은 지수의 {_format_decimal(profile.leverage)}배로 움직이고 "
            "한 번 크게 떨어지면 원래대로 돌아오기 어려워서, 오래 둘수록 지수와 차이가 "
            "벌어질 수 있어요."
        )
    if rule_code == "W-CC-01":
        condition = CC_CONDITION_BY_PURPOSE.get(purpose)
        if condition is None:
            return None
        return (
            f"{condition}, 이 상품은 매달 돈을 주는 대신 얼마까지만 오를지 미리 정해둬서, "
            "크게 오르는 구간에서는 지수만큼 따라가지 못해요."
        )
    if rule_code == "W-MIX-01":
        return (
            f"{MIX_CONDITION}, 이 상품은 이름과 달리 주식이 절반이고 나머지 절반은 "
            "채권이라서, 주식만 담은 상품과 다르게 움직여요."
        )
    if rule_code == "W-TR-01":
        frequency = DISTRIBUTION_FREQUENCY_PHRASE.get(profile.distribution, profile.distribution)
        return (
            f"{TR_CONDITION}, 이 상품도 돈을 나눠주긴 하지만 {frequency} 적은 금액이라서, "
            "생활비로 쓰기에는 부족할 수 있어요."
        )
    if rule_code == "W-FX-01":
        trait = (
            "이 상품은 환율이 오르내리는 만큼 수익도 같이 흔들려서"
            if master.market == Market.KR
            else "이 상품은 달러로 사고파는 상품이라 환율이 오르내리는 만큼 수익도 같이 흔들려서"
        )
        return f"{FX_CONDITION}, {trait}, 받는 금액이 환율 따라 왔다 갔다 해요."
    return None


def _widget(widget_type: str | None) -> dict[str, Any] | None:
    if widget_type is None:
        return None
    return {
        "type": widget_type,
        "data": {},
        "disclaimer": "이해를 돕기 위한 예시입니다. 실제 수익률은 시장 상황에 따라 다릅니다.",
    }


def _checklist(profile: EtfProfile) -> dict[str, list[dict[str, str]] | list[str]]:
    return {
        "items": [
            {"rule": rule, "label": label, "value": _checklist_value(rule, profile)}
            for rule, label in CHECKLIST_LABELS.items()
        ],
        "generalRisks": [
            "모든 투자에는 원금 손실 가능성이 있습니다.",
            "이 상품도 시장이 하락하면 함께 하락합니다.",
            "구조가 단순하다는 것이 손실 가능성이 없다는 뜻은 아닙니다.",
        ],
    }


def _checklist_value(rule: str, profile: EtfProfile) -> str:
    if rule == "W-LEV":
        if profile.leverage == Decimal("1.0"):
            return "해당 없음"
        return f"{_format_decimal(profile.leverage)}배"
    if rule == "W-CC":
        return "해당 없음" if profile.strategy != "커버드콜" else "해당"
    if rule == "W-MIX":
        return "해당 없음" if profile.strategy != "자산혼합" else "해당"
    if rule == "W-FX":
        if profile.fx_hedge == FxHedge.HEDGED:
            return "막아주는 장치 있음"
        if profile.fx_hedge == FxHedge.NOT_APPLICABLE:
            return "해당없음 (국내 상품)"
        # 미헤지 — 기획 정본의 "경고 0건" 예시엔 이 케이스가 없어서
        # 문서 톤에 맞춰 직접 작성함(정본 문구 아님, 확인 요청 대상).
        return "환율 영향 있음"
    if rule == "W-TR":
        frequency = DISTRIBUTION_FREQUENCY_PHRASE.get(profile.distribution, profile.distribution)
        return f"{frequency} 지급"
    return "확인 필요"


def _evidence_by_rule(evidence: list[Evidence]) -> dict[str, list[Evidence]]:
    grouped: dict[str, list[Evidence]] = {}
    for item in _sorted_evidence(evidence):
        if item.rule_code is not None:
            grouped.setdefault(item.rule_code, []).append(item)
    return grouped


def _sorted_evidence(evidence: list[Evidence]) -> list[Evidence]:
    return sorted(
        evidence,
        key=lambda item: (item.display_order is None, item.display_order or 0, item.id),
    )


def _evidence_item(evidence: Evidence) -> dict[str, Any]:
    return {
        "quote": evidence.quote,
        "quoteOriginal": evidence.quote_original,
        "location": evidence.location,
        "sourceType": evidence.source_type,
        "translated": evidence.translated,
    }


def _format_decimal(value: Decimal) -> str:
    return f"{value.normalize():f}".rstrip("0").rstrip(".")
