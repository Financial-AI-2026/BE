from typing import Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.schemas.chat import ChatRequest, ChatResponse, SuggestedQuestionsResponse
from app.db.session import get_db
from app.services import chat_chips
from app.services.chat_service import handle_chat
from app.services.etfs import EtfNotFoundError

router = APIRouter(prefix="/v1/chat", tags=["chat"])
DB_DEPENDENCY = Depends(get_db)


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = DB_DEPENDENCY):
    try:
        return handle_chat(db, request)
    except EtfNotFoundError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": "ETF_NOT_FOUND",
                    "message": "지원하지 않는 종목입니다.",
                    "field": "productCode",
                }
            },
        )


@router.get("/suggested-questions", response_model=SuggestedQuestionsResponse)
def get_suggested_questions(
    stage: Literal["S4", "S6"],
    code: str | None = None,
    db: Session = DB_DEPENDENCY,
):
    questions = chat_chips.suggested_questions(db, stage, code or "")
    return SuggestedQuestionsResponse(suggestedQuestions=questions)
