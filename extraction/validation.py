from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.domain.enums import Distribution, FxHedge, Market, Replication, Strategy
from extraction.parsers.base import Section
from extraction.schemas import (
    PERFORMANCE_DEPENDENT_FIELDS,
    TIER1_FIELDS,
    EvidenceItem,
    ExtractionResult,
    ProductProfile,
    SourceMetadata,
    ValidationIssue,
)

RULE_BASED_LOCATION = "규칙 기반 보정 (원문에 직접 서술 없음)"


class ExtractionValidationError(RuntimeError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__("Extraction validation failed")


@dataclass(frozen=True)
class NameCorrection:
    field: str
    value: Any
    original: Any


def validate_payload(
    *,
    code: str,
    raw_payload: dict[str, Any],
    sections: list[Section],
    source: SourceMetadata | None,
    model: str,
    prompt_version: str,
) -> ExtractionResult:
    try:
        profile = ProductProfile.model_validate(raw_payload)
    except ValidationError as exc:
        issues = [
            ValidationIssue(field="schema", code="SCHEMA_INVALID", message=str(exc.errors()))
        ]
        raise ExtractionValidationError(issues) from exc

    issues: list[ValidationIssue] = []
    issues.extend(apply_master_overrides(code, profile))
    issues.extend(normalize_profile_fields(profile))
    issues.extend(apply_us_fx_hedge_default(profile))
    # KR-only: these rules match Korean fund-naming markers ("(합성)", "(H)") and
    # fire wrongly on US names (e.g. every US name lacks "(합성)", so the blanket
    # "no marker -> PHYSICAL" rule would force-flip a correctly-extracted SYNTHETIC
    # US fund back to PHYSICAL). US corrections are handled by the market-aware
    # enforce_leveraged_synthetic_replication / apply_us_fx_hedge_default instead.
    corrections = apply_name_corrections(profile) if profile.market == Market.KR else []
    for correction in corrections:
        issues.append(
            ValidationIssue(
                field=correction.field,
                code="NAME_CORRECTION_CONFLICT",
                message=f"LLM value {correction.original!r} replaced with {correction.value!r}",
            )
        )
    # after name corrections, since those can flip strategy to/from LEVERAGE/INVERSE
    # (e.g. "레버리지" in the product name) -- this must see the final strategy.
    issues.extend(enforce_leverage_default(profile))
    issues.extend(enforce_leveraged_synthetic_replication(profile))
    issues.extend(enforce_daily_rebalancing_default(profile))
    issues.extend(enforce_counterparty_risk_default(profile))
    issues.extend(enforce_issuer_disclosure_field_scope(profile))
    issues.extend(supplement_evidence(profile))
    issues.extend(repair_or_drop_unsupported_evidence(profile, sections))
    issues.extend(_validate_required_evidence(profile))
    issues.extend(_validate_quotes(profile, sections))

    nonfatal = {
        "BASE_INDEX_NORMALIZED",
        "MASTER_CODE_OVERRIDDEN",
        "NAME_CORRECTION_CONFLICT",
        "REPLICATION_EVIDENCE_DERIVED",
        "TIER2_EVIDENCE_DROPPED",
        "TOTAL_EXPENSE_EVIDENCE_REPAIRED",
        "LEVERAGE_EVIDENCE_DERIVED",
        "STRATEGY_EVIDENCE_DERIVED",
        "LEVERAGE_FORCED_TO_ONE",
        "FX_HEDGE_DERIVED",
        "REPLICATION_FORCED_TO_SYNTHETIC",
        "EVIDENCE_QUOTE_REALIGNED",
        "DAILY_REBALANCING_DERIVED",
        "COUNTERPARTY_RISK_DERIVED",
    }
    failed = [issue for issue in issues if issue.code not in nonfatal]
    return ExtractionResult(
        code=code,
        profile=profile,
        validationPassed=not failed,
        issues=issues,
        source=source,
        model=model,
        promptVersion=prompt_version,
    )


def apply_name_corrections(profile: ProductProfile) -> list[NameCorrection]:
    name = profile.name
    corrections: list[NameCorrection] = []

    rules: list[tuple[bool, str, Any]] = [
        ("(합성)" in name, "replication", Replication.SYNTHETIC),
        ("(합성)" not in name and "합성)" not in name, "replication", Replication.PHYSICAL),
        ("(H)" in name, "fxHedge", FxHedge.HEDGED),
        (
            any(token in name for token in ("레버리지", "2X", "UltraPro", "Ultra")),
            "strategy",
            Strategy.LEVERAGE,
        ),
        (any(token in name for token in ("인버스", "Short")), "strategy", Strategy.INVERSE),
        (
            any(token in name for token in ("커버드콜", "Covered Call")),
            "strategy",
            Strategy.COVERED_CALL,
        ),
        ("채권혼합" in name, "strategy", Strategy.MIXED_ASSET),
        ("TR" in name, "distribution", Distribution.NONE),
        ("액티브" in name, "isActive", True),
    ]

    target_year = _target_year_from_name(name)
    if target_year is not None:
        rules.append((True, "strategy", Strategy.TARGET_DATE))
        rules.append((True, "targetYear", target_year))

    for matched, field, value in rules:
        if not matched:
            continue
        original = getattr(profile, field)
        if original != value:
            setattr(profile, field, value)
            corrections.append(NameCorrection(field=field, value=value, original=original))
    return corrections


def enforce_issuer_disclosure_field_scope(profile: ProductProfile) -> list[ValidationIssue]:
    """sourceType="ISSUER_DISCLOSURE" (the issuer's
    legally-mandated disclosure area, not marketing copy) is accepted as evidence only
    for PERFORMANCE_DEPENDENT_FIELDS -- values that genuinely don't belong in a
    prospectus because they depend on operating results, not a fixed contractual term.
    Every other Tier1 field (baseIndex/replication/leverage/strategy/fxHedge/name) must
    still be backed by the prospectus itself; keep this exception narrow so fail-closed
    doesn't quietly erode field by field."""
    issues: list[ValidationIssue] = []
    kept: list[EvidenceItem] = []
    for item in profile.evidence:
        if (
            item.sourceType == "ISSUER_DISCLOSURE"
            and item.field not in PERFORMANCE_DEPENDENT_FIELDS
        ):
            issues.append(
                ValidationIssue(
                    field=item.field,
                    code="ISSUER_DISCLOSURE_OUT_OF_SCOPE",
                    message=(
                        f"ISSUER_DISCLOSURE evidence for {item.field!r} dropped: this "
                        "source is only accepted for performance-dependent fields "
                        f"{PERFORMANCE_DEPENDENT_FIELDS}"
                    ),
                )
            )
            continue
        kept.append(item)
    profile.evidence = kept
    return issues


def normalize_quote(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def apply_master_overrides(code: str, profile: ProductProfile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if profile.code != code:
        original = profile.code
        profile.code = code
        issues.append(
            ValidationIssue(
                field="code",
                code="MASTER_CODE_OVERRIDDEN",
                message=f"LLM value {original!r} replaced with master code {code!r}",
            )
        )
    return issues


def normalize_profile_fields(profile: ProductProfile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    normalized_base_index = normalize_base_index(profile.baseIndex)
    if normalized_base_index != profile.baseIndex:
        original = profile.baseIndex
        profile.baseIndex = normalized_base_index
        issues.append(
            ValidationIssue(
                field="baseIndex",
                code="BASE_INDEX_NORMALIZED",
                message=f"LLM value {original!r} normalized to {normalized_base_index!r}",
            )
        )
    return issues


def enforce_leverage_default(profile: ProductProfile) -> list[ValidationIssue]:
    """leverage is a category default, not a document fact, for anything that
    isn't a leveraged/inverse product -- no other strategy implies a non-1x
    daily target. US active/index funds routinely never mention "leverage" in
    their own text at all (e.g. ARKK), so asking the LLM to state 1.0 with
    evidence is asking it to find something that isn't there.

    Must run after apply_name_corrections, which can flip strategy to/from
    LEVERAGE/INVERSE based on the product name (e.g. "레버리지" in the name)."""
    if profile.strategy in (Strategy.LEVERAGE, Strategy.INVERSE) or profile.leverage == 1.0:
        return []
    original_leverage = profile.leverage
    profile.leverage = 1.0
    return [
        ValidationIssue(
            field="leverage",
            code="LEVERAGE_FORCED_TO_ONE",
            message=(
                f"LLM value {original_leverage!r} overridden to 1.0: strategy "
                f"{profile.strategy!r} is not leveraged/inverse"
            ),
        )
    ]


def enforce_leveraged_synthetic_replication(profile: ProductProfile) -> list[ValidationIssue]:
    """Leveraged/inverse funds achieve their daily-multiple target via swaps and
    futures in practice -- every sample in this project's KR and US data confirms
    this, with no counterexample. The LLM has a strong, reproducible bias toward
    reading "Equity Securities" language in these documents (direct holdings used
    as swap collateral, or a minor allocation) as literal physical replication --
    confirmed 10/10 across two independent 5-run reproducibility checks on TQQQ,
    even after adding schema-description guidance. A softer prompt hint wasn't
    enough, so (like leverage) this is enforced as a rule rather than left to the
    model. Must run after apply_name_corrections for the same reason as
    enforce_leverage_default."""
    if profile.strategy not in (Strategy.LEVERAGE, Strategy.INVERSE):
        return []
    if profile.replication == Replication.SYNTHETIC:
        return []
    original = profile.replication
    profile.replication = Replication.SYNTHETIC
    profile.evidence = [item for item in profile.evidence if item.field != "replication"]
    swap_evidence = next(
        (
            item
            for item in profile.evidence
            if any(
                term in (item.quoteOriginal or "").lower() or term in item.quote.lower()
                for term in ("swap", "futures", "스왑", "선물")
            )
        ),
        None,
    )
    if swap_evidence is not None:
        profile.evidence.append(
            EvidenceItem(
                field="replication",
                quote=swap_evidence.quote,
                quoteOriginal=swap_evidence.quoteOriginal,
                location=swap_evidence.location,
                sourceType=swap_evidence.sourceType,
                translated=swap_evidence.translated,
            )
        )
    else:
        fallback_source_type = (
            profile.evidence[0].sourceType if profile.evidence else "US_SUMMARY_PROSPECTUS"
        )
        profile.evidence.append(
            EvidenceItem(
                field="replication",
                quote=(
                    "레버리지/인버스 상품은 배수 달성을 위해 스왑·선물 계약을 사용하므로 "
                    "규칙 기반으로 합성 판정."
                ),
                location=RULE_BASED_LOCATION,
                sourceType=fallback_source_type,
                translated=True,
            )
        )
    return [
        ValidationIssue(
            field="replication",
            code="REPLICATION_FORCED_TO_SYNTHETIC",
            message=(
                f"LLM value {original!r} overridden to 합성: strategy "
                f"{profile.strategy!r} implies swap/futures-based exposure"
            ),
        )
    ]


def enforce_daily_rebalancing_default(profile: ProductProfile) -> list[ValidationIssue]:
    """dailyRebalancing, like leverage, is a category default rather than a fact
    every document states -- only leveraged/inverse funds rebalance daily to hold
    a fixed daily multiple; a plain index-tracking or covered-call fund has no
    "rebalancing" concept to disclose at all, so the LLM correctly has nothing to
    quote and leaves the field null. Observed live 2026-09-02: 5 of 7 species left
    this null, and the 2 that did answer (418660, TQQQ, both leveraged) matched
    this exact rule -- no counterexample. Must run after apply_name_corrections /
    enforce_leverage_default, for the same reason those must."""
    expected = profile.strategy in (Strategy.LEVERAGE, Strategy.INVERSE)
    if profile.dailyRebalancing == expected:
        return []
    original = profile.dailyRebalancing
    profile.dailyRebalancing = expected
    return [
        ValidationIssue(
            field="dailyRebalancing",
            code="DAILY_REBALANCING_DERIVED",
            message=(
                f"LLM value {original!r} overridden to {expected!r}: strategy "
                f"{profile.strategy!r} determines whether daily rebalancing applies"
            ),
        )
    ]


def enforce_counterparty_risk_default(profile: ProductProfile) -> list[ValidationIssue]:
    """counterpartyRisk tracks replication method, not a document fact -- a
    synthetic (swap/futures-based) fund has real counterparty exposure; a
    physical-replication fund generally does not. Observed live 2026-09-02: the
    LLM produced false positives on 2 of 7 species (133690, 435420, both 실물)
    by reading generic KRX regulatory boilerplate ("what a synthetic ETF's
    counterparty must meet, if it uses one") as if it described this specific
    fund. Across all 7 species, replication predicted the correct answer with no
    counterexample once those false positives are corrected. Must run after
    enforce_leveraged_synthetic_replication, which can still flip replication."""
    expected = profile.replication == Replication.SYNTHETIC
    if profile.counterpartyRisk == expected:
        return []
    original = profile.counterpartyRisk
    profile.counterpartyRisk = expected
    if not expected:
        profile.evidence = [item for item in profile.evidence if item.field != "counterpartyRisk"]
    return [
        ValidationIssue(
            field="counterpartyRisk",
            code="COUNTERPARTY_RISK_DERIVED",
            message=(
                f"LLM value {original!r} overridden to {expected!r}: replication "
                f"{profile.replication!r} determines counterparty exposure"
            ),
        )
    ]


def apply_us_fx_hedge_default(profile: ProductProfile) -> list[ValidationIssue]:
    """A US-domiciled, USD-denominated fund's own SEC prospectus has no reason to
    discuss KRW/USD hedging -- that concept only exists from a Korean investor's
    frame, so an honest read of the document alone correctly answers '해당없음'.
    For our app the right answer is 미헤지 by definition unless the fund explicitly
    hedges (which would show up in its own text, e.g. "(H)"/"Hedged" funds)."""
    if profile.market != Market.US:
        return []
    has_fx_evidence = any(
        item.field == "fxHedge" and item.quote.strip() for item in profile.evidence
    )
    # Nothing to do if the LLM already answered 미헤지/헤지 *with* supporting evidence
    # (e.g. it quoted explicit hedge language) -- only 해당없음, or an unsupported
    # answer with no evidence at all, needs the rule-based default + evidence below.
    if profile.fxHedge != FxHedge.NOT_APPLICABLE and has_fx_evidence:
        return []
    explicit_hedge_terms = ("currency hedge", "fx hedge", "hedged share class")
    already_explicit = any(
        term in (item.quoteOriginal or item.quote).lower()
        for item in profile.evidence
        for term in explicit_hedge_terms
    )
    if already_explicit:
        return []
    profile.fxHedge = FxHedge.UNHEDGED
    profile.evidence = [item for item in profile.evidence if item.field != "fxHedge"]
    profile.evidence.append(
        EvidenceItem(
            field="fxHedge",
            quote=(
                "USD 표시 미국 상장 상품이며 원문에 환헤지 서술 없음 — 원화 투자자 기준 "
                "미헤지로 규칙 기반 판정."
            ),
            location=RULE_BASED_LOCATION,
            sourceType="US_SUMMARY_PROSPECTUS",
            translated=True,
        )
    )
    return [
        ValidationIssue(
            field="fxHedge",
            code="FX_HEDGE_DERIVED",
            message="US fund with no hedge disclosure defaulted to 미헤지 for KRW investors",
        )
    ]


def supplement_evidence(profile: ProductProfile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    by_field = {item.field: item for item in profile.evidence if item.quote.strip()}
    if (
        profile.strategy == Strategy.LEVERAGE
        and "strategy" not in by_field
        and "leverage" in by_field
    ):
        leverage_evidence = by_field["leverage"]
        profile.evidence.append(
            EvidenceItem(
                field="strategy",
                quote=leverage_evidence.quote,
                quoteOriginal=leverage_evidence.quoteOriginal,
                location=leverage_evidence.location,
                sourceType=leverage_evidence.sourceType,
                translated=leverage_evidence.translated,
            )
        )
        issues.append(
            ValidationIssue(
                field="strategy",
                code="STRATEGY_EVIDENCE_DERIVED",
                message="Derived strategy evidence from leverage evidence for leverage strategy",
            )
        )
    if profile.leverage == 1.0 and "leverage" not in by_field:
        source = by_field.get("strategy") or by_field.get("baseIndex")
        if source is not None:
            profile.evidence.append(
                EvidenceItem(
                    field="leverage",
                    quote=source.quote,
                    quoteOriginal=source.quoteOriginal,
                    location=source.location,
                    sourceType=source.sourceType,
                    translated=source.translated,
                )
            )
            issues.append(
                ValidationIssue(
                    field="leverage",
                    code="LEVERAGE_EVIDENCE_DERIVED",
                    message="Derived 1.0 leverage evidence from index-tracking strategy evidence",
                )
            )
    if (
        profile.replication == Replication.PHYSICAL
        and "replication" not in by_field
        and (source := by_field.get("strategy") or by_field.get("mainAssets"))
    ):
        profile.evidence.append(
            EvidenceItem(
                field="replication",
                quote=source.quote,
                quoteOriginal=source.quoteOriginal,
                location=source.location,
                sourceType=source.sourceType,
                translated=source.translated,
            )
        )
        issues.append(
            ValidationIssue(
                field="replication",
                code="REPLICATION_EVIDENCE_DERIVED",
                message=(
                    "Derived physical replication evidence from direct investment "
                    "strategy evidence"
                ),
            )
        )
    return issues


SENTENCE_MATCH_THRESHOLD = 0.72


def _split_sentences(sections: list[Section]) -> list[str]:
    """Split section text into sentence-level candidates for fuzzy matching.

    Source text extracted from HTML/PDF often has whitespace/newlines mid-
    sentence (e.g. a "®" glyph rendered as its own <font> tag on its own
    line) -- collapse all runs of whitespace to a single space first so a
    sentence's parts are compared as one contiguous candidate, not shredded
    into fragments too short to fuzzy-match against.
    """
    sentences: list[str] = []
    for section in sections:
        collapsed = re.sub(r"\s+", " ", section.text)
        for raw in re.split(r"(?<=[.!?])\s+", collapsed):
            candidate = raw.strip()
            if candidate:
                sentences.append(candidate)
    return sentences


def _find_best_matching_sentence(source_text: str, sections: list[Section]) -> str | None:
    """Recover the true verbatim source sentence for a paraphrased LLM quote.

    Observed live 2026-09-02 on TQQQ: the LLM copied the Investment Objective
    sentence near-verbatim into quoteOriginal but silently substituted the
    fund's full name ("ProShares UltraPro QQQ (the "Fund")") with "The Fund"
    -- a paraphrase, not a literal quote, despite the prompt instructing no
    changes. Rather than fail-closed on evidence that is 95% correct, look up
    the actual closest sentence in the corpus and use its real wording. If no
    sentence is close enough, this returns None and the caller keeps failing
    closed as before.
    """
    normalized_target = normalize_quote(source_text)
    best_sentence: str | None = None
    best_ratio = 0.0
    for sentence in _split_sentences(sections):
        ratio = difflib.SequenceMatcher(
            None, normalize_quote(sentence), normalized_target
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_sentence = sentence
    if best_sentence is not None and best_ratio >= SENTENCE_MATCH_THRESHOLD:
        return best_sentence
    return None


def repair_or_drop_unsupported_evidence(
    profile: ProductProfile, sections: list[Section]
) -> list[ValidationIssue]:
    corpus = normalize_quote("\n".join(section.text for section in sections))
    issues: list[ValidationIssue] = []
    kept: list[EvidenceItem] = []
    for item in profile.evidence:
        source_text = _source_text(item)
        if item.sourceType == "ISSUER_DISCLOSURE":
            kept.append(item)  # not from this corpus by design (Q10) -- nothing to repair
            continue
        if not source_text.strip() or normalize_quote(source_text) in corpus:
            kept.append(item)
            continue
        if item.field == "totalExpense" and (
            repaired := _find_total_expense_quote(profile, sections)
        ):
            kept.append(repaired)
            issues.append(
                ValidationIssue(
                    field="totalExpense",
                    code="TOTAL_EXPENSE_EVIDENCE_REPAIRED",
                    message="Replaced totalExpense evidence with a source table row",
                )
            )
            continue
        if item.field == "replication" and profile.replication == Replication.PHYSICAL:
            if repaired_replication := _find_physical_replication_quote(profile):
                kept.append(repaired_replication)
                issues.append(
                    ValidationIssue(
                        field="replication",
                        code="REPLICATION_EVIDENCE_DERIVED",
                        message=(
                            "Replaced unsupported replication evidence with direct "
                            "investment strategy evidence"
                        ),
                    )
                )
                continue
        if item.field in TIER1_FIELDS and (
            matched_sentence := _find_best_matching_sentence(source_text, sections)
        ):
            kept.append(
                item.model_copy(update={"quoteOriginal": matched_sentence})
                if item.quoteOriginal is not None
                else item.model_copy(update={"quote": matched_sentence})
            )
            issues.append(
                ValidationIssue(
                    field=item.field,
                    code="EVIDENCE_QUOTE_REALIGNED",
                    message=(
                        f"LLM quote for {item.field} paraphrased the source; replaced "
                        "with the closest verbatim source sentence"
                    ),
                )
            )
            continue
        if item.field not in TIER1_FIELDS:
            issues.append(
                ValidationIssue(
                    field=item.field,
                    code="TIER2_EVIDENCE_DROPPED",
                    message="Dropped unsupported non-Tier1 evidence quote",
                )
            )
            continue
        kept.append(item)
    profile.evidence = kept
    return issues


def normalize_base_index(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = normalized.replace("®", "")
    normalized = re.sub(r"^The\s+", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*\([^)]*원화환산[^)]*\)", "", normalized)
    normalized = re.sub(r"\s*\((Total Return|총수익지수)\)", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*지수$", "", normalized)
    normalized = re.sub(r"\s*Index$", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^CBOE\b", "Cboe", normalized)
    if normalized == "KOSPI 200":
        return "코스피200"
    if normalized == "Cboe Nasdaq-100 BuyWrite V2":
        return "Cboe Nasdaq-100 BuyWrite V2 (TR)"
    if "나스닥100채권혼합50" in normalized:
        return "나스닥100 + 국내채권 혼합 (5:5)"
    return re.sub(r"\s+", " ", normalized).strip()


def _find_total_expense_quote(
    profile: ProductProfile, sections: list[Section]
) -> EvidenceItem | None:
    value = str(profile.totalExpense).rstrip("0").rstrip(".")
    for section in sections:
        for line in section.text.splitlines():
            has_fee_context = "총보수" in section.text or "총 보수" in section.text
            if "투자신탁" in line and value in line and has_fee_context:
                return EvidenceItem(
                    field="totalExpense",
                    quote=line.strip(),
                    location=section.location,
                    sourceType="KR_PROSPECTUS",
                    translated=False,
                )
    return None


def _find_physical_replication_quote(profile: ProductProfile) -> EvidenceItem | None:
    for item in profile.evidence:
        if item.field in {"strategy", "mainAssets"} and item.quote.strip():
            return EvidenceItem(
                field="replication",
                quote=item.quote,
                location=item.location,
                sourceType=item.sourceType,
                translated=item.translated,
            )
    return None


def _validate_required_evidence(profile: ProductProfile) -> list[ValidationIssue]:
    by_field = {item.field for item in profile.evidence if item.quote.strip()}
    return [
        ValidationIssue(
            field=field,
            code="EVIDENCE_MISSING",
            message=f"Tier1 field {field} has no evidence quote",
        )
        for field in TIER1_FIELDS
        if field not in by_field
    ]


def _source_text(item: EvidenceItem) -> str:
    """The literal-quote text to check against the source corpus.

    For KR evidence, `quote` already *is* the literal Korean source text.
    For US evidence, `quote` is a Korean *translation* -- it can never appear
    in the English source corpus, so a Korean quote alone made this check
    fail-closed on every correctly-translated run and only pass when the LLM
    left the quote untranslated (a bug, not a feature). `quoteOriginal` holds
    the untranslated literal sentence and is what must be checked instead.
    """
    return item.quoteOriginal or item.quote


def _validate_quotes(profile: ProductProfile, sections: list[Section]) -> list[ValidationIssue]:
    corpus = normalize_quote("\n".join(section.text for section in sections))
    issues: list[ValidationIssue] = []
    for item in profile.evidence:
        if item.location == RULE_BASED_LOCATION:
            continue  # labeled as a rule-based inference, not a literal quote
        if item.sourceType == "ISSUER_DISCLOSURE":
            continue  # not from the prospectus corpus by design (Q10) -- nothing to match
        quote = _source_text(item).strip()
        if quote and normalize_quote(quote) not in corpus:
            issues.append(
                ValidationIssue(
                    field=item.field,
                    code="QUOTE_NOT_FOUND",
                    message=f"Evidence quote for {item.field} does not exist in source text",
                )
            )
    return issues


def _target_year_from_name(name: str) -> int | None:
    if "TDF" not in name:
        return None
    match = re.search(r"(20\d{2})", name)
    return int(match.group(1)) if match else None
