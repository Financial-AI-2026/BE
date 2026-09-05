from enum import StrEnum


class Horizon(StrEnum):
    SHORT = "SHORT"
    MID = "MID"
    LONG = "LONG"
    UNKNOWN = "UNKNOWN"


class Purpose(StrEnum):
    CAPITAL_GAIN = "CAPITAL_GAIN"
    INCOME = "INCOME"
    GROWTH = "GROWTH"


class FundNature(StrEnum):
    SPARE = "SPARE"
    PURPOSE = "PURPOSE"


class Replication(StrEnum):
    PHYSICAL = "실물"
    SYNTHETIC = "합성"


class FxHedge(StrEnum):
    HEDGED = "헤지"
    UNHEDGED = "미헤지"
    NOT_APPLICABLE = "해당없음"


class Strategy(StrEnum):
    INDEX = "지수추종"
    LEVERAGE = "레버리지"
    INVERSE = "인버스"
    COVERED_CALL = "커버드콜"
    MIXED_ASSET = "자산혼합"
    TARGET_DATE = "타겟데이트"
    ACTIVE = "액티브"
    OTHER = "기타"


class Distribution(StrEnum):
    NONE = "무분배"
    MONTHLY = "월분배"
    QUARTERLY = "분기분배"
    SEMIANNUAL = "반기분배"
    ANNUAL = "연분배"


class Market(StrEnum):
    KR = "KR"
    US = "US"
