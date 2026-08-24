"""작업순서 3: 전처리 파이프라인 — 표 재구성 + 목차 기준 섹션 분할.

본문은 PyMuPDF 원시 텍스트를 쓰고, 열 대응이 깨지는 수치 격자표만 pdfplumber로
재구성해 해당 페이지 끝에 덧붙인다. 서술형 표는 원시 텍스트로 이미 읽히므로
재구성하지 않는다 (전량 재구성 시 1.48배, 수치표만 1.06~1.11배).

섹션 분할은 목차([목 차] 페이지)를 파싱해 얻은 항목을 본문에서 찾는 방식이다.
본문 헤딩을 정규식으로 추측하지 않으므로 운용사 양식이 달라도 목차만 있으면 동작한다.

출력:
  text/{S}.corpus.txt        C1 입력 겸 근거 대조 코퍼스 (본문 + 재구성 표)
  sections/{S}.map.json      섹션 경계 (부/번호/제목/페이지범위)
  sections/{S}.c2_wide.txt   C2-wide 입력
  sections/{S}.c2_narrow.txt C2-narrow 입력 (제2부 10 투자위험 제외)
  sections/corpus_report.json 조건별 토큰 실측치
"""

import json
import pathlib
import re
import statistics
from difflib import SequenceMatcher

import pdfplumber
import pymupdf
import tiktoken

ROOT = pathlib.Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "docs" / "prospectus"
TEXT_DIR = ROOT / "text"
SEC_DIR = ROOT / "sections"

SAMPLES = {
    "A": "TIGER 미국S&P500 레버리지(합성 H)_투자설명서.pdf",
    "B": "TIGER 배당커버드콜액티브_투자설명서.pdf",
    "C": "TIGER TDF2045 적격_투자설명서.pdf",
    # D는 held-out 검증용. A/B/C로 만든 프롬프트가 처음 보는 문서에서도
    # 버티는지 확인하려고 나중에 추가했다. 본 실행 27회에는 포함되지 않는다.
    "D": "투자설명서_미래에셋tiger200선물레버리지증권상장지수투자신탁(주식-파생형)_20260626_k55301bo0239.pdf",
}

# C2에 넣을 섹션. (부, 번호, 제목검증키워드) — Tier1 8필드의 근거가 실리는 곳.
#
# 조회는 (부, 번호)로 하되 가져온 섹션의 제목을 키워드로 검증한다. 번호만 믿으면
# 다른 양식에서 9번이 투자전략이 아닐 때 엉뚱한 섹션을 조용히 가져오고, 그러면
# "C2 정확도가 낮다"는 결과가 AI 문제인지 전처리 문제인지 구분이 안 된다.
#
# 번호와 제목 중 무엇이 운용사 간에 안정적인지는 아직 모른다. 실측된 것은
# 미래에셋 3종에서 번호 34개 전부 일치, 제목 5건 불일치라는 사실뿐이므로
# 조회 키는 번호를 유지한다. 타 운용사 회귀 테스트 후 재검토할 것.
C2_SECTIONS = [
    (1, 1, "명칭"),
    (2, 1, "명칭"),
    (2, 6, "구조"),
    (2, 7, "투자목적"),
    (2, 8, "투자대상"),
    (2, 9, "투자전략"),
    (2, 10, "투자위험"),
    (2, 13, "보수"),
    (2, 14, "배분"),
]
# 제2부 10(투자위험)은 정형 위험고지 문구가 대부분이라 narrow에서 제외한다.
C2_NARROW_EXCLUDE = {(2, 10)}

PAGE_MARKER = "===== [PAGE {n}] ====="
TABLE_MARKER = "----- [표 복원 p.{n}] -----"

NUMERIC_CELL = re.compile(r"^-?[\d,]+\.?\d*%?$")

