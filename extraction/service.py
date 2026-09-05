from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from extraction.parsers.base import PageText, Section
from extraction.parsers.kr_prospectus import C2_SECTIONS, KrProspectusParser
from extraction.parsers.us_summary import UsSummaryParser
from extraction.paths import INTERIM_DIR, OUT_DIR, RAW_DIR, ensure_output_dirs
from extraction.schemas import ExtractionResult, SourceMetadata
from extraction.validation import validate_payload

PROMPT_VERSION = "v6_tier12_product_kr_v1"
US_PROMPT_VERSION = "v1_tier1_product_us_v1"
DEFAULT_MODEL = "gpt-5-mini"


class LlmClient(Protocol):
    model: str

    def extract(self, prompt: str, context: str) -> dict[str, Any]:
        ...


class OpenAiStructuredClient:
    model = DEFAULT_MODEL

    def __init__(
        self, *, market: str = "KR", reasoning_effort: str = "medium", seed: int = 42
    ) -> None:
        try:
            from dotenv import load_dotenv
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError("openai package is required for real extraction runs") from exc
        load_dotenv()
        self._client = OpenAI()
        self._market = market
        self._reasoning_effort = reasoning_effort
        self._seed = seed

    def extract(self, prompt: str, context: str) -> dict[str, Any]:
        if self._market == "US":
            schema_name, schema = "us_etf_profile", _us_openai_profile_schema()
        else:
            schema_name, schema = "kr_etf_profile", _openai_profile_schema()
        response = self._client.chat.completions.create(
            model=self.model,
            reasoning_effort=self._reasoning_effort,
            seed=self._seed,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": context},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI response was empty")
        return json.loads(content)


def parse_document(
    code: str, *, pdf_path: Path | None = None
) -> tuple[list[PageText], list[Section]]:
    ensure_output_dirs()
    source = pdf_path or find_source_pdf(code)
    parser = KrProspectusParser()
    pages, report = parser.extract_pages(source, code)
    sections = parser.split_sections(pages)
    _write_json(INTERIM_DIR / f"{code}.pages.json", [page.__dict__ for page in pages])
    _write_json(INTERIM_DIR / f"{code}.parse-report.json", report.__dict__)
    _write_json(INTERIM_DIR / f"{code}.sections.json", [section.__dict__ for section in sections])
    (INTERIM_DIR / f"{code}.text.txt").write_text(_format_pages(pages), encoding="utf-8")
    return pages, sections


def extract_profile(
    code: str,
    *,
    sections: list[Section] | None = None,
    llm_client: LlmClient | None = None,
    source: SourceMetadata | None = None,
    write_output: bool = True,
) -> ExtractionResult:
    ensure_output_dirs()
    if sections is None:
        _, sections = parse_document(code)
    client = llm_client or OpenAiStructuredClient()
    context = build_c2_wide_context(sections)
    payload = client.extract(_prompt(code), context)
    result = validate_payload(
        code=code,
        raw_payload=payload,
        sections=sections,
        source=source or load_source_metadata(code),
        model=client.model,
        prompt_version=PROMPT_VERSION,
    )
    if write_output:
        _write_json(OUT_DIR / f"{code}.json", result.model_dump(mode="json"))
    return result


def parse_us_document(
    code: str, *, html_path: Path | None = None
) -> tuple[list[PageText], list[Section]]:
    ensure_output_dirs()
    source = html_path or find_source_html(code)
    parser = UsSummaryParser()
    pages, report = parser.extract_pages(source, code)
    sections = parser.split_sections(pages)
    _write_json(INTERIM_DIR / f"{code}.pages.json", [page.__dict__ for page in pages])
    _write_json(INTERIM_DIR / f"{code}.parse-report.json", report.__dict__)
    _write_json(INTERIM_DIR / f"{code}.sections.json", [section.__dict__ for section in sections])
    (INTERIM_DIR / f"{code}.text.txt").write_text(_format_pages(pages), encoding="utf-8")
    return pages, sections


