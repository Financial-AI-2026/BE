import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ExtractionRun(Base):
    __tablename__ = "extraction_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    model: Mapped[str | None] = mapped_column()
    prompt_version: Mapped[str | None] = mapped_column()
    input_condition: Mapped[str | None] = mapped_column()
    source_path: Mapped[str | None] = mapped_column()
    status: Mapped[str] = mapped_column()
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class EtfMaster(Base):
    __tablename__ = "etf_master"

    code: Mapped[str] = mapped_column(primary_key=True)
    isin: Mapped[str | None] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column()
    market: Mapped[str] = mapped_column()
    manager: Mapped[str | None] = mapped_column()
    listed_at: Mapped[date | None] = mapped_column()
    exchange: Mapped[str | None] = mapped_column()
    source: Mapped[str] = mapped_column()
    display_order: Mapped[int | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=text("now()")
    )

    profile: Mapped["EtfProfile | None"] = relationship(
        back_populates="master",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="master",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    name_tokens: Mapped[list["EtfNameToken"]] = relationship(
        back_populates="master",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EtfNameToken.seq",
    )
    hidden_insight: Mapped["EtfHiddenInsight | None"] = relationship(
        back_populates="master",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index(
            "etf_master_display_order_unique",
            "display_order",
            unique=True,
            postgresql_where=text("display_order IS NOT NULL"),
        ),
    )


class EtfProfile(Base):
    __tablename__ = "etf_profile"

    code: Mapped[str] = mapped_column(
        ForeignKey("etf_master.code", ondelete="CASCADE"),
        primary_key=True,
    )
    base_index: Mapped[str] = mapped_column()
    replication: Mapped[str] = mapped_column()
    leverage: Mapped[Decimal] = mapped_column()
    daily_rebalancing: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=False)
    strategy: Mapped[str] = mapped_column()
    distribution: Mapped[str] = mapped_column()
    distribution_yield: Mapped[Decimal | None] = mapped_column()
    target_year: Mapped[int | None] = mapped_column()
    total_expense: Mapped[Decimal] = mapped_column()
    fx_hedge: Mapped[str] = mapped_column()
    counterparty_risk: Mapped[bool] = mapped_column(default=False)
    counterparty: Mapped[str | None] = mapped_column()
    main_assets: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    is_complex_product: Mapped[bool] = mapped_column(default=False)
    extracted_by: Mapped[str] = mapped_column()
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("extraction_run.id"),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=text("now()")
    )

    master: Mapped[EtfMaster] = relationship(back_populates="profile")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(ForeignKey("etf_master.code", ondelete="CASCADE"))
    field: Mapped[str | None] = mapped_column()
    rule_code: Mapped[str | None] = mapped_column()
    quote: Mapped[str] = mapped_column()
    quote_original: Mapped[str | None] = mapped_column()
    location: Mapped[str] = mapped_column()
    source_type: Mapped[str] = mapped_column()
    translated: Mapped[bool] = mapped_column(default=False)
    display_order: Mapped[int | None] = mapped_column()

    master: Mapped[EtfMaster] = relationship(back_populates="evidence")


class EtfNameToken(Base):
    __tablename__ = "etf_name_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(ForeignKey("etf_master.code", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column()
    text: Mapped[str | None] = mapped_column()
    absent: Mapped[str | None] = mapped_column()
    translation: Mapped[str] = mapped_column()

    master: Mapped[EtfMaster] = relationship(back_populates="name_tokens")


class EtfHiddenInsight(Base):
    __tablename__ = "etf_hidden_insight"

    code: Mapped[str] = mapped_column(
        ForeignKey("etf_master.code", ondelete="CASCADE"),
        primary_key=True,
    )
    summary: Mapped[str] = mapped_column()
    body: Mapped[str] = mapped_column()

    master: Mapped[EtfMaster] = relationship(back_populates="hidden_insight")


class RuleConfig(Base):
    __tablename__ = "rule_config"

    code: Mapped[str] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column()
    priority: Mapped[int | None] = mapped_column()
    category: Mapped[str | None] = mapped_column()
    summary: Mapped[str] = mapped_column()
    title: Mapped[str | None] = mapped_column()
    body: Mapped[str] = mapped_column()
    purpose_addon: Mapped[str | None] = mapped_column()
    widget_type: Mapped[str | None] = mapped_column()

    variants: Mapped[list["RuleConfigVariant"]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RuleConfigVariant(Base):
    __tablename__ = "rule_config_variant"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(
        ForeignKey("rule_config.code", ondelete="CASCADE"),
    )
    purpose: Mapped[str] = mapped_column()
    summary: Mapped[str] = mapped_column()
    title: Mapped[str | None] = mapped_column()
    body: Mapped[str] = mapped_column()

    rule: Mapped[RuleConfig] = relationship(back_populates="variants")