# 표기 흔들림을 흡수한다. 실측: 미래에셋 "[목 차]" / "제 1 부. " 대(對)
# 삼성 "목        차" / "제1부 ". 항목 번호는 두 운용사가 공유하므로
# 조회 키는 번호를 유지하고, 형식 가정만 느슨하게 둔다.
TOC_MARKER = re.compile(r"\[?\s*목\s*차\s*\]?")
TOC_BU = re.compile(r"^제\s*(\d+)\s*부\.?\s*(.+)$")
TOC_SUB = re.compile(r"^(\d{1,2})\.\s*(.+)$")
BODY_HEAD = re.compile(r"^(\d{1,2})\.\s*(.+)$")
BODY_BU = re.compile(r"^제\s*(\d+)\s*부\.?")

# 목차가 여러 페이지에 걸칠 수 있다 (미래에셋 1장, 삼성 4장). 본문 시작을
# 못 알아채고 폭주하는 것을 막는 안전 상한.
MAX_TOC_PAGES = 8

# 목차와 본문을 가르는 기준. 목차는 제목의 나열이고 본문은 문장이라 줄 길이가
# 갈린다. 실측(미래에셋 3종 + 삼성 1종): 목차 페이지 최장줄 19~45,
# 본문 첫 페이지 61~69. 그 사이가 비어 있어 50을 경계로 둔다.
TOC_MAX_LINE_LEN = 50

# 목차와 본문의 제목 표기가 어긋나는 경우가 있다 (B: 목차 "5. 책임운용전문인력" vs
# 본문 "5. 운용전문인력"). 완전일치를 요구하면 섹션을 놓치므로 유사도로 판정한다.
TITLE_SIMILARITY = 0.75

ENC = tiktoken.get_encoding("o200k_base")


def norm(s: str) -> str:
    """공백·구두점 제거. 목차 항목과 본문 헤딩 대조용."""
    return re.sub(r"[\s,.·ㆍ()\[\]:]", "", s)


# ---------------------------------------------------------------- 표 재구성


def normalize_table(raw: list[list]) -> list[list[str]] | None:
    """빈 행·열을 걷어내고 격자표만 남긴다. 레이아웃용 가짜 표는 버린다."""
    rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in raw]
    if not rows:
        return None
    width = max(len(r) for r in rows)
    keep = [i for i in range(width) if any(i < len(r) and r[i] for r in rows)]
    rows = [[r[i] if i < len(r) else "" for i in keep] for r in rows]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2 or len(keep) < 2:
        return None
    if sum(1 for r in rows if sum(1 for c in r if c) >= 2) < 2:
        return None
    return rows


def is_numeric_grid(rows: list[list[str]]) -> bool:
    """수치 격자표 판정. 서술형 표는 원시 텍스트로 충분하므로 제외한다."""
    cells = [c for r in rows for c in r if c]
    if len(cells) < 6:
        return False
    if sum(1 for c in cells if NUMERIC_CELL.match(c)) < 3:
        return False
    return statistics.mean(len(c) for c in cells) < 25


def render(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(r) for r in rows)


def extract_tables_by_page(pdf_path: pathlib.Path) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            rendered = [
                render(rows)
                for raw in page.extract_tables()
                if (rows := normalize_table(raw)) and is_numeric_grid(rows)
            ]
            if rendered:
                out[pno] = rendered
    return out


def extract_fee_tables(pdf_path: pathlib.Path, pages_wanted: set[int]) -> dict[int, list[str]]:
    """총보수 표 전용 2차 탐색. is_numeric_grid 임계값에 기대지 않는다.

    문서 전체에 이 규칙(격자 판정 생략, 텍스트 매칭만)을 적용하면 서술형 표까지
    다 재구성돼 토큰이 다시 부푼다(1.06배 → 1.48배). 하지만 요약정보·제2부13은
    이미 목차로 위치를 알고 있으므로, 그 좁은 범위 안에서는 "총보수" 텍스트가
    들어간 표를 격자 판정과 무관하게 전부 잡는다. 총보수 하나가 빠지면 Tier1
    8필드 중 1개가 통째로 사라지므로, 여기서는 평균 셀 길이 같은 임계값에
    기대지 않는다.
    """
    out: dict[int, list[str]] = {}
    if not pages_wanted:
        return out
    with pdfplumber.open(pdf_path) as pdf:
        for pno in sorted(pages_wanted):
            if not (1 <= pno <= len(pdf.pages)):
                continue
            for raw in pdf.pages[pno - 1].extract_tables():
                rows = normalize_table(raw)
                if rows and any("총보수" in c for r in rows for c in r):
                    out.setdefault(pno, []).append(render(rows))
    return out