def extract_us_profile(
    code: str,
    *,
    sections: list[Section] | None = None,
    llm_client: LlmClient | None = None,
    source: SourceMetadata | None = None,
    write_output: bool = True,
) -> ExtractionResult:
    ensure_output_dirs()
    if sections is None:
        _, sections = parse_us_document(code)
    client = llm_client or OpenAiStructuredClient(market="US")
    context = build_us_context(sections)
    payload = client.extract(_us_prompt(code), context)
    result = validate_payload(
        code=code,
        raw_payload=payload,
        sections=sections,
        source=source or load_source_metadata(code),
        model=client.model,
        prompt_version=US_PROMPT_VERSION,
    )
    if write_output:
        _write_json(OUT_DIR / f"{code}.json", result.model_dump(mode="json"))
    return result


def build_us_context(sections: list[Section]) -> str:
    # No precise section splitting for US docs (see UsSummaryParser docstring) --
    # these are short enough that the whole cleaned text is the context.
    return "\n\n".join(section.text for section in sections)


def find_source_html(code: str) -> Path:
    raw_dir = RAW_DIR / code
    candidates = sorted(path for path in raw_dir.glob("*.htm*") if path.is_file())
    if not candidates:
        raise FileNotFoundError(f"No HTML source found under {raw_dir}")
    return candidates[0]


def _us_prompt(code: str) -> str:
    return (
        "미국 ETF의 SEC 요약투자설명서(Summary Prospectus) 영문 원문에서 제품 스키마 JSON만 "
        f"추출한다. code 필드는 사용자가 지정한 티커 {code}를 그대로 반환한다. "
        "근거는 두 가지를 함께 채운다: quoteOriginal에는 원문(영문) 문장을 한 글자도 고치지 "
        "않고 그대로 넣고, quote에는 그 문장을 한국어로 번역해서 넣는다. translated는 항상 "
        "true로 한다. quoteOriginal은 요약·재작성·번역 없이 원문 그대로여야 하고, quote는 "
        "그 원문의 자연스러운 번역이어야 한다. "
        "찾지 못한 필드는 값을 비우고 근거도 만들지 않는다(환각 금지) — 특히 분배 주기는 "
        "요약투자설명서에 직접 명시된 문장이 없으면 추정하지 말고 값·근거를 비운다. "
        "totalExpense는 'Total Annual Fund Operating Expenses' 표의 값을 사용한다. "
        "enum은 지정된 값만 쓴다(한국어 코드값). replication은 '실물'(직접 자산을 보유) 또는 "
        "'합성'(스왑·선물 등 파생상품으로 노출을 만듦) 중 선택한다."
    )


