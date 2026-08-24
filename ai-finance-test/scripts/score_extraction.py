"""작업순서 7: 채점 + 근거 자동 검증.

응답 원문(raw/*.json)을 ground_truth.json과 대비하여 채점.

출력:
  results_field.csv: 필드별 점수 (CLAUDE.md 스키마)
"""

import csv
import json
import pathlib
import re
import sys
from difflib import SequenceMatcher

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
RESULTS_CSV = ROOT / "results_field.csv"
GROUND_TRUTH_PATH = ROOT / "ground_truth.json"
CORPUS_DIR = ROOT / "text"

RESULTS_CSV_HEADER = [
    "run_id", "sample", "condition", "field",
    "ai_value", "expected_value",
    "match_raw", "match_corrected", "is_null",
    "evidence_text", "evidence_found", "evidence_page",
]

FIELDS = [
    "종목명", "기초지수", "비교지수", "레버리지배율", "복제방식",
    "환헤지여부", "전략유형", "분배정책", "총보수",
]


def condition_of(run_id: str) -> str:
    """run_id({sample}_{condition}_r{n}_{ts})에서 조건을 되꺼낸다."""
    parts = run_id.split("_")
    return "_".join(parts[1:-2])


def normalize_text(s: str) -> str:
    """근거 검증용 정규화: 공백·줄바꿈·특수문자·표 구분자 제거."""
    if not s:
        return ""
    # 공백, 줄바꿈, 구두점, 표 구분자(|, -, 등) 제거
    return re.sub(r"[\s\.\,\!\?;:\-\(\)\[\]{}\"\'\*\%\&\#\@\+\=\/\\|‐–—~]", "", s)


def find_evidence(corpus_text: str, evidence: str, context_chars: int = 10) -> tuple[bool, int | None]:
    """근거 원문이 문서에 실제로 존재하는지 검증.

    Returns: (found: bool, page: int | None)
    """
    if not evidence or not corpus_text:
        return False, None

    norm_evidence = normalize_text(evidence)
    norm_corpus = normalize_text(corpus_text)

    # 1차 시도: 정규화 후 부분일치
    if norm_evidence in norm_corpus:
        # 페이지 추출: [PAGE n] 마커로 페이지 역추적
        norm_corpus_list = norm_corpus.split("=====")
        for chunk in norm_corpus_list:
            if norm_evidence in chunk:
                # [PAGE n] 마커 찾기 (마지막으로 나온 번호)
                page_matches = re.findall(r"\[PAGE(\d+)\]", corpus_text)
                if page_matches:
                    return True, int(page_matches[-1])
                return True, None
        return True, None

    # 2차 시도: 앞뒤 잘림 대응 (context_chars 제거 후 재시도)
    if len(norm_evidence) > context_chars * 2:
        trimmed = norm_evidence[context_chars:-context_chars]
        if trimmed in norm_corpus:
            return True, None

    return False, None


def norm_name(s: str) -> str:
    """종목명·지수명 대조용 정규화. 공백과 괄호류만 제거한다."""
    return re.sub(r"[\s()（）\[\]【】]", "", s or "")


# 펀드코드 접미사. 요약정보 페이지 제목에만 "…(합성 H)(B5268)" 형태로 붙어 있어
# C2(요약정보로 시작) 조건에서 AI가 이 표기를 고른다. 둘 다 문서에 실재하는
# 표기이므로 채점에서 접미사를 떼고 비교한다 — AI 오류가 아니라 표기 변형이다.
#
# 문서 내 실제 코드는 B5268(영문1+숫자4), EH735·DY904(영문2+숫자3) 3종이라
# 영문 1~3자 + 숫자 3자리 이상을 받는다.
#
# 반드시 norm_name() '전에' 적용할 것. 괄호를 먼저 지우고 매칭하면 괄호 없이
# 영문+숫자로 끝나는 정상 종목명이 잘린다 (삼성KODEX200 → 삼성KO).
FUND_CODE_SUFFIX = re.compile(r"\([A-Z]{1,3}\d{3,}\)\s*$")


def norm_fund_name(s: str) -> str:
    """종목명 대조용 정규화: 펀드코드 접미사 제거 후 공백·괄호 제거."""
    return norm_name(FUND_CODE_SUFFIX.sub("", s or ""))


def score_field(
    ai_value,
    expected_value,
    field: str,
    enum_values: list | None = None,
    allowed_values: list | None = None,
) -> dict:
    """필드별 채점 로직.

    Returns:
        match_raw (1/0): 정답과 일치
        is_null (1/0): AI 값이 null
    """
    is_null = ai_value is None
    match_raw = 0

    if is_null:
        # null이 정답인 경우가 있다(B의 기초지수). 오답과 구분해 집계한다.
        if allowed_values is not None:
            match_raw = 1 if None in allowed_values else 0
        else:
            match_raw = 1 if expected_value is None else 0
    elif field in ("레버리지배율", "총보수"):
        try:
            match_raw = 1 if float(ai_value) == float(expected_value) else 0
        except (ValueError, TypeError):
            match_raw = 0
    elif field in ("복제방식", "환헤지여부", "전략유형", "분배정책"):
        # enum: 정답값과 완전일치. enum 목록에 있기만 하면 되는 게 아니다.
        match_raw = 1 if ai_value == expected_value else 0
    elif allowed_values is not None:
        # 기초·비교지수: 허용 문자열 목록 중 하나와 일치하면 정답
        norm_ai = norm_name(ai_value)
        match_raw = 1 if any(
            norm_ai == norm_name(v) for v in allowed_values if v is not None
        ) else 0
    else:
        # 종목명: 펀드코드 접미사를 떼고 비교
        match_raw = 1 if norm_fund_name(ai_value) == norm_fund_name(expected_value) else 0

    return {
        "match_raw": match_raw,
        "is_null": 1 if is_null else 0,
    }


