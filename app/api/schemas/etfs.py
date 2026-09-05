from typing import Any, Literal

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class EtfListItem(BaseModel):
    code: str
    name: str
    manager: str | None
    market: Literal["KR", "US"]
    ready: bool
    displayOrder: int | None


class EtfListResponse(BaseModel):
    domestic: list[EtfListItem]
    overseas: list[EtfListItem]


class NameTokenResponse(BaseModel):
    seq: int
    text: str | None
    absent: str | None = None
    translation: str


class HiddenInsightResponse(BaseModel):
    summary: str
    body: str


class StructureItemResponse(BaseModel):
    label: str
    question: str
    value: str
    sub: str | None = None


class EvidenceResponse(BaseModel):
    quote: str
    quoteOriginal: str | None = None
    location: str
    sourceType: str
    translated: bool


class LoadingStatsResponse(BaseModel):
    pages: int | None = None
    chars: int | None = None


class EtfDetailResponse(BaseModel):
    code: str
    name: str
    market: Literal["KR", "US"]
    tokens: list[NameTokenResponse]
    hiddenInsight: HiddenInsightResponse | None
    structure: dict[str, StructureItemResponse]
    evidence: list[EvidenceResponse]
    loadingStats: LoadingStatsResponse | None


class BannerResponse(BaseModel):
    level: Literal["none", "single", "multiple"]
    text: str
    subtext: str
    sentences: list[str]
    note: str | None


class WidgetResponse(BaseModel):
    type: str
    data: dict[str, Any]
    disclaimer: str


class WarningCardResponse(BaseModel):
    code: str
    priority: int | None
    category: str | None
    summary: str
    title: str | None
    body: str
    purposeAddon: str | None
    widget: WidgetResponse | None
    evidence: list[EvidenceResponse]


class InfoCardResponse(BaseModel):
    code: str
    summary: str
    body: str
    evidence: list[EvidenceResponse]


class ChecklistItemResponse(BaseModel):
    rule: str
    label: str
    value: str


class ChecklistResponse(BaseModel):
    items: list[ChecklistItemResponse]
    generalRisks: list[str]


class DiagnosisResponse(BaseModel):
    code: str
    name: str
    banner: BannerResponse
    warnings: list[WarningCardResponse]
    warningsVisible: int
    infos: list[InfoCardResponse]
    checklist: ChecklistResponse | None


class BatchDiagnosisItemResponse(BaseModel):
    code: str
    name: str
    warningCount: int
    warningCodes: list[str] | None = None


class BatchDiagnosisResponse(BaseModel):
    matched: list[BatchDiagnosisItemResponse]
    unmatched: list[BatchDiagnosisItemResponse]
    riskSummary: dict[str, int]


class EtfContextResponse(BaseModel):
    code: str
    name: str
    market: Literal["KR", "US"]
    structure: dict[str, StructureItemResponse]
    diagnosis: DiagnosisResponse
    evidence: list[EvidenceResponse]
