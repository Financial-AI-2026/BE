from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Distribution, FxHedge, Market, Replication, Strategy

SourceType = Literal["KR_PROSPECTUS", "US_SUMMARY_PROSPECTUS", "ISSUER_DISCLOSURE"]

TIER1_FIELDS = (
    "name",
    "baseIndex",
    "replication",
    "leverage",
    "strategy",
    "distribution",
    "totalExpense",
    "fxHedge",
)

# 기본 원칙은 "근거 = 투자설명서 원문"이지만, 운용
# 실적에 따라 달라지는 값은 애초에 투자설명서에 실리지 않는 게 정상이라 예외를 둔다.
# 이 두 필드에 한해서만 sourceType="ISSUER_DISCLOSURE"(운용사의 법정 공시 의무 영역 —
# 마케팅/홍보 문구가 아니라 지급기준일·금액 등을 법적으로 공시하는 자료)를 근거로 인정한다.
# 다른 Tier1 필드(baseIndex/replication/leverage/strategy/fxHedge)는 여전히 투자설명서
# 원문만 근거로 인정한다 — fail-closed 원칙이 흔들리지 않도록 이 예외의 범위를 좁게 못박는다.
PERFORMANCE_DEPENDENT_FIELDS = ("distribution", "totalExpense")


class EvidenceItem(BaseModel):
    field: str
    quote: str
    quoteOriginal: str | None = None
    location: str
    sourceType: SourceType = "KR_PROSPECTUS"
    translated: bool = False


class ProductProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    code: str
    isin: str | None = None
    market: Market
    baseIndex: str
    replication: Replication
    leverage: float
    dailyRebalancing: bool | None = None
    isActive: bool | None = None
    strategy: Strategy
    distribution: Distribution
    distributionYield: float | None = None
    targetYear: int | None = None
    totalExpense: float
    fxHedge: FxHedge
    counterpartyRisk: bool | None = None
    counterparty: str | None = None
    mainAssets: list[str] = Field(default_factory=list)
    isComplexProduct: bool | None = None
    evidence: list[EvidenceItem]


class SourceMetadata(BaseModel):
    filename: str
    sha256: str | None = None
    collectedAt: str | None = None
    sourceUrl: str | None = None


class ValidationIssue(BaseModel):
    field: str | None
    code: str
    message: str


class ExtractionResult(BaseModel):
    code: str
    profile: ProductProfile
    validationPassed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    source: SourceMetadata | None = None
    model: str
    promptVersion: str
    promptInput: str = "C2_wide"