def merge_tables(base: dict[int, list[str]], extra: dict[int, list[str]]) -> None:
    for pno, rendered in extra.items():
        existing = base.setdefault(pno, [])
        existing += [r for r in rendered if r not in existing]


# ------------------------------------------------------------- 섹션 분할


def parse_toc(pages: list[str]) -> tuple[int, int, list[dict]]:
    """목차를 파싱해 (시작페이지, 끝페이지, 항목목록)을 만든다.

    목차 마커가 있는 페이지에서 시작해, 목차처럼 보이는 동안 계속 이어붙인다.
    본문의 "제1부" 재등장으로 끊으려 했으나 삼성 문서는 본문 부 헤딩이 같은
    형식으로 나오지 않아 폭주했다. 줄 길이로 가르는 편이 실측상 안정적이다.
    """
    toc_page = next(
        i
        for i, p in enumerate(pages, 1)
        if any(TOC_MARKER.fullmatch(l.strip()) for l in p.split("\n"))
    )
    entries, bu, toc_end = [], None, toc_page
    for pno in range(toc_page, min(toc_page + MAX_TOC_PAGES, len(pages)) + 1):
        if pno > toc_page and not looks_like_toc(pages[pno - 1]):
            break
        for line in pages[pno - 1].split("\n"):
            line = line.strip()
            if m := TOC_BU.match(line):
                bu = int(m.group(1))
            elif bu and (m := TOC_SUB.match(line)):
                entries.append(
                    {"bu": bu, "num": int(m.group(1)), "title": m.group(2).strip()}
                )
        toc_end = pno
    return toc_page, toc_end, entries


def looks_like_toc(page: str) -> bool:
    """제목의 나열인가(목차) 문장인가(본문)."""
    lines = [l.strip() for l in page.split("\n") if l.strip()]
    if not lines or max(len(l) for l in lines) > TOC_MAX_LINE_LEN:
        return False
    return any(TOC_BU.match(l) or TOC_SUB.match(l) for l in lines)


def locate_summary(pages: list[str], toc_page: int, toc_end: int, body_start: int) -> dict:
    """요약정보 구간. 목차 앞(미래에셋)일 수도 뒤(삼성)일 수도 있다."""
    if before := [i for i in range(1, toc_page) if "요약정보" in pages[i - 1]]:
        start, end = before[0], toc_page - 1
    elif after := [i for i in range(toc_end + 1, body_start) if "요약정보" in pages[i - 1]]:
        start, end = after[0], body_start - 1
    else:
        raise SectionMismatch("요약정보 구간을 찾지 못했습니다.")
    return {"bu": 0, "num": 0, "title": "요약정보", "start": start, "end": max(start, end)}