def _us_openai_profile_schema() -> dict[str, Any]:
    evidence_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "field": {"type": "string"},
            "quote": {
                "type": "string",
                "description": "quoteOriginal의 자연스러운 한국어 번역 (요약·재작성 금지).",
            },
            "quoteOriginal": {
                "type": "string",
                "description": (
                    "원문(영문) 문장을 한 글자도 고치지 않고 그대로 인용한다. 요약·번역·"
                    "재작성하지 않는다 — 검증 로직이 이 문자열이 원문에 실제로 있는지 "
                    "그대로 대조한다."
                ),
            },
            "location": {"type": "string"},
            "sourceType": {"type": "string", "enum": ["US_SUMMARY_PROSPECTUS"]},
            "translated": {"type": "boolean"},
        },
        "required": [
            "field",
            "quote",
            "quoteOriginal",
            "location",
            "sourceType",
            "translated",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "code": {"type": "string"},
            "isin": {"type": ["string", "null"]},
            "market": {"type": "string", "enum": ["US"]},
            "baseIndex": {"type": "string"},
            "replication": {
                "type": "string",
                "enum": ["실물", "합성"],
                "description": (
                    "핵심 판정 기준: 레버리지/인버스 상품(2x/3x/-1x 등 일간 배수 목표)은 배수를 "
                    "달성하기 위해 스왑(swap)·선물(futures) 계약을 반드시 함께 쓴다. 문서에 "
                    "'Equity Securities'(직접 주식 보유) 같은 문구가 같이 나와도, strategy가 "
                    "레버리지/인버스이고 스왑·선물(swap/futures) 계약 언급이 있으면 '합성'을 "
                    "최우선으로 선택한다 — 직접 보유 언급은 스왑의 담보/보조 자산일 뿐 복제방식의 "
                    "정체성이 아니다. 레버리지/인버스가 아닌 펀드에서 지수 구성종목을 그대로 "
                    "보유한다는 설명만 있으면 '실물'이다."
                ),
            },
            "leverage": {
                "type": "number",
                "description": (
                    "일간 변동률 목표 배수. 레버리지/인버스가 아닌 일반 펀드(지수추종·커버드콜· "
                    "액티브 등)는 배수를 항상 1로 반환한다(0이 아니다). '2x daily'면 2, "
                    "'3x daily'면 3, '-1x'(인버스)면 -1."
                ),
            },
            "dailyRebalancing": {"type": ["boolean", "null"]},
            "isActive": {"type": ["boolean", "null"]},
            "strategy": {
                "type": "string",
                "enum": [
                    "지수추종",
                    "레버리지",
                    "인버스",
                    "커버드콜",
                    "자산혼합",
                    "타겟데이트",
                    "액티브",
                    "기타",
                ],
                "description": (
                    "핵심 판정 기준: 콜옵션 매도(sell/write call options, buy-write)가 핵심 "
                    "전략이면 '커버드콜'을 최우선으로 선택한다 — 기초자산을 지수 구성종목대로 "
                    "보유한다는 설명(indexing/replication)이 같이 있어도 마찬가지다. 일간 "
                    "변동률의 배수(2x/3x daily)를 목표로 하면 '레버리지'(양의 배수) 또는 "
                    "'인버스'(음의 배수)를 선택한다. 그런 파생 전략이 전혀 없이 지수를 그대로 "
                    "추종하면 '지수추종'이다."
                ),
            },
            "distribution": {
                "type": "string",
                "enum": ["무분배", "월분배", "분기분배", "반기분배", "연분배"],
                "description": (
                    "분배금 지급 주기. 'monthly'면 월분배, 'quarterly'면 분기분배, 'annually'면 "
                    "연분배. 문서에 명시된 지급 주기 문장을 그대로 근거로 쓰고, 추정하지 않는다."
                ),
            },
            "distributionYield": {"type": ["number", "null"]},
            "targetYear": {"type": ["integer", "null"]},
            "totalExpense": {
                "type": "number",
                "description": (
                    "'Total Annual Fund Operating Expenses' 표의 퍼센트 숫자를 그대로 반환한다. "
                    "예: 문서에 '0.60%'라고 적혀 있으면 0.6을 반환한다 (0.006이 아니다)."
                ),
            },
            "fxHedge": {
                "type": "string",
                "enum": ["헤지", "미헤지", "해당없음"],
                "description": (
                    "환헤지 여부. 문서에 환헤지를 한다는 명시적 서술이 있으면 '헤지'. 그런 서술이 "
                    "없으면 '미헤지'. 국내 자산에만 투자하는 구조일 때만 '해당없음'."
                ),
            },
            "counterpartyRisk": {"type": ["boolean", "null"]},
            "counterparty": {"type": ["string", "null"]},
            "mainAssets": {"type": "array", "items": {"type": "string"}},
            "isComplexProduct": {"type": ["boolean", "null"]},
            "evidence": {"type": "array", "items": evidence_item},
        },
        "required": [
            "name",
            "code",
            "isin",
            "market",
            "baseIndex",
            "replication",
            "leverage",
            "dailyRebalancing",
            "isActive",
            "strategy",
            "distribution",
            "distributionYield",
            "targetYear",
            "totalExpense",
            "fxHedge",
            "counterpartyRisk",
            "counterparty",
            "mainAssets",
            "isComplexProduct",
            "evidence",
        ],
    }


def build_c2_wide_context(sections: list[Section]) -> str:
    if not sections:
        return ""
    picks = {(f"제{bu}부" if bu else None, str(num) if num else None) for bu, num, _ in C2_SECTIONS}
    preferred = [
        section
        for section in sections
        if (section.part, section.clause) in picks
        or any(keyword in section.title for keyword in ("요약정보", "보수", "비용"))
    ]
    selected = preferred or sections
    return "\n\n".join(
        f"[{section.location} / p.{section.page_start}-{section.page_end}]\n{section.text}"
        for section in selected
    )


