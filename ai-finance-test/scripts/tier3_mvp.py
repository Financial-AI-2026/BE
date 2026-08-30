from __future__ import annotations

import argparse
from typing import Any

# ETF 마스터 데이터 10종
ETF_MASTER = [
    {
        "ticker": "225040",
        "name": "TIGER 미국S&P500레버리지(합성 H)",
        "base_index": "S&P 500",
        "leverage": 2.0,
        "replication": "합성",
        "currency_hedging": "헤지",
        "strategy": "레버리지",
        "distribution": "무분배",
        "expense_ratio": "0.25%",
        "type": "레버리지·합성·환헤지",
        "summary": "미국 대형주 500개를 2배로 추종하는 레버리지 ETF",
    },
    {
        "ticker": "418660",
        "name": "TIGER 미국나스닥100레버리지(합성)",
        "base_index": "NASDAQ-100",
        "leverage": 2.0,
        "replication": "합성",
        "currency_hedging": "미헤지",
        "strategy": "레버리지",
        "distribution": "무분배",
        "expense_ratio": "0.25%",
        "type": "레버리지·합성·환노출",
        "summary": "미국 기술주 대형주를 2배로 추종하는 구조",
    },
    {
        "ticker": "123310",
        "name": "TIGER 인버스",
        "base_index": "F-KOSPI200",
        "leverage": -1.0,
        "replication": "선물 중심",
        "currency_hedging": "해당없음",
        "strategy": "인버스",
        "distribution": "무분배",
        "expense_ratio": "0.022%",
        "type": "인버스·국내",
        "summary": "지수가 하락할 때 수익을 추구하는 반대 방향 ETF",
    },
    {
        "ticker": "441680",
        "name": "TIGER 미국나스닥100커버드콜(합성)",
        "base_index": "Cboe Nasdaq-100 BuyWrite V2 (TR)",
        "leverage": 1.0,
        "replication": "합성",
        "currency_hedging": "미헤지",
        "strategy": "커버드콜",
        "distribution": "월분배",
        "expense_ratio": "0.37%",
        "type": "커버드콜·합성·환노출",
        "summary": "콜옵션 매도로 분배 수익을 확보하는 구조",
    },
    {
        "ticker": "472150",
        "name": "TIGER 배당커버드콜액티브",
        "base_index": "코스피200 커버드콜 5% OTM",
        "leverage": 1.0,
        "replication": "실물",
        "currency_hedging": "해당없음",
        "strategy": "커버드콜(액티브)",
        "distribution": "월분배",
        "expense_ratio": "0.38%",
        "type": "커버드콜·액티브·월분배·국내",
        "summary": "국내 지수에 기반한 커버드콜 전략으로 매월 분배",
    },
    {
        "ticker": "435420",
        "name": "TIGER 미국나스닥100채권혼합Fn",
        "base_index": "FnGuide 나스닥100 채권혼합지수",
        "leverage": 1.0,
        "replication": "실물",
        "currency_hedging": "헤지",
        "strategy": "자산혼합",
        "distribution": "분기분배",
        "expense_ratio": "0.25%",
        "type": "자산혼합형·환헤지",
        "summary": "주식과 채권이 함께 섞인 혼합 전략의 대표적 사례",
    },
    {
        "ticker": "KR70025N0008",
        "name": "TIGER TDF2045 적격",
        "base_index": "S&P Korea Target Date 2045 Global Index",
        "leverage": 1.0,
        "replication": "실물",
        "currency_hedging": "미헤지",
        "strategy": "타겟데이트",
        "distribution": "분기 기준",
        "expense_ratio": "0.19%",
        "type": "TDF·자산배분",
        "summary": "2045년을 목표로 자산 비중을 자동으로 조정하는 구조",
    },
    {
        "ticker": "133690",
        "name": "TIGER 미국나스닥100",
        "base_index": "NASDAQ-100",
        "leverage": 1.0,
        "replication": "실물",
        "currency_hedging": "미헤지",
        "strategy": "지수추종",
        "distribution": "분기분배",
        "expense_ratio": "0.007%",
        "type": "일반·환노출",
        "summary": "미국 기술주 지수를 그대로 따라가는 일반형 ETF",
    },
    {
        "ticker": "448290",
        "name": "TIGER 미국S&P500(H)",
        "base_index": "S&P 500",
        "leverage": 1.0,
        "replication": "실물",
        "currency_hedging": "헤지",
        "strategy": "지수추종",
        "distribution": "분기분배",
        "expense_ratio": "0.07%",
        "type": "일반·환헤지",
        "summary": "기본 지수 추종형이지만 환율을 막는 구조",
    },
    {
        "ticker": "102110",
        "name": "TIGER 200",
        "base_index": "코스피200",
        "leverage": 1.0,
        "replication": "실물",
        "currency_hedging": "해당없음",
        "strategy": "지수추종",
        "distribution": "분기분배",
        "expense_ratio": "0.05%",
        "type": "일반·국내 대표",
        "summary": "한국 대표 지수 200개를 그대로 따라가는 기본형 ETF",
    },
]