def title_match(body: str, toc: str) -> bool:
    a, b = norm(body), norm(toc)
    if not a or not b:
        return False
    if a.startswith(b) or b.startswith(a) or a.endswith(b) or b.endswith(a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= TITLE_SIMILARITY


def find_bu_heading(pages: list[str], start_page: int, bu: int) -> int | None:
    for pno in range(start_page, len(pages) + 1):
        for line in pages[pno - 1].split("\n"):
            if (m := BODY_BU.match(line.strip())) and int(m.group(1)) == bu:
                return pno
    return None


def find_heading(pages: list[str], start_page: int, entry: dict) -> tuple[int | None, bool]:
    """(페이지, 제목까지 확인됐는지).

    제목이 맞는 자리를 우선하되, 없으면 번호만 맞는 첫 자리를 차선으로 쓴다.
    목차와 본문의 제목이 어긋나는 경우가 실재하기 때문이다
    (삼성 제2부 14: 목차 "이익 배분 및 과세" ↔ 본문 "투자신탁분배금 및 과세",
    유사도 0.667). 번호는 운용사가 달라도 유지되는 것이 실측됐으므로
    (미래에셋 3종 + 삼성에서 C2 좌표 9개 일치) 번호를 더 신뢰한다.
    """
    fallback = None
    for pno in range(start_page, len(pages) + 1):
        for line in pages[pno - 1].split("\n"):
            m = BODY_HEAD.match(line.strip())
            if not m or int(m.group(1)) != entry["num"]:
                continue
            if title_match(m.group(2), entry["title"]):
                return pno, True
            if fallback is None:
                fallback = pno
    return fallback, False


def locate_sections(pages: list[str], toc_page: int, entries: list[dict]) -> list[dict]:
    """목차 항목을 본문에서 순서대로 찾아 페이지 범위를 확정한다.

    커서를 앞으로만 옮기며 훑는다. 제목이 겹치는 항목(제1부 1 / 제2부 1 모두
    "집합투자기구의 명칭")이 있어서, 매번 처음부터 찾으면 앞엣것을 잘못 문다.
    """
    found, cursor, cur_bu = [], toc_page + 1, None
    for e in entries:
        if e["bu"] != cur_bu:
            # 부가 바뀌면 본문의 "제 N 부." 헤딩까지 커서를 밀어둔다. 부마다 번호가
            # 1부터 다시 시작하고 제목도 겹쳐서(제1부 1 / 제2부 1 = "집합투자기구의
            # 명칭"), 부 경계를 끊지 않으면 앞 부의 항목을 다시 문다.
            cur_bu = e["bu"]
            cursor = find_bu_heading(pages, cursor, cur_bu) or cursor
        # 여러 섹션이 한 페이지를 공유할 수 있으므로 커서를 pno+1로 밀지 않는다.
        pno, verified = find_heading(pages, cursor, e)
        if pno is not None:
            found.append({**e, "start": pno, "title_verified": verified})
            cursor = pno

    for i, f in enumerate(found):
        nxt = found[i + 1]["start"] - 1 if i + 1 < len(found) else len(pages)
        f["end"] = max(f["start"], nxt)  # 같은 페이지에서 시작하면 그 페이지 하나
    return found


# ---------------------------------------------------------------- 조립


class SectionMismatch(Exception):
    """번호로 집은 섹션의 제목이 기대와 다름. 양식이 달라졌다는 신호."""


def resolve_sections(
    by_key: dict[tuple[int, int], dict], picks: list[tuple[int, int, str]], sample: str
) -> tuple[list[dict], list[tuple[int, int]]]:
    """(부, 번호)로 섹션을 집되 제목 키워드로 검증한다.

    없는 섹션은 missing으로 보고하고 넘어가지만, 있는데 제목이 다르면 예외를
    던진다. 전자는 C2가 좁아질 뿐이고 후자는 엉뚱한 내용이 섞이는 것이라
    실패의 성격이 다르다.
    """
    chosen, missing = [], []
    for bu, num, keyword in picks:
        sec = by_key.get((bu, num))
        if sec is None:
            missing.append((bu, num))
            continue
        if keyword not in norm(sec["title"]):
            raise SectionMismatch(
                f"[{sample}] 제{bu}부 {num}번의 제목이 기대와 다릅니다. "
                f"기대 키워드={keyword!r}, 실제 제목={sec['title']!r}. "
                f"양식이 다른 문서일 수 있으니 C2_SECTIONS 매핑을 확인하세요."
            )
        chosen.append(sec)
    return chosen, missing


def page_block(pno: int, text: str, tables: list[str]) -> str:
    parts = [PAGE_MARKER.format(n=pno), text]
    for t in tables:
        parts += [TABLE_MARKER.format(n=pno), t]
    return "\n".join(parts) + "\n"


def build(sample: str, filename: str) -> dict:
    pdf_path = PDF_DIR / filename
    doc = pymupdf.open(pdf_path)
    pages = [p.get_text("text") for p in doc]
    doc.close()

    tables = extract_tables_by_page(pdf_path)

    toc_page, toc_end, entries = parse_toc(pages)
    sections = locate_sections(pages, toc_end, entries)
    body_start = min((s["start"] for s in sections), default=len(pages))
    summary = locate_summary(pages, toc_page, toc_end, body_start)
    by_key = {(s["bu"], s["num"]): s for s in sections}

    # 총보수 안전망. is_numeric_grid 통과분에 이미 총보수 표가 있으면 그대로 두고
    # (A/B/C 전부 이 경로), 없을 때만 격자 판정 없는 넓은 재탐색으로 넘어간다.
    # 먼저 시도 안 하고 항상 재탐색하면 pdfplumber가 같은 표를 중복 인식한
    # 지저분한 후보까지 끼어들어 정보 증가 없이 토큰만 늘어난다(B에서 실측:
    # +843 토큰, 신규 정보 없음 — p.5/p.43에 이미 깨끗한 표가 있었음).
    fee_range = set(range(summary["start"], summary["end"] + 1))
    if fee_sec := by_key.get((2, 13)):
        fee_range |= set(range(fee_sec["start"], fee_sec["end"] + 1))

    if not any("총보수" in t for pno in fee_range for t in tables.get(pno, [])):
        merge_tables(tables, extract_fee_tables(pdf_path, fee_range))

    if not any("총보수" in t for pno in fee_range for t in tables.get(pno, [])):
        raise SectionMismatch(
            f"[{sample}] 요약정보·제2부13 범위(p{sorted(fee_range)})에서 '총보수' "
            f"표를 찾지 못했습니다. pdfplumber가 표로 인식하지 못하는 레이아웃일 "
            f"수 있으니 수동으로 확인하세요."
        )

    blocks = [page_block(i, t, tables.get(i, [])) for i, t in enumerate(pages, 1)]
    corpus = "\n".join(blocks)
    (TEXT_DIR / f"{sample}.corpus.txt").write_text(corpus, encoding="utf-8")

    (SEC_DIR / f"{sample}.map.json").write_text(
        json.dumps([summary] + sections, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    wide = C2_SECTIONS
    narrow = [p for p in C2_SECTIONS if (p[0], p[1]) not in C2_NARROW_EXCLUDE]

    variants = {}
    for name, picks in [("c2_wide", wide), ("c2_narrow", narrow)]:
        chosen, missing = resolve_sections(by_key, picks, sample)
        text = "\n".join(
            "".join(blocks[s["start"] - 1 : s["end"]]) for s in [summary] + chosen
        )
        (SEC_DIR / f"{sample}.{name}.txt").write_text(text, encoding="utf-8")
        variants[name] = {"tokens": len(ENC.encode(text)), "missing": missing}

    c1 = len(ENC.encode(corpus))
    return {
        "sample": sample,
        "page_count": len(pages),
        "toc_page": toc_page,
        "section_count": len(sections),
        "toc_pages": toc_end - toc_page + 1,
        # 제목이 목차와 어긋나 번호로만 확정한 섹션. 사람이 눈으로 볼 것.
        "title_unverified": [
            f"제{s['bu']}부-{s['num']}" for s in sections if not s.get("title_verified")
        ],
        "table_pages": len(tables),
        "c1_tokens": c1,
        **{
            k: {**v, "ratio_of_c1": round(v["tokens"] / c1, 2)}
            for k, v in variants.items()
        },
    }


def main() -> None:
    TEXT_DIR.mkdir(exist_ok=True)
    SEC_DIR.mkdir(exist_ok=True)
    report = [build(s, f) for s, f in SAMPLES.items()]
    (SEC_DIR / "corpus_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"{'':2} {'섹션':>4} {'C1':>8} {'C2-wide':>10} {'C2-narrow':>12}")
    for r in report:
        w, n = r["c2_wide"], r["c2_narrow"]
        print(
            f"{r['sample']:2} {r['section_count']:>4} {r['c1_tokens']:>8,} "
            f"{w['tokens']:>7,}({w['ratio_of_c1']:.0%}) {n['tokens']:>8,}({n['ratio_of_c1']:.0%})"
        )
        for k, v in (("wide", w), ("narrow", n)):
            if v["missing"]:
                print(f"     !! c2_{k} 누락 섹션: {v['missing']}")
        if r["title_unverified"]:
            print(f"     ?  제목 미확인(번호로만 확정): {', '.join(r['title_unverified'])}")


if __name__ == "__main__":
    main()
