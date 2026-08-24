"""Tier1 + Tier2 추출용 OpenAI Structured Outputs 스키마."""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

VALUE_FIELDS = [
    "종목명",
    "기초지수",
    "비교지수",
    "레버리지배율",
    "복제방식",
    "환헤지여부",
    "전략유형",
    "분배정책",
    "총보수",
    "액티브여부",
    "목표시점",
    "고난도금융투자상품여부",
    "거래상대방위험",
    "거래상대방",
    "일일리밸런싱여부",
    "주요투자자산",
]

NUMERIC_FIELDS = {"레버리지배율", "총보수", "목표시점"}
BOOLEAN_FIELDS = {
    "액티브여부",
    "고난도금융투자상품여부",
    "거래상대방위험",
    "일일리밸런싱여부",
}
ARRAY_FIELDS = {"거래상대방", "주요투자자산"}


def load_enum_definitions() -> dict[str, list[str]]:
    gt = json.loads((ROOT / "ground_truth.json").read_text(encoding="utf-8"))
    return gt["enum_definitions"]


def build_schema() -> dict:
    enums = load_enum_definitions()

    value_props = {}
    for field in VALUE_FIELDS:
        if field in NUMERIC_FIELDS:
            value_props[field] = {"type": ["number", "null"]}
        elif field in BOOLEAN_FIELDS:
            value_props[field] = {"type": ["boolean", "null"]}
        elif field in ARRAY_FIELDS:
            value_props[field] = {
                "type": ["array", "null"],
                "items": {"type": "string"},
            }
        elif field in enums:
            value_props[field] = {"type": ["string", "null"], "enum": enums[field] + [None]}
        else:
            value_props[field] = {"type": ["string", "null"]}

    evidence_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "원문": {
                "type": ["string", "null"],
                "description": "값의 근거가 된 투자설명서 원문 문장. 값이 null이면 이것도 null.",
            },
            "페이지": {
                "type": ["integer", "null"],
                "description": "근거 문장이 속한 [PAGE n] 마커의 n.",
            },
            "조항": {
                "type": ["string", "null"],
                "description": "식별 가능하면 '제2부 9' 같은 부/번호. 모르면 null.",
            },
        },
        "required": ["원문", "페이지", "조항"],
    }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "값": {
                "type": "object",
                "additionalProperties": False,
                "properties": value_props,
                "required": VALUE_FIELDS,
            },
            "근거": {
                "type": "object",
                "additionalProperties": False,
                "properties": {field: evidence_item for field in VALUE_FIELDS},
                "required": VALUE_FIELDS,
            },
        },
        "required": ["값", "근거"],
    }


if __name__ == "__main__":
    print(json.dumps(build_schema(), ensure_ascii=False, indent=2))