# 종목 조회용 인덱스
ETF_INDEX: dict[str, dict[str, Any]] = {item["ticker"]: item for item in ETF_MASTER}

# 이름 해독 데이터( Layer 1 구현 : 토큰 단위 분해 + 한국어 설명 )
NAME_DECODE = {
    "225040": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "미국S&P500", "translation": "미국 큰 회사 500개를"},
        {"token": "레버리지", "translation": "2배로 따라가는데"},
        {"token": "(합성", "translation": "실제 주식은 사지 않고"},
        {"token": "H)", "translation": "환율 걱정은 없는 상품"},
    ],
    "418660": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "미국나스닥100", "translation": "미국 기술주 100개를"},
        {"token": "레버리지", "translation": "2배로 따라가는데"},
        {"token": "(합성)", "translation": "실제 주식은 사지 않는 상품"},
        {"token": "(H 없음)", "translation": "환율에 따라 수익이 달라집니다"},
    ],
    "123310": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "인버스", "translation": "한국 대표 주가가 떨어지면 오르는 상품"},
    ],
    "441680": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "미국나스닥100", "translation": "미국 기술주 100개를 담고"},
        {"token": "커버드콜", "translation": "매달 돈을 받는 대신 큰 상승은 포기하며"},
        {"token": "(합성)", "translation": "실제 주식은 사지 않는 상품"},
    ],
    "472150": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "배당", "translation": "매달 돈을 나눠주고"},
        {"token": "커버드콜", "translation": "큰 상승은 포기하는 대신 그 돈을 만들며"},
        {"token": "액티브", "translation": "지수를 그대로 따라가지 않고 더 벌려고 하는 상품"},
    ],
    "435420": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "미국나스닥100", "translation": "미국 기술주 100개와"},
        {"token": "채권", "translation": "채권을"},
        {"token": "혼합", "translation": "함께 담은"},
        {"token": "Fn", "translation": "에프앤가이드가 만든 기준을 따라가는 상품"},
    ],
    "KR70025N0008": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "TDF", "translation": "은퇴 시점이 다가올수록 알아서 안전하게 바꿔주는"},
        {"token": "2045", "translation": "2045년을 목표로 하는"},
        {"token": "적격", "translation": "퇴직연금 계좌에서 살 수 있는 상품"},
    ],
    "133690": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "미국나스닥100", "translation": "미국 기술주 100개를 그대로 따라가는 상품"},
        {"token": "(H 없음)", "translation": "환율에 따라 수익이 달라집니다"},
    ],
    "448290": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "미국S&P500", "translation": "미국 큰 회사 500개를 그대로 따라가고"},
        {"token": "(H)", "translation": "환율 걱정은 없는 상품"},
    ],
    "102110": [
        {"token": "TIGER", "translation": "미래에셋이 만든"},
        {"token": "200", "translation": "한국 대표 기업 200개를 그대로 따라가는 상품"},
    ],
}

# 경고 문구 (위험 설명)
WARNING_TEXT = {
    "W-LEV-01": {
        "title": "오래 들고 있으면 손해 볼 수 있어요",
        "body": "이 상품은 하루 단위로 지수의 {leverage}배를 맞추도록 만들어졌습니다. 지수가 올랐다 내렸다를 반복하면, {period} 뒤에는 지수가 제자리여도 원금이 줄어 있을 수 있습니다.",
    },
    "W-CC-01": {
        "title": "차익을 노리는 목적과 맞지 않습니다",
        "body": "이 상품이 매달 주는 돈은, 앞으로 오를 수 있는 몫을 미리 팔아서 만듭니다. 그래서 크게 오르는 구간에서 그 상승분을 온전히 받지 못합니다.",
    },
    "W-TR-01": {
        "title": "정기적으로 현금을 받고 싶다는 목적과 맞지 않습니다",
        "body": "이 상품은 돈을 나눠주지 않고 다시 굴리는 구조입니다. 현금이 필요하다면 직접 팔아야 합니다.",
    },
    "W-FX-01": {
        "title": "안정적인 현금 목적과 맞지 않을 수 있습니다",
        "body": "이름에 (H)가 없습니다. 환율 변동을 막는 장치가 없어서, 받는 돈이 환율에 따라 달라집니다.",
    },
    "W-TDF-01": {
        "title": "짧게 보유하실 계획과 맞지 않습니다",
        "body": "이 상품은 2045년을 목표로 천천히 안전해지도록 설계되었습니다. 1년 안에 파실 계획이라면 이 구조의 이점을 얻기 어렵습니다.",
    },
    "W-MIX-01": {
        "title": "주식 상품처럼 보이지만 채권이 더 많아요",
        "body": "이름 앞에 '미국나스닥100'이 있어 기술주 상품으로 보이지만, 실제로는 채권 비중이 더 큽니다. 나스닥이 크게 올라도 그 상승분이 일부만 반영됩니다.",
    },
}

