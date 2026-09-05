from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from extraction.paths import OUT_DIR, REPORTS_DIR, ensure_output_dirs
from extraction.schemas import ExtractionResult

DOMESTIC_CODES = ("418660", "441680", "435420", "133690", "448290", "102110")

PROFILE_SCORE_FIELDS = (
    ("baseIndex", "base_index"),
    ("replication", "replication"),
    ("leverage", "leverage"),
    ("strategy", "strategy"),
    ("distribution", "distribution"),
    ("totalExpense", "total_expense"),
    ("fxHedge", "fx_hedge"),
)

@dataclass(frozen=True)
class FieldScore:
    code: str
    field: str
    expected: Any
    actual: Any
    passed: bool
    note: str | None = None


@dataclass(frozen=True)
class ScoreReport:
    rows: list[FieldScore]
    missing_codes: list[str]

    @property
    def score_rows(self) -> list[FieldScore]:
        return [row for row in self.rows if not row.field.startswith("master.")]

    @property
    def total(self) -> int:
        return len(self.score_rows)

    @property
    def passed(self) -> int:
        return sum(1 for row in self.score_rows if row.passed)

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass(frozen=True)
class ReproducibilityField:
    field: str
    modal_value: Any
    match_count: int
    runs: int

    @property
    def rate(self) -> float:
        return self.match_count / self.runs if self.runs else 0.0


def score_outputs(
    *,
    codes: tuple[str, ...] = DOMESTIC_CODES,
    out_dir: Path = OUT_DIR,
    seed_dir: Path = Path("app/seed/etfs"),
) -> ScoreReport:
    rows: list[FieldScore] = []
    missing_codes: list[str] = []
    for code in codes:
        seed_path = seed_dir / f"{code}.json"
        out_path = out_dir / f"{code}.json"
        if not seed_path.exists() or not out_path.exists():
            missing_codes.append(code)
            rows.extend(_missing_rows(code, seed_path, out_path))
            continue

        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        result = ExtractionResult.model_validate_json(out_path.read_text(encoding="utf-8"))
        rows.extend(score_result(code, seed, result))

    return ScoreReport(
        rows=rows,
        missing_codes=missing_codes,
    )


def score_result(code: str, seed: dict[str, Any], result: ExtractionResult) -> list[FieldScore]:
    profile = result.profile
    expected_profile = seed["profile"]
    rows = []
    for output_field, seed_field in PROFILE_SCORE_FIELDS:
        expected = expected_profile[seed_field]
        actual = getattr(profile, output_field)
        rows.append(
            FieldScore(
                code=code,
                field=output_field,
                expected=expected,
                actual=actual,
                passed=_values_equal(expected, actual),
            )
        )
    rows.extend(_master_sanity_rows(code, seed["master"], result))
    return rows


def summarize_reproducibility(results: list[ExtractionResult]) -> list[ReproducibilityField]:
    if not results:
        return []
    rows: list[ReproducibilityField] = []
    for field, _ in PROFILE_SCORE_FIELDS:
        values = [_jsonable(getattr(result.profile, field)) for result in results]
        modal_value, match_count = Counter(
            json.dumps(value, ensure_ascii=False) for value in values
        ).most_common(1)[0]
        rows.append(
            ReproducibilityField(
                field=field,
                modal_value=json.loads(modal_value),
                match_count=match_count,
                runs=len(results),
            )
        )
    return rows


def write_score_report(report: ScoreReport, output_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    ensure_output_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "score.json"
    md_path = output_dir / "score.md"
    json_path.write_text(
        json.dumps(
            {
                "total": report.total,
                "passed": report.passed,
                "rate": round(report.rate, 4),
                "missingCodes": report.missing_codes,
                "rows": [row.__dict__ for row in report.rows],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path.write_text(_score_markdown(report), encoding="utf-8")
    return json_path, md_path


def write_reproducibility_report(
    code: str, rows: list[ReproducibilityField], output_dir: Path = REPORTS_DIR
) -> tuple[Path, Path]:
    ensure_output_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"reproducibility_{code}.json"
    md_path = output_dir / f"reproducibility_{code}.md"
    json_path.write_text(
        json.dumps(
            {
                "code": code,
                "fields": [
                    {
                        "field": row.field,
                        "modalValue": row.modal_value,
                        "matchCount": row.match_count,
                        "runs": row.runs,
                        "rate": round(row.rate, 4),
                    }
                    for row in rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path.write_text(_reproducibility_markdown(code, rows), encoding="utf-8")
    return json_path, md_path


def _missing_rows(code: str, seed_path: Path, out_path: Path) -> list[FieldScore]:
    note = f"missing seed={not seed_path.exists()} out={not out_path.exists()}"
    return [
        FieldScore(
            code=code,
            field=field,
            expected=None,
            actual=None,
            passed=False,
            note=note,
        )
        for field, _ in PROFILE_SCORE_FIELDS
    ]


def _master_sanity_rows(
    code: str, master: dict[str, Any], result: ExtractionResult
) -> list[FieldScore]:
    profile = result.profile
    extracted_name = _compact_name(profile.name)
    master_tokens = _master_name_tokens(master["name"])
    return [
        FieldScore(
            code=code,
            field="master.code",
            expected=code,
            actual=profile.code,
            passed=profile.code == code,
        ),
        FieldScore(
            code=code,
            field="master.market",
            expected=master["market"],
            actual=profile.market.value,
            passed=profile.market.value == master["market"],
        ),
        FieldScore(
            code=code,
            field="master.name",
            expected=master["name"],
            actual=profile.name,
            passed=all(token in extracted_name for token in master_tokens),
            note="sanity only; does not update etf_master",
        ),
    ]


def _values_equal(expected: Any, actual: Any) -> bool:
    actual = _jsonable(actual)
    if isinstance(expected, (float, int)) and isinstance(actual, (float, int)):
        return abs(float(expected) - float(actual)) < 0.0001
    return expected == actual


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _compact_name(value: str) -> str:
    return re.sub(r"[\s()]", "", value)


def _master_name_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[\s()]+", value) if token]


def _score_markdown(report: ScoreReport) -> str:
    lines = [
        "# Extraction Score Report",
        "",
        f"- passed: {report.passed}/{report.total}",
        f"- rate: {report.rate:.1%}",
        f"- missingCodes: {', '.join(report.missing_codes) if report.missing_codes else 'none'}",
        "",
        "| code | field | passed | expected | actual | note |",
        "| :--- | :--- | :---: | :--- | :--- | :--- |",
    ]
    for row in report.rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.code,
                    row.field,
                    "PASS" if row.passed else "FAIL",
                    str(row.expected),
                    str(row.actual),
                    row.note or "",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _reproducibility_markdown(code: str, rows: list[ReproducibilityField]) -> str:
    lines = [
        f"# {code} Reproducibility Report",
        "",
        "| field | modal value | match count | rate |",
        "| :--- | :--- | :---: | :---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.field} | {row.modal_value} | {row.match_count}/{row.runs} | {row.rate:.1%} |"
        )
    return "\n".join(lines) + "\n"
