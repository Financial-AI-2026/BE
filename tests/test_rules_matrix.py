from decimal import Decimal
from itertools import product

from app.domain.enums import Distribution, FxHedge, Horizon, Market, Purpose, Replication, Strategy
from app.domain.rules import EtfRuleProfile, evaluate_rule_codes

PROFILES = {
    "418660": EtfRuleProfile(
        code="418660",
        market=Market.KR,
        replication=Replication.SYNTHETIC,
        fx_hedge=FxHedge.UNHEDGED,
        leverage=Decimal("2.0"),
        strategy=Strategy.LEVERAGE,
        distribution=Distribution.ANNUAL,
        distribution_yield=Decimal("0.8"),
    ),
    "441680": EtfRuleProfile(
        code="441680",
        market=Market.KR,
        replication=Replication.SYNTHETIC,
        fx_hedge=FxHedge.UNHEDGED,
        leverage=Decimal("1.0"),
        strategy=Strategy.COVERED_CALL,
        distribution=Distribution.MONTHLY,
        distribution_yield=Decimal("12.3"),
    ),
    "435420": EtfRuleProfile(
        code="435420",
        market=Market.KR,
        replication=Replication.PHYSICAL,
        fx_hedge=FxHedge.UNHEDGED,
        leverage=Decimal("1.0"),
        strategy=Strategy.MIXED_ASSET,
        distribution=Distribution.QUARTERLY,
        distribution_yield=Decimal("1.5"),
    ),
    "133690": EtfRuleProfile(
        code="133690",
        market=Market.KR,
        replication=Replication.PHYSICAL,
        fx_hedge=FxHedge.UNHEDGED,
        leverage=Decimal("1.0"),
        strategy=Strategy.INDEX,
        distribution=Distribution.QUARTERLY,
        distribution_yield=Decimal("0.5"),
    ),
    "448290": EtfRuleProfile(
        code="448290",
        market=Market.KR,
        replication=Replication.PHYSICAL,
        fx_hedge=FxHedge.HEDGED,
        leverage=Decimal("1.0"),
        strategy=Strategy.INDEX,
        distribution=Distribution.QUARTERLY,
        distribution_yield=Decimal("1.0"),
    ),
    "102110": EtfRuleProfile(
        code="102110",
        market=Market.KR,
        replication=Replication.PHYSICAL,
        fx_hedge=FxHedge.NOT_APPLICABLE,
        leverage=Decimal("1.0"),
        strategy=Strategy.INDEX,
        distribution=Distribution.QUARTERLY,
        distribution_yield=Decimal("2.0"),
    ),
    "TQQQ": EtfRuleProfile(
        code="TQQQ",
        market=Market.US,
        replication=Replication.SYNTHETIC,
        fx_hedge=FxHedge.UNHEDGED,
        leverage=Decimal("3.0"),
        strategy=Strategy.LEVERAGE,
        distribution=Distribution.QUARTERLY,
        distribution_yield=Decimal("0.5"),
    ),
    "QYLD": EtfRuleProfile(
        code="QYLD",
        market=Market.US,
        replication=Replication.PHYSICAL,
        fx_hedge=FxHedge.UNHEDGED,
        leverage=Decimal("1.0"),
        strategy=Strategy.COVERED_CALL,
        distribution=Distribution.MONTHLY,
        distribution_yield=Decimal("11.5"),
    ),
}

HORIZONS = [Horizon.SHORT, Horizon.MID, Horizon.LONG, Horizon.UNKNOWN]
PURPOSES = [Purpose.CAPITAL_GAIN, Purpose.INCOME, Purpose.GROWTH]