# 정보 문구(구조 설명)
INFO_TEXT = {
    "I-SYN-01": {
        "title": "주식을 직접 사지 않고 증권사와 약속만 했어요",
        "body": "이 상품은 {base_index}를 직접 사는 대신, 증권사와 계약(TRS)을 맺어 수익률을 받는 구조입니다.",
    },
    "I-FX-01": {
        "title": "환율에 따라 수익이 달라져요",
        "body": "이름에 (H)가 없습니다. 미국 주가가 올라도 원달러 환율이 떨어지면 수익이 줄어들 수 있습니다.",
    },
    "I-FXH-01": {
        "title": "환율이 오르내려도 크게 상관없어요",
        "body": "원달러 환율이 변해도 수익률에 미치는 영향이 작습니다. 대신 그 장치를 유지하는 비용이 듭니다.",
    },
    "I-ACT-01": {
        "title": "지수를 그대로 따라가지 않아요",
        "body": "운용사가 지수보다 더 벌기 위해 종목을 조정합니다. 지수보다 잘할 수도, 못할 수도 있습니다.",
    },
    "I-DIV-01": {
        "title": "매달 돈을 나눠줘요",
        "body": "매월 마지막 영업일 기준으로 분배금을 지급합니다. 다만 그 돈이 어디서 나오는지 함께 살펴보는 것이 좋습니다.",
    },
    "I-MIX-01": {
        "title": "주식과 채권을 함께 담고 있어요",
        "body": "하나의 상품 안에 주식과 채권이 함께 들어 있습니다. 주식만 담은 상품보다 덜 흔들리지만, 크게 오를 때도 덜 오릅니다.",
    },
}

# 경고 우선순위
WARNING_PRIORITY = {
    "W-LEV-01": 1,
    "W-MIX-01": 2,
    "W-CC-01": 2,
    "W-TR-01": 3,
    "W-FX-01": 3,
    "W-TDF-01": 3,
}

# 배너 문구와 색상
BANNER_STYLES = {
    0: {"text": "어긋나는 부분은 발견되지 않았어요", "color": "sage_green"},
    1: {"text": "한 가지는 알고 사셔야 해요", "color": "amber_soft"},
    2: {"text": "생각하신 것과 다를 수 있어요", "color": "amber_strong"},
}

# ETF_MASTER 전체 목록을 복사해서 반환
def get_etf_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in ETF_MASTER]

# 종목코드로 개별 ETF 정보를 조회
def get_etf_by_ticker(ticker: str) -> dict[str, Any]:
    if ticker not in ETF_INDEX:
        raise KeyError(f"지원하지 않는 ETF 종목: {ticker}")
    return dict(ETF_INDEX[ticker])

# 종목명 해독 데이터를 조회
def get_name_decoding(ticker: str) -> list[dict[str, str]]:
    if ticker not in NAME_DECODE:
        raise KeyError(f"이름 해독 데이터가 없는 ETF: {ticker}")
    return [dict(item) for item in NAME_DECODE[ticker]]

# 사용자의 기간과 투자 목적에 맞춰 경고 코드를 계산
def build_warning_codes(etf: dict[str, Any], period: str, purpose: str) -> list[str]:
    warnings: list[str] = []

    if etf["leverage"] != 1.0 and period in {"MID", "LONG", "UNKNOWN"}:
        warnings.append("W-LEV-01")

    if etf["strategy"] == "커버드콜" and purpose == "시세차익":
        warnings.append("W-CC-01")

    if etf["distribution"] == "무분배" and purpose == "인컴":
        warnings.append("W-TR-01")

    if etf["currency_hedging"] == "미헤지" and purpose == "인컴":
        warnings.append("W-FX-01")

    if etf["strategy"] == "타겟데이트" and period == "SHORT":
        warnings.append("W-TDF-01")

    if etf["strategy"] == "자산혼합" and purpose == "시세차익":
        warnings.append("W-MIX-01")

    return sorted(warnings, key=lambda code: (WARNING_PRIORITY.get(code, 99), code))

