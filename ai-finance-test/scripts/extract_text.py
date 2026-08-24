"""작업순서 1: PDF → 전문 텍스트 추출 + 토큰 수 실측.

출력:
  text/{A,B,C}.txt        페이지 마커 포함 전문 텍스트 (C1 조건 입력용)
  text/{A,B,C}.pages.json 페이지별 텍스트 (근거 페이지 역추적용)
  text/extract_report.json 토큰/페이지/스캔본 여부 실측치

C1(전문 통째 투입) 성립 여부는 이 스크립트의 토큰 실측 결과로 판정한다.
"""

import json
import pathlib
import sys

import pymupdf
import tiktoken

ROOT = pathlib.Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "docs" / "prospectus"
OUT_DIR = ROOT / "text"

# 샘플 ID → 실제 PDF 파일명. PDF 원본은 docs/prospectus/ 에 고정, 수정 금지.
SAMPLES = {
    "A": "TIGER 미국S&P500 레버리지(합성 H)_투자설명서.pdf",
    "B": "TIGER 배당커버드콜액티브_투자설명서.pdf",
    "C": "TIGER TDF2045 적격_투자설명서.pdf",
    # D는 held-out 검증용. build_corpus.py 주석 참조.
    "D": "투자설명서_미래에셋tiger200선물레버리지증권상장지수투자신탁(주식-파생형)_20260626_k55301bo0239.pdf",
}

PAGE_MARKER = "\n\n===== [PAGE {n}] =====\n\n"

# 스캔본 판정: 페이지당 문자 수가 이 값 미만이면 텍스트 레이어 없음으로 간주
EMPTY_PAGE_CHARS = 30


def count_tokens(text: str) -> dict[str, int]:
    return {
        "o200k_base": len(tiktoken.get_encoding("o200k_base").encode(text)),
        "cl100k_base": len(tiktoken.get_encoding("cl100k_base").encode(text)),
    }


def extract(sample: str, filename: str) -> dict:
    pdf_path = PDF_DIR / filename
    if not pdf_path.exists():
        sys.exit(f"PDF 없음: {pdf_path}")

    doc = pymupdf.open(pdf_path)
    pages = [page.get_text("text") for page in doc]
    doc.close()

    full_text = "".join(
        PAGE_MARKER.format(n=i + 1) + t for i, t in enumerate(pages)
    )

    (OUT_DIR / f"{sample}.txt").write_text(full_text, encoding="utf-8")
    (OUT_DIR / f"{sample}.pages.json").write_text(
        json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    page_chars = [len(t.strip()) for t in pages]
    empty_pages = [i + 1 for i, c in enumerate(page_chars) if c < EMPTY_PAGE_CHARS]

    return {
        "sample": sample,
        "pdf": filename,
        "pdf_size_mb": round(pdf_path.stat().st_size / 1024 / 1024, 2),
        "page_count": len(pages),
        "char_count": len(full_text),
        "tokens": count_tokens(full_text),
        "chars_per_page_min": min(page_chars),
        "chars_per_page_median": sorted(page_chars)[len(page_chars) // 2],
        "chars_per_page_max": max(page_chars),
        "empty_page_count": len(empty_pages),
        "empty_pages": empty_pages[:20],
    }


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    report = [extract(s, f) for s, f in SAMPLES.items()]
    (OUT_DIR / "extract_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"{'':2} {'pages':>6} {'chars':>9} {'o200k':>9} {'cl100k':>9} {'빈페이지':>8}")
    for r in report:
        print(
            f"{r['sample']:2} {r['page_count']:>6} {r['char_count']:>9,} "
            f"{r['tokens']['o200k_base']:>9,} {r['tokens']['cl100k_base']:>9,} "
            f"{r['empty_page_count']:>8}"
        )


if __name__ == "__main__":
    main()
