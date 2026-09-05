from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatSuggestedQuestion


def suggested_questions(session: Session, stage: str, code: str) -> list[str]:
    stmt = (
        select(ChatSuggestedQuestion.question)
        .where(ChatSuggestedQuestion.stage == stage)
        .where(ChatSuggestedQuestion.code == (code if stage == "S4" else None))
        .order_by(ChatSuggestedQuestion.seq)
    )
    return list(session.scalars(stmt))
