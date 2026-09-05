from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MasterSeed(BaseModel):
    code: str
    isin: str | None = None
    name: str
    market: str
    manager: str | None = None
    listed_at: date | None = None
    exchange: str | None = None
    source: str
    display_order: int | None = None


class ProfileSeed(BaseModel):
    base_index: str
    replication: str
    leverage: Decimal
    daily_rebalancing: bool = False
    is_active: bool = False
    strategy: str
    distribution: str
    distribution_yield: Decimal | None = None
    target_year: int | None = None
    total_expense: Decimal
    fx_hedge: str
    counterparty_risk: bool = False
    counterparty: str | None = None
    main_assets: list[str] | None = None
    is_complex_product: bool = False
    extracted_by: str
    extraction_run_id: str | None = None
    reviewed_at: datetime | None = None


class EvidenceSeed(BaseModel):
    field: str | None = None
    rule_code: str | None = None
    quote: str
    quote_original: str | None = None
    location: str
    source_type: str
    translated: bool = False
    display_order: int | None = None


class NameTokenSeed(BaseModel):
    seq: int
    text: str | None = None
    absent: str | None = None
    translation: str


class HiddenInsightSeed(BaseModel):
    summary: str
    body: str


class EtfSeed(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    master: MasterSeed
    profile: ProfileSeed | None = None
    tokens: list[NameTokenSeed] = Field(default_factory=list)
    hidden_insight: HiddenInsightSeed | None = Field(default=None, alias="hiddenInsight")
    evidence: list[EvidenceSeed] = Field(default_factory=list)


class RuleSeed(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    level: str
    priority: int | None = None
    category: str | None = None
    summary: str
    title: str | None = None
    body: str
    purpose_addon: str | None = Field(default=None, alias="purposeAddon")
    widget_type: str | None = Field(default=None, alias="widgetType")
    variants: list["RuleVariantSeed"] = Field(default_factory=list)


class RuleVariantSeed(BaseModel):
    purpose: str
    summary: str
    title: str | None = None
    body: str


class ChatChipsSeed(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stage4: dict[str, list[str]] = Field(alias="S4")
    stage6: list[str] = Field(alias="S6")