def find_source_pdf(code: str) -> Path:
    raw_dir = RAW_DIR / code
    candidates = sorted(path for path in raw_dir.glob("*.pdf") if path.is_file())
    if not candidates:
        raise FileNotFoundError(f"No PDF found under {raw_dir}")
    return candidates[0]


def load_source_metadata(code: str) -> SourceMetadata | None:
    path = RAW_DIR / code / "sources.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return None
    return SourceMetadata.model_validate(data)


def _prompt(code: str) -> str:
    return (
        "국내 ETF 투자설명서에서 제품 스키마 JSON만 추출한다. "
        "code 필드는 PDF 내부 펀드코드가 아니라 사용자가 지정한 "
        f"단축코드 {code}를 그대로 반환한다. "
        "근거는 원문 문장 또는 표 행을 그대로 인용하고 찾지 못하면 값을 비운다. "
        "quote에는 말줄임표, 생략, 요약, 재작성, 페이지번호 설명을 넣지 않는다. "
        "quote는 입력 텍스트에 공백 정규화 후 부분 문자열로 실제 존재해야 한다. "
        "distribution은 제2부 14의 분배 지급 주기를 우선한다. "
        "totalExpense는 총보수·비용이 아니라 투자자가 부담하는 수수료 및 총보수 표의 "
        "총보수 값을 사용한다. "
        "isActive는 상품명 또는 본문에 액티브 운용이라고 명시될 때만 true다. "
        "enum은 스키마에 정의된 값만 사용한다. evidence.field는 영문 키를 사용한다."
    )


def _openai_profile_schema() -> dict[str, Any]:
    evidence_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "field": {"type": "string"},
            "quote": {"type": "string"},
            "location": {"type": "string"},
            "sourceType": {"type": "string", "enum": ["KR_PROSPECTUS"]},
            "translated": {"type": "boolean"},
        },
        "required": ["field", "quote", "location", "sourceType", "translated"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "code": {"type": "string"},
            "isin": {"type": ["string", "null"]},
            "market": {"type": "string", "enum": ["KR"]},
            "baseIndex": {"type": "string"},
            "replication": {"type": "string", "enum": ["실물", "합성"]},
            "leverage": {"type": "number"},
            "dailyRebalancing": {"type": ["boolean", "null"]},
            "isActive": {"type": ["boolean", "null"]},
            "strategy": {
                "type": "string",
                "enum": [
                    "지수추종",
                    "레버리지",
                    "인버스",
                    "커버드콜",
                    "자산혼합",
                    "타겟데이트",
                    "액티브",
                    "기타",
                ],
            },
            "distribution": {
                "type": "string",
                "enum": ["무분배", "월분배", "분기분배", "반기분배", "연분배"],
            },
            "distributionYield": {"type": ["number", "null"]},
            "targetYear": {"type": ["integer", "null"]},
            "totalExpense": {"type": "number"},
            "fxHedge": {"type": "string", "enum": ["헤지", "미헤지", "해당없음"]},
            "counterpartyRisk": {"type": ["boolean", "null"]},
            "counterparty": {"type": ["string", "null"]},
            "mainAssets": {"type": "array", "items": {"type": "string"}},
            "isComplexProduct": {"type": ["boolean", "null"]},
            "evidence": {"type": "array", "items": evidence_item},
        },
        "required": [
            "name",
            "code",
            "isin",
            "market",
            "baseIndex",
            "replication",
            "leverage",
            "dailyRebalancing",
            "isActive",
            "strategy",
            "distribution",
            "distributionYield",
            "targetYear",
            "totalExpense",
            "fxHedge",
            "counterpartyRisk",
            "counterparty",
            "mainAssets",
            "isComplexProduct",
            "evidence",
        ],
    }


def _format_pages(pages: list[PageText]) -> str:
    return "\n\n".join(f"[PAGE {page.page}]\n{page.text}" for page in pages)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
