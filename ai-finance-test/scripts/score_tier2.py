"""Tier2 응답(raw/*.json)을 ground_truth_tier2.json으로 채점한다."""

import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from score_extraction import find_evidence, normalize_text

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
CORPUS_DIR = ROOT / "text"
GROUND_TRUTH_PATH = ROOT / "ground_truth_tier2.json"
RESULTS_CSV = ROOT / "results_tier2_field.csv"
RUNS_CSV = ROOT / "runs.csv"

HEADER = [
    "run_id", "sample", "condition", "field", "is_core", "ai_value",
    "expected_value", "match_raw", "is_null", "evidence_text",
    "evidence_found", "evidence_page",
]


def condition_of(run_id: str) -> str:
    parts = run_id.split("_")
    return "_".join(parts[1:-2])


def canonical_asset(value: str, aliases: dict[str, list[str]]) -> str | None:
    normalized = normalize_text(value).lower()
    for canonical, variants in aliases.items():
        if normalized in {normalize_text(v).lower() for v in variants}:
            return canonical
    return None


def canonical_assets(value: str, aliases: dict[str, list[str]]) -> list[str | None]:
    if normalize_text(value).lower() == normalize_text("현금성 자산 및 채권").lower():
        return ["현금성 자산", "채권"]
    return [canonical_asset(value, aliases)]


def matches(field: str, actual, expected, aliases: dict[str, list[str]]) -> int:
    if field == "주요투자자산":
        if not isinstance(actual, list):
            return 0
        normalized = [asset for value in actual for asset in canonical_assets(value, aliases)]
        return int(None not in normalized and set(normalized) == set(expected))
    if field == "거래상대방" and isinstance(expected, list):
        return int(isinstance(actual, list) and set(actual) == set(expected) and len(actual) == len(set(actual)))
    return int(actual == expected)


def score_run(run_id: str, gt: dict) -> list[dict]:
    sample = run_id.split("_", 1)[0]
    if sample not in gt["samples"]:
        return []
    raw_path = RAW_DIR / f"{run_id}.json"
    try:
        response = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    values = response.get("값", {})
    evidence = response.get("근거", {})
    core_fields = gt["_meta"]["core_fields"]
    fields = core_fields + gt["_meta"]["supporting_fields"]
    if not set(fields).issubset(values):
        return []

    corpus_path = CORPUS_DIR / f"{sample}.corpus.txt"
    corpus = corpus_path.read_text(encoding="utf-8") if corpus_path.exists() else ""
    rows = []
    for field in fields:
        actual = values.get(field)
        expected = gt["samples"][sample][field]
        evidence_obj = evidence.get(field) or {}
        evidence_text = evidence_obj.get("원문")
        found = 0
        if actual is not None and evidence_text:
            found = int(find_evidence(corpus, evidence_text)[0])
        rows.append({
            "run_id": run_id,
            "sample": sample,
            "condition": condition_of(run_id),
            "field": field,
            "is_core": int(field in core_fields),
            "ai_value": json.dumps(actual, ensure_ascii=False) if actual is not None else "null",
            "expected_value": json.dumps(expected, ensure_ascii=False) if expected is not None else "null",
            "match_raw": matches(field, actual, expected, gt["asset_aliases"]),
            "is_null": int(actual is None),
            "evidence_text": evidence_text or "",
            "evidence_found": found,
            "evidence_page": evidence_obj.get("페이지") or "",
        })
    return rows


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", help="runs.csv의 prompt_version으로 대상 실행을 제한")
    args = parser.parse_args()
    gt = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    allowed_runs = None
    if args.prompt:
        with RUNS_CSV.open(encoding="utf-8", newline="") as f:
            allowed_runs = {
                row["run_id"] for row in csv.DictReader(f)
                if row["prompt_version"] == args.prompt and row["json_parse_ok"] == "1"
            }
    rows = []
    for path in sorted(RAW_DIR.glob("*.json")):
        if allowed_runs is not None and path.stem not in allowed_runs:
            continue
        scored = score_run(path.stem, gt)
        if scored:
            print(f"채점: {path.stem}")
            rows.extend(scored)

    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)

    core = [row for row in rows if row["is_core"]]
    support = [row for row in rows if not row["is_core"]]
    print(f"Tier2 핵심: {sum(r['match_raw'] for r in core)}/{len(core)}")
    print(f"거래상대방 보조: {sum(r['match_raw'] for r in support)}/{len(support)}")
    print(f"근거 실재성: {sum(r['evidence_found'] for r in rows if not r['is_null'])}/{sum(not r['is_null'] for r in rows)}")


if __name__ == "__main__":
    main()