EXPECTED_WARNINGS = {
    "418660": {
        Horizon.SHORT: ((), ("W-TR-01", "W-FX-01"), ()),
        Horizon.MID: (("W-LEV-01",), ("W-LEV-01", "W-TR-01", "W-FX-01"), ("W-LEV-01",)),
        Horizon.LONG: (("W-LEV-01",), ("W-LEV-01", "W-TR-01", "W-FX-01"), ("W-LEV-01",)),
        Horizon.UNKNOWN: (
            ("W-LEV-01",),
            ("W-LEV-01", "W-TR-01", "W-FX-01"),
            ("W-LEV-01",),
        ),
    },
    "441680": {horizon: (("W-CC-01",), ("W-FX-01",), ("W-CC-01",)) for horizon in HORIZONS},
    "435420": {horizon: (("W-MIX-01",), ("W-TR-01", "W-FX-01"), ()) for horizon in HORIZONS},
    "133690": {horizon: ((), ("W-TR-01", "W-FX-01"), ()) for horizon in HORIZONS},
    "448290": {horizon: ((), ("W-TR-01",), ()) for horizon in HORIZONS},
    "102110": {horizon: ((), ("W-TR-01",), ()) for horizon in HORIZONS},
    "TQQQ": {
        Horizon.SHORT: ((), ("W-TR-01", "W-FX-01"), ()),
        Horizon.MID: (("W-LEV-01",), ("W-LEV-01", "W-TR-01", "W-FX-01"), ("W-LEV-01",)),
        Horizon.LONG: (("W-LEV-01",), ("W-LEV-01", "W-TR-01", "W-FX-01"), ("W-LEV-01",)),
        Horizon.UNKNOWN: (
            ("W-LEV-01",),
            ("W-LEV-01", "W-TR-01", "W-FX-01"),
            ("W-LEV-01",),
        ),
    },
    "QYLD": {horizon: (("W-CC-01",), ("W-FX-01",), ("W-CC-01",)) for horizon in HORIZONS},
}


def test_warning_matrix_matches_documented_96_cells() -> None:
    for code, profile in PROFILES.items():
        for horizon, purpose in product(HORIZONS, PURPOSES):
            purpose_index = PURPOSES.index(purpose)
            expected = EXPECTED_WARNINGS[code][horizon][purpose_index]

            result = evaluate_rule_codes(profile, horizon, purpose)

            assert result.warnings == expected


def test_warning_count_distribution_matches_documented_matrix() -> None:
    distribution = {0: 0, 1: 0, 2: 0, 3: 0}
    for profile in PROFILES.values():
        for horizon, purpose in product(HORIZONS, PURPOSES):
            result = evaluate_rule_codes(profile, horizon, purpose)
            distribution[len(result.warnings)] += 1

    assert distribution == {0: 32, 1: 48, 2: 10, 3: 6}


def test_fx_warning_and_fx_info_are_mutually_exclusive() -> None:
    for profile in PROFILES.values():
        for horizon, purpose in product(HORIZONS, PURPOSES):
            result = evaluate_rule_codes(profile, horizon, purpose)

            assert not ({"W-FX-01"} <= set(result.warnings) and {"I-FX-01"} <= set(result.infos))


def test_three_warning_cells_are_only_leveraged_income_mid_long_unknown() -> None:
    cells = []
    for code, profile in PROFILES.items():
        for horizon, purpose in product(HORIZONS, PURPOSES):
            result = evaluate_rule_codes(profile, horizon, purpose)
            if len(result.warnings) == 3:
                cells.append((code, horizon, purpose))

    assert cells == [
        ("418660", Horizon.MID, Purpose.INCOME),
        ("418660", Horizon.LONG, Purpose.INCOME),
        ("418660", Horizon.UNKNOWN, Purpose.INCOME),
        ("TQQQ", Horizon.MID, Purpose.INCOME),
        ("TQQQ", Horizon.LONG, Purpose.INCOME),
        ("TQQQ", Horizon.UNKNOWN, Purpose.INCOME),
    ]


def test_covered_call_domestic_and_us_warning_matrices_match() -> None:
    for horizon, purpose in product(HORIZONS, PURPOSES):
        domestic = evaluate_rule_codes(PROFILES["441680"], horizon, purpose)
        overseas = evaluate_rule_codes(PROFILES["QYLD"], horizon, purpose)

        assert domestic.warnings == overseas.warnings
