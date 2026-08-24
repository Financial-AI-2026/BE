"""Tier1 추출용 OpenAI Structured Outputs 스키마.

enum 허용값은 ground_truth.json의 enum_definitions를 그대로 가져다 쓴다.
여기 따로 다시 쓰면 둘이 어긋날 수 있다 — 실제로 값을 바꿀 곳은 한 곳(ground_truth.json)
이어야 한다.
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 지수 필드를 기초/비교로 분리하기로 한 결정 반영. ground_truth.json 참조.
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
]

NUMERIC_FIELDS = {"레버리지배율", "총보수"}


def load_enum_definitions() -> dict[str, list[str]]:
    gt = json.loads((ROOT / "ground_truth.json").read_text(encoding="utf-8"))
    return gt["enum_definitions"]


def build_schema() -> dict:
    enums = load_enum_definitions()

    value_props = {}
    for f in VALUE_FIELDS:
        if f in NUMERIC_FIELDS:
            value_props[f] = {"type": ["number", "null"]}
        elif f in enums:
            value_props[f] = {"type": ["string", "null"], "enum": enums[f] + [None]}
        else:
            value_props[f] = {"type": ["string", "null"]}

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
                "properties": {f: evidence_item for f in VALUE_FIELDS},
                "required": VALUE_FIELDS,
            },
        },
        "required": ["값", "근거"],
    }


if __name__ == "__main__":
    print(json.dumps(build_schema(), ensure_ascii=False, indent=2))
