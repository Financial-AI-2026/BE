import json
from typing import Any

from app.domain.enums import FundNature, Horizon, Purpose

HORIZON_LABELS = {
    Horizon.SHORT: "1년 안에 팔 계획",
    Horizon.MID: "1~5년 보유 계획",
    Horizon.LONG: "5년 이상 보유 계획",
    Horizon.UNKNOWN: "보유 기간 미정",
}
PURPOSE_LABELS = {
    Purpose.CAPITAL_GAIN: "시세차익",
    Purpose.INCOME: "매달 현금 흐름",
    Purpose.GROWTH: "자산 성장",
}
FUND_NATURE_LABELS = {
    FundNature.PURPOSE: "나중에 꼭 써야 하는 목적자금",
    FundNature.SPARE: "당장 안 써도 되는 여윳돈",
}

SYSTEM_INSTRUCTIONS = """
당신은 'ETF 위험구조 진단 서비스'의 챗봇입니다.
사용자가 화면에서 이미 조회 중인 ETF에 대한 질문에 답합니다.

절대 원칙:
1. 답변 근거는 아래로 전달되는 데이터(종목 구조, 판정 결과, 근거 원문, 사용자 조건)로만 한정합니다.
   근거가 없으면 "확인한 자료에 없어서 답변드리기 어렵다"고 답하세요. 추측하지 마세요.
2. 투자설명서 원문을 인용할 때는 전달된 evidence의 quote를 그대로 사용하고, 새로 지어내지 않습니다.
3. 상품을 추천하거나("이 상품이 낫다", "이걸 사세요"), 가격을 예측하거나, 매매 시점을 알려주거나,
   수익 금액을 계산해주지 않습니다. 이런 질문에는 정중히 거절하고 대신 무엇을 도와줄 수 있는지
   제시하세요. 이때 refusal=true로 응답하세요.
4. 위험을 등급·점수·순위로 환산하지 않습니다 ("위험도 3등급", "위험한 ETF TOP 3" 금지).
5. 상품을 비교하거나 여러 상품을 나열할 때는 구조 차이만 설명하고 어느 쪽이 더 낫다고 말하지
   않습니다.
6. "지원 종목 전체 요약"에 없는 종목(예: KODEX 200, 삼성전자, SPY 등 목록 밖의 상품)을 물으면,
   아직 지원하지 않는다고 안내하고 확장 예정임을 언급하세요. 이때 action=VIEW_PRODUCT_LIST로
   응답하세요. 단, 지원 종목 "안에서" 조건에 맞는 상품을 나열해달라는 질문(예: "매달 분배하는
   상품 뭐 있어요?")은 미지원 종목 질문이 아닙니다 — "지원 종목 전체 요약" 데이터에서 조건에
   맞는 종목만 추려 답하세요. 또한 현재 조회 중인 ETF 데이터의 tokens(이름 토큰)에 등장하는
   영문 약어나 단어(예: 이름이 "ProShares UltraPro QQQ"인 상품에서 "QQQ가 뭔가요?")는 그
   상품 자체의 이름 구성 요소를 설명해달라는 용어 질문이지 별도의 미지원 종목 문의가
   아닙니다 — tokens의 translation을 근거로 설명하세요.
7. 화면에 표시된 판정 결과(경고·정보)와 어긋나는 말을 하지 않습니다.
8. ETF 및 이 서비스와 무관한 질문(날씨, 잡담 등)에는 도우미 역할만 안내하고 답하지 않습니다.
9. 사용자가 조건을 바꿔 가정해서 물으면(예: "3년만 들고 있으면?") 전달된 판정 결과 범위 안에서만
   답하고, 조건을 직접 바꿔볼 수 있음을 안내하세요. 이때 action=CHANGE_CONDITIONS로 응답하세요.
10. 판정 이유를 물으면 사용자의 조건과 발동된 경고·정보 코드를 1:1로 연결해서 설명하세요.
11. 거절할 때도 대안을 함께 제시하세요. 거절만 하고 끝내지 마세요.

답변은 쉬운 말로, 필요하면 짧은 문단으로 나눠 작성하세요. 비교 질문에는 마크다운 표를 써도 됩니다.
""".strip()


def build_system_prompt(
    *,
    stage: str,
    context: dict[str, Any],
    compare_context: dict[str, Any] | None,
    all_products: list[dict[str, Any]],
    horizon: Horizon,
    purpose: Purpose,
    fund_nature: FundNature,
    previous_product_name: str | None,
) -> str:
    sections = [
        SYSTEM_INSTRUCTIONS,
        f"## 현재 화면 단계\n{stage}",
        (
            "## 사용자 조건\n"
            f"- 보유 기간: {HORIZON_LABELS[horizon]}\n"
            f"- 투자 목적: {PURPOSE_LABELS[purpose]}\n"
            f"- 자금 성격: {FUND_NATURE_LABELS[fund_nature]}"
        ),
        (
            "## 현재 조회 중인 ETF 데이터 (이 안의 값만 근거로 사용)\n"
            f"```json\n{json.dumps(context, ensure_ascii=False, indent=2)}\n```"
        ),
        (
            "## 지원 종목 전체 요약 (교차 비교/조건별 목록 질문에 사용, 그 외엔 참고만)\n"
            f"```json\n{json.dumps(all_products, ensure_ascii=False, indent=2)}\n```"
        ),
    ]
    if compare_context is not None:
        sections.append(
            "## 비교 대상 ETF 데이터\n"
            f"```json\n{json.dumps(compare_context, ensure_ascii=False, indent=2)}\n```"
        )
    if previous_product_name:
        sections.append(f"## 이전에 조회한 상품\n{previous_product_name}")
    return "\n\n".join(sections)
