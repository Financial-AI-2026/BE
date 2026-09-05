from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import FundNature, Horizon, Purpose


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    stage: Literal["S4", "S6"]
    productCode: str
    horizon: Horizon
    purpose: Purpose
    fundNature: FundNature
    compareProductCode: str | None = None
    previousProductCode: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    message: str
    refusal: bool
    action: Literal["NONE", "CHANGE_CONDITIONS", "VIEW_PRODUCT_LIST", "RETRY"]


class SuggestedQuestionsResponse(BaseModel):
    suggestedQuestions: list[str]