# 상품 설명 정보 뽑는 함수
def build_info_codes(etf: dict[str, Any]) -> list[str]:
    info_codes: list[str] = []

    if etf["replication"] == "합성":
        info_codes.append("I-SYN-01")

    if etf["currency_hedging"] == "미헤지":
        info_codes.append("I-FX-01")

    if etf["currency_hedging"] == "헤지":
        info_codes.append("I-FXH-01")

    if etf["strategy"] == "커버드콜(액티브)":
        info_codes.append("I-ACT-01")

    if etf["distribution"] == "월분배":
        info_codes.append("I-DIV-01")

    if etf["strategy"] == "자산혼합":
        info_codes.append("I-MIX-01")

    return info_codes

# 최종 상단 배너 문구 생성
def build_banner(warnings: list[str]) -> dict[str, Any]:
    count = len(warnings)
    style = BANNER_STYLES.get(count, BANNER_STYLES[2])
    return {
        "warning_count": count,
        "text": style["text"],
        "color": style["color"],
    }

# 각 경고 코드에 대응되는 제목과 본문을 조합
def build_warning_details(etf: dict[str, Any], warnings: list[str], period: str, purpose: str) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []

    for code in warnings:
        payload = WARNING_TEXT[code]
        detail = {
            "code": code,
            "title": payload["title"],
            "body": payload["body"].format(
                leverage=etf["leverage"],
                period=period,
                purpose=purpose,
                base_index=etf["base_index"],
            ),
        }
        details.append(detail)
    return details

# 정보 코드별 설명을 생성
def build_info_details(etf: dict[str, Any], info_codes: list[str]) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for code in info_codes:
        payload = INFO_TEXT[code]
        detail = {
            "code": code,
            "title": payload["title"],
            "body": payload["body"].format(base_index=etf["base_index"]),
        }
        details.append(detail)
    return details

# 최종 결과를 조립
def get_risk_assessment(ticker: str, period: str, purpose: str) -> dict[str, Any]:
    etf = get_etf_by_ticker(ticker)
    warnings = build_warning_codes(etf, period, purpose)
    info_codes = build_info_codes(etf)
    banner = build_banner(warnings)

    return {
        "ticker": ticker,
        "name": etf["name"],
        "period": period,
        "purpose": purpose,
        "warning_codes": warnings,
        "info_codes": info_codes,
        "banner": banner,
        "warnings": build_warning_details(etf, warnings, period, purpose),
        "info": build_info_details(etf, info_codes),
        "summary": f"{period} · {purpose} 기준으로 살펴봤어요",
    }

# 종목 상세 조회용 응답을 생성
def get_etf_detail(ticker: str) -> dict[str, Any]:
    etf = get_etf_by_ticker(ticker)
    return {
        "ticker": etf["ticker"],
        "name": etf["name"],
        "base_index": etf["base_index"],
        "leverage": etf["leverage"],
        "replication": etf["replication"],
        "currency_hedging": etf["currency_hedging"],
        "strategy": etf["strategy"],
        "distribution": etf["distribution"],
        "expense_ratio": etf["expense_ratio"],
        "type": etf["type"],
        "summary": etf["summary"],
        "name_decoding": get_name_decoding(ticker),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Tier3 ETF 위험 판정 샘플 실행기")
    parser.add_argument("--ticker", default="225040", help="ETF 종목 코드")
    parser.add_argument("--period", default="LONG", help="보유 기간: SHORT, MID, LONG, UNKNOWN")
    parser.add_argument("--purpose", default="인컴", help="투자 목적: 시세차익, 인컴, 자산성장")
    args = parser.parse_args()

    etf = get_etf_by_ticker(args.ticker)
    result = get_risk_assessment(args.ticker, args.period, args.purpose)

    print("ETF 정보:")
    print(f"- ticker: {etf['ticker']}")
    print(f"- name: {etf['name']}")
    print(f"- strategy: {etf['strategy']}")
    print(f"- leverage: {etf['leverage']}")
    print(f"- distribution: {etf['distribution']}")
    print(f"- currency_hedging: {etf['currency_hedging']}")
    print()
    print("선택한 조건:")
    print(f"- period: {args.period}")
    print(f"- purpose: {args.purpose}")
    print()
    print("이름 해독 결과:")
    print(get_name_decoding(args.ticker))
    print()
    print("분석 결과:")
    print(result)


if __name__ == "__main__":
    main()
