from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import Distribution, FxHedge, Horizon, Market, Purpose, Replication, Strategy

WARNING_PRIORITIES = {
    "W-LEV-01": 1,
    "W-CC-01": 2,
    "W-MIX-01": 2,
    "W-TR-01": 3,
    "W-FX-01": 3,
}

# 동순위 내 표시 순서 (2026-09-04 기획 확정: TR을 FX보다
# 먼저 표시). CC/MIX는 동시에 발동하는 경우가 없어(strategy가 배타적) 둘 사이 순서는
# 실질적으로 의미가 없다.
WARNING_TIE_BREAK_ORDER = ["W-LEV-01", "W-CC-01", "W-MIX-01", "W-TR-01", "W-FX-01"]


@dataclass(frozen=True)
class EtfRuleProfile:
    code: str
    market: Market
    replication: Replication
    leverage: Decimal
    strategy: Strategy
    distribution: Distribution
    distribution_yield: Decimal | None
    fx_hedge: FxHedge


@dataclass(frozen=True)
class RuleCodeResult:
    warnings: tuple[str, ...]
    infos: tuple[str, ...]
    ok: str | None


def evaluate_rule_codes(
    profile: EtfRuleProfile,
    horizon: Horizon,
    purpose: Purpose,
) -> RuleCodeResult:
    warnings = _warning_codes(profile, horizon, purpose)
    infos = _info_codes(profile, purpose)

    return RuleCodeResult(
        warnings=tuple(
            sorted(
                warnings,
                key=lambda code: (WARNING_PRIORITIES[code], WARNING_TIE_BREAK_ORDER.index(code)),
            )
        ),
        infos=tuple(infos),
        ok="OK-01" if not warnings else None,
    )


def _warning_codes(
    profile: EtfRuleProfile,
    horizon: Horizon,
    purpose: Purpose,
) -> list[str]:
    warnings: list[str] = []

    if profile.leverage != Decimal("1.0") and horizon in {
        Horizon.MID,
        Horizon.LONG,
        Horizon.UNKNOWN,
    }:
        warnings.append("W-LEV-01")

    if profile.strategy == Strategy.COVERED_CALL and purpose in {
        Purpose.CAPITAL_GAIN,
        Purpose.GROWTH,
    }:
        warnings.append("W-CC-01")

    if profile.strategy == Strategy.MIXED_ASSET and purpose == Purpose.CAPITAL_GAIN:
        warnings.append("W-MIX-01")

    if _distribution_yield_below_income_threshold(profile) and purpose == Purpose.INCOME:
        warnings.append("W-TR-01")

    if profile.fx_hedge == FxHedge.UNHEDGED and purpose == Purpose.INCOME:
        warnings.append("W-FX-01")

    return warnings


def _info_codes(profile: EtfRuleProfile, purpose: Purpose) -> list[str]:
    infos: list[str] = []

    if profile.market == Market.US:
        infos.append("I-OVS-01")

    if profile.replication == Replication.SYNTHETIC:
        infos.append("I-SYN-01")

    if profile.fx_hedge == FxHedge.UNHEDGED and purpose != Purpose.INCOME:
        infos.append("I-FX-01")

    if profile.fx_hedge == FxHedge.HEDGED:
        infos.append("I-FXH-01")

    if profile.distribution == Distribution.MONTHLY:
        infos.append("I-DIV-01")

    if profile.strategy == Strategy.MIXED_ASSET:
        infos.append("I-MIX-01")

    return infos


def _distribution_yield_below_income_threshold(profile: EtfRuleProfile) -> bool:
    distribution_is_not_regular = profile.distribution not in {
        Distribution.MONTHLY,
        Distribution.QUARTERLY,
    }

    # NULL means "not confirmed", not "high enough". Income users should see the warning.
    if profile.distribution_yield is None:
        yield_below_threshold = True
    else:
        yield_below_threshold = profile.distribution_yield < Decimal("5.0")

    return distribution_is_not_regular or yield_below_threshold
