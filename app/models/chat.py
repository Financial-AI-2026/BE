from sqlalchemy import CheckConstraint, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChatSuggestedQuestion(Base):
    __tablename__ = "chat_suggested_question"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(ForeignKey("etf_master.code", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column()
    seq: Mapped[int] = mapped_column()
    question: Mapped[str] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "(stage = 'S4' AND code IS NOT NULL) OR (stage = 'S6' AND code IS NULL)",
            name="chat_suggested_question_stage_code_check",
        ),
        Index(
            "chat_suggested_question_product_unique",
            "code",
            "seq",
            unique=True,
            postgresql_where=text("code IS NOT NULL"),
        ),
        Index(
            "chat_suggested_question_common_unique",
            "stage",
            "seq",
            unique=True,
            postgresql_where=text("code IS NULL"),
        ),
    )
