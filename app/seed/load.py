import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    ChatSuggestedQuestion,
    EtfHiddenInsight,
    EtfMaster,
    EtfNameToken,
    EtfProfile,
    Evidence,
    RuleConfig,
    RuleConfigVariant,
)
from app.seed.schemas import ChatChipsSeed, EtfSeed, RuleSeed

SEED_DIR = Path(__file__).resolve().parent
ETF_DIR = SEED_DIR / "etfs"
RULES_PATH = SEED_DIR / "rules.json"
CHAT_CHIPS_PATH = SEED_DIR / "chat_chips.json"


def main() -> None:
    with SessionLocal() as session:
        load_all(session)
        session.commit()


def load_all(session: Session) -> None:
    for seed in read_etf_seeds(ETF_DIR):
        upsert_etf(session, seed)

    if RULES_PATH.exists():
        upsert_rules(session, read_rule_seeds(RULES_PATH))

    if CHAT_CHIPS_PATH.exists():
        upsert_chat_chips(session, ChatChipsSeed.model_validate(_read_json(CHAT_CHIPS_PATH)))

    session.flush()
    validate_seed_state(session)


def read_etf_seeds(seed_dir: Path) -> list[EtfSeed]:
    if not seed_dir.exists():
        return []

    seeds: list[EtfSeed] = []
    for path in sorted(seed_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        seeds.append(EtfSeed.model_validate(_read_json(path)))
    return seeds


def read_rule_seeds(path: Path) -> list[RuleSeed]:
    data = _read_json(path)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return [RuleSeed.model_validate(item) for item in data]


def upsert_etf(session: Session, seed: EtfSeed) -> None:
    code = seed.master.code
    _upsert(session, EtfMaster, seed.master.model_dump())

    if seed.profile is not None:
        profile_data = seed.profile.model_dump()
        profile_data["code"] = code
        _upsert(session, EtfProfile, profile_data)

    session.execute(delete(EtfNameToken).where(EtfNameToken.code == code))
    session.execute(delete(Evidence).where(Evidence.code == code))

    for token in seed.tokens:
        session.add(EtfNameToken(code=code, **token.model_dump()))

    if seed.hidden_insight is not None:
        _upsert(
            session,
            EtfHiddenInsight,
            {"code": code, **seed.hidden_insight.model_dump()},
        )

    for evidence in seed.evidence:
        session.add(Evidence(code=code, **evidence.model_dump()))


def upsert_rules(session: Session, seeds: Iterable[RuleSeed]) -> None:
    for seed in seeds:
        rule_data = seed.model_dump(by_alias=False, exclude={"variants"})
        _upsert(
            session,
            RuleConfig,
            rule_data,
        )
        session.execute(delete(RuleConfigVariant).where(RuleConfigVariant.rule_code == seed.code))
        for variant in seed.variants:
            session.add(RuleConfigVariant(rule_code=seed.code, **variant.model_dump()))


def upsert_chat_chips(session: Session, seed: ChatChipsSeed) -> None:
    session.execute(delete(ChatSuggestedQuestion))
    for code, questions in seed.stage4.items():
        for seq, question in enumerate(questions, start=1):
            session.add(ChatSuggestedQuestion(code=code, stage="S4", seq=seq, question=question))
    for seq, question in enumerate(seed.stage6, start=1):
        session.add(ChatSuggestedQuestion(code=None, stage="S6", seq=seq, question=question))


def validate_seed_state(session: Session) -> None:
    master_count = session.scalar(select(func.count()).select_from(EtfMaster))
    if master_count < 8:
        raise ValueError(f"expected at least 8 ETF master rows, found {master_count}")

    display_orders = set(
        session.execute(
            select(EtfMaster.display_order).where(EtfMaster.display_order.is_not(None))
        ).scalars()
    )
    expected_orders = set(range(1, 9))
    if not expected_orders <= display_orders:
        raise ValueError(
            f"missing MVP display_order values: {sorted(expected_orders - display_orders)}"
        )

    duplicate_orders = session.execute(
        select(EtfMaster.display_order, func.count())
        .where(EtfMaster.display_order.is_not(None))
        .group_by(EtfMaster.display_order)
        .having(func.count() > 1)
    ).all()
    if duplicate_orders:
        raise ValueError(f"duplicate ETF display_order values: {duplicate_orders}")

    missing_review = session.execute(
        select(EtfProfile.code).where(EtfProfile.reviewed_at.is_(None))
    ).scalars()
    missing_review_codes = list(missing_review)
    if missing_review_codes:
        raise ValueError(
            f"profile reviewed_at is required for seed exposure: {missing_review_codes}"
        )

    profile_count = session.scalar(select(func.count()).select_from(EtfProfile))
    if profile_count not in {0, 8}:
        raise ValueError(f"expected 0 or 8 ETF profile rows, found {profile_count}")

    if profile_count == 8:
        codes_without_evidence = session.execute(
            select(EtfProfile.code)
            .outerjoin(Evidence, Evidence.code == EtfProfile.code)
            .group_by(EtfProfile.code)
            .having(func.count(Evidence.id) == 0)
        ).scalars()
        missing_evidence_codes = list(codes_without_evidence)
        if missing_evidence_codes:
            raise ValueError(f"expected evidence for every profile: {missing_evidence_codes}")

    rule_count = session.scalar(select(func.count()).select_from(RuleConfig))
    if rule_count not in {0, 12}:
        raise ValueError(f"expected 0 or 12 rule_config rows, found {rule_count}")

    chip_count = session.scalar(select(func.count()).select_from(ChatSuggestedQuestion))
    if chip_count not in {0, 27}:
        raise ValueError(f"expected 0 or 27 chat_suggested_question rows, found {chip_count}")


def _upsert(session: Session, model: type[Any], values: dict[str, Any]) -> None:
    table = model.__table__
    stmt = insert(table).values(**values)
    update_values = {
        column.name: stmt.excluded[column.name]
        for column in table.columns
        if not column.primary_key
    }
    conflict_columns = [column.name for column in table.primary_key.columns]
    session.execute(stmt.on_conflict_do_update(index_elements=conflict_columns, set_=update_values))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
