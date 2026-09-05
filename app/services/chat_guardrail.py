"""Deterministic, LLM-free policy checks (spec §3, §9).

Two independent checks live here:
- `classify_refusal` — pre-LLM router. Catches the most literal phrasings of
  the four banned intents (추천/예측/타이밍/수익계산) so those cases never
  reach the model at all. Deliberately conservative: anything not an obvious
  match falls through to the LLM, which still carries the same refusal
  instructions in its system prompt as a backstop.
- `find_banned_phrase` — post-LLM safety net. Scans the generated answer for
  grading/ranking language the model was told never to produce.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RefusalMatch:
    category: str
    message: str
    action: str


_REFUSAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "RECOMMEND": (
        r"추천",
        r"뭘\s*사야",
        r"뭐.{0,3}사야",
        r"골라\s*주세요",
        r"제일\s*나은",
        r"뭐가\s*나아요",
        r"뭐가\s*좋아요",
    ),
    "PREDICT": (r"오를까", r"내릴까", r"전망이", r"어떻게\s*될까요", r"어떻게\s*될\s*것"),
    "TIMING": (
        r"지금\s*사도",
        r"지금이\s*저점",
        r"지금이\s*고점",
        r"언제\s*팔아야",
        r"매수\s*타이밍",
        r"매도\s*타이밍",
    ),
    "CALC": (
        r"얼마.{0,3}벌어요",
        r"얼마.{0,3}나와요",
        r"얼마.{0,3}받아요",
        r"넣으면\s*얼마",
        r"얼마\s*넣어야",
    ),
}

_REFUSAL_RESPONSES: dict[str, RefusalMatch] = {
    "RECOMMEND": RefusalMatch(
        category="RECOMMEND",
        message=(
            "저는 특정 상품을 추천하지 않습니다.\n\n"
            "어떤 상품이 더 낫다는 판단은 사람마다 목적이 달라서 대신 내려드릴 수 없어요.\n\n"
            "대신 관심 있는 상품을 선택하시면, 그 상품의 구조와 회원님 조건에서 "
            "주의할 점을 알려드릴 수 있습니다."
        ),
        action="VIEW_PRODUCT_LIST",
    ),
    "PREDICT": RefusalMatch(
        category="PREDICT",
        message=(
            "앞으로 가격이 어떻게 될지는 말씀드릴 수 없습니다.\n\n"
            "저는 시장을 예측하지 않아요.\n\n"
            "대신 이 상품이 어떤 구조로 움직이는지는 설명해드릴 수 있습니다."
        ),
        action="NONE",
    ),
    "TIMING": RefusalMatch(
        category="TIMING",
        message=(
            "언제 사고팔지는 말씀드릴 수 없습니다.\n\n"
            "투자 시점 판단은 회원님이 하셔야 하는 부분이에요.\n\n"
            "다만 이 상품의 구조와 회원님이 선택한 보유 기간이 어떻게 맞물리는지는 "
            "확인해드릴 수 있습니다."
        ),
        action="CHANGE_CONDITIONS",
    ),
    "CALC": RefusalMatch(
        category="CALC",
        message=(
            "얼마를 벌 수 있는지는 계산해드릴 수 없습니다.\n\n"
            "수익은 시장 상황과 운용 결과에 따라 달라지기 때문이에요.\n\n"
            "다만 현재 데이터에 해당 상품의 분배 구조가 있다면 지급 주기와 구조는 "
            "설명해드릴 수 있습니다."
        ),
        action="NONE",
    ),
}


def classify_refusal(message: str) -> RefusalMatch | None:
    for category, patterns in _REFUSAL_PATTERNS.items():
        if any(re.search(pattern, message) for pattern in patterns):
            return _REFUSAL_RESPONSES[category]
    return None


_BANNED_PHRASE_PATTERNS = (
    r"위험도\s*\d+\s*(등급|점)",
    r"위험\s*등급",
    r"\d+\s*/\s*10",
    r"위험한\s*ETF\s*TOP",
    r"더\s*(좋습니다|낫습니다)",
    r"추천합니다",
    r"추천드립니다",
    r"이\s*상품을\s*추천",
)

NEUTRAL_OVERRIDE_MESSAGE = (
    "그 부분은 등급이나 우열로 답변드릴 수 없어요.\n\n"
    "화면에 표시된 진단 결과와 구조 차이를 직접 확인해보시는 걸 권해드립니다."
)


def find_banned_phrase(message: str) -> str | None:
    for pattern in _BANNED_PHRASE_PATTERNS:
        match = re.search(pattern, message)
        if match:
            return match.group(0)
    return None