def score_run(run_id: str, sample: str) -> list[dict]:
    """한 회 실행에 대해 8개 필드 채점."""
    raw_path = RAW_DIR / f"{run_id}.json"
    if not raw_path.exists():
        return []

    try:
        response = json.loads(raw_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    gt = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    sample_gt = gt["samples"][sample]
    enums = gt["enum_definitions"]

    # 근거 검증용 코퍼스 로드
    corpus_path = CORPUS_DIR / f"{sample}.corpus.txt"
    corpus_text = corpus_path.read_text(encoding="utf-8") if corpus_path.exists() else ""

    results = []
    ai_values = response.get("값", {})
    ai_evidence = response.get("근거", {})

    for field in ["종목명", "기초지수", "비교지수", "레버리지배율", "복제방식", "환헤지여부", "전략유형", "분배정책", "총보수"]:
        # 기초·비교지수는 '지수' 복합 필드 안에 허용목록 형태로 들어 있다.
        allowed = None
        if field in ("기초지수", "비교지수"):
            sub = sample_gt["fields"].get("지수", {}).get(field, {})
            allowed = sub.get("expected_allowed")
            expected = allowed[0] if allowed else None
            field_spec = sub
        else:
            field_spec = sample_gt["fields"].get(field, {})
            expected = field_spec.get("expected")

        ai_value = ai_values.get(field)
        evidence_obj = ai_evidence.get(field, {})
        evidence_text = evidence_obj.get("원문")
        evidence_page = evidence_obj.get("페이지")

        # 채점
        enum_list = enums.get(field) if field in enums else None
        score = score_field(ai_value, expected, field, enum_list, allowed)

        # 근거 검증
        evidence_found = 0
        if evidence_text and not score["is_null"]:
            found, detected_page = find_evidence(corpus_text, evidence_text)
            evidence_found = 1 if found else 0
            if not evidence_page and detected_page:
                evidence_page = detected_page

        results.append({
            "run_id": run_id,
            "sample": sample,
            "condition": condition_of(run_id),
            "field": field,
            "ai_value": json.dumps(ai_value, ensure_ascii=False) if ai_value is not None else "null",
            "expected_value": json.dumps(expected, ensure_ascii=False) if expected is not None else "null",
            "match_raw": score["match_raw"],
            "match_corrected": 0,  # TODO: 종목명 파싱 보정 로직
            "is_null": score["is_null"],
            "evidence_text": evidence_text or "",
            "evidence_found": evidence_found,
            "evidence_page": evidence_page or "",
        })

    return results


def main() -> None:
    # 모든 raw/*.json 파일을 실행 ID로 매핑
    runs = {}
    for raw_path in sorted(RAW_DIR.glob("*.json")):
        run_id = raw_path.stem
        # run_id 형식: {sample}_{condition}_{repeat}_{timestamp}
        parts = run_id.split("_")
        if len(parts) >= 3:
            sample = parts[0]
            runs[run_id] = sample

    all_results = []
    for run_id, sample in sorted(runs.items()):
        print(f"채점: {run_id}")
        results = score_run(run_id, sample)
        all_results.extend(results)

    # CSV 쓰기
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_CSV_HEADER)
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\n결과 {len(all_results)}개 필드 채점 완료 ({RESULTS_CSV})")

    conditions = sorted({r["condition"] for r in all_results})
    samples = sorted({r["sample"] for r in all_results})

    print(f"\n조건 × 샘플 정답률 (보정 전)")
    print(f"  {'':10}" + "".join(f"{c:>12}" for c in conditions))
    for sample in samples:
        cells = []
        for c in conditions:
            sub = [r for r in all_results if r["sample"] == sample and r["condition"] == c]
            if not sub:
                cells.append(f"{'-':>12}")
                continue
            hit = sum(r["match_raw"] for r in sub)
            cells.append(f"{hit:>4}/{len(sub):<3}{round(100*hit/len(sub)):>3}%")
        print(f"  {sample:10}" + "".join(cells))

    print(f"\n필드별 정답률")
    for field in FIELDS:
        sub = [r for r in all_results if r["field"] == field]
        if not sub:
            continue
        hit = sum(r["match_raw"] for r in sub)
        nulls = sum(r["is_null"] for r in sub)
        ev = sum(r["evidence_found"] for r in sub)
        flag = "" if hit == len(sub) else "  <<"
        print(f"  {field:8} {hit:>2}/{len(sub):<3} ({round(100*hit/len(sub)):>3}%)  "
              f"null={nulls}  근거확인={ev}/{len(sub)}{flag}")

    # CLAUDE.md 실패방식 기준: null이 '확신 있는 오답'보다 많아야 한다
    wrong = [r for r in all_results if not r["match_raw"] and not r["is_null"]]
    nulls = [r for r in all_results if r["is_null"] and not r["match_raw"]]
    print(f"\n실패 방식: null {len(nulls)}건 vs 확신 있는 오답 {len(wrong)}건")


if __name__ == "__main__":
    main()
