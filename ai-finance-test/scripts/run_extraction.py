"""작업순서 5: 프롬프트 실행 — A 1종 파일럿부터 본 실행(27회)까지 같은 함수로 처리.

사용:
  파일럿 1회:  .venv/bin/python scripts/run_extraction.py --pilot
  본 실행:     .venv/bin/python scripts/run_extraction.py --full

출력:
  raw/{run_id}.json   응답 원문 그대로
  runs.csv            실행 단위 로그 (CLAUDE.md 스키마)
"""

import argparse
import csv
import json
import pathlib
import sys
import time

import yaml
from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from schema_tier1 import build_schema as build_tier1_schema
from schema_tier12 import build_schema as build_tier12_schema

ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PROMPTS_DIR = ROOT / "prompts"
RAW_DIR = ROOT / "raw"
RUNS_CSV = ROOT / "runs.csv"

RUNS_CSV_HEADER = [
    "run_id", "timestamp", "model", "condition", "sample", "repeat",
    "prompt_version", "latency_sec", "input_tokens", "output_tokens",
    "json_parse_ok", "raw_response_path",
]

CONDITION_INPUT = {
    "C1": ROOT / "text" / "{sample}.corpus.txt",
    "C2_wide": ROOT / "sections" / "{sample}.c2_wide.txt",
    "C2_narrow": ROOT / "sections" / "{sample}.c2_narrow.txt",
}


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def read_corpus(sample: str, condition: str) -> str:
    path = pathlib.Path(str(CONDITION_INPUT[condition]).format(sample=sample))
    if not path.exists():
        sys.exit(f"입력 파일 없음: {path} — scripts/build_corpus.py를 먼저 실행하세요.")
    return path.read_text(encoding="utf-8")


def run_once(
    client: OpenAI, model_cfg: dict, sample: str, condition: str, repeat: int,
    prompt_version: str, schema_version: str,
) -> dict:
    corpus = read_corpus(sample, condition)
    prompt_path = PROMPTS_DIR / f"{prompt_version}.md"
    if not prompt_path.exists():
        sys.exit(f"프롬프트 없음: {prompt_path}")
    instructions = prompt_path.read_text(encoding="utf-8")
    schema = build_tier12_schema() if schema_version == "tier12" else build_tier1_schema()

    run_id = f"{sample}_{condition}_r{repeat}_{int(time.time())}"
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=model_cfg["name"],
            reasoning_effort=model_cfg["reasoning_effort"],
            seed=model_cfg["seed"],
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": corpus},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": f"{schema_version}_extraction",
                    "schema": schema,
                    "strict": True,
                },
            },
        )
    except Exception as e:
        latency = time.perf_counter() - t0
        print(f"  !! API 호출 실패: {e}")
        return {
            "run_id": run_id, "timestamp": int(time.time()), "model": model_cfg["name"],
            "condition": condition, "sample": sample, "repeat": repeat,
            "prompt_version": prompt_version, "latency_sec": round(latency, 2),
            "input_tokens": None, "output_tokens": None,
            "json_parse_ok": 0, "raw_response_path": None,
        }
    latency = time.perf_counter() - t0

    raw_text = resp.choices[0].message.content
    RAW_DIR.mkdir(exist_ok=True)
    raw_path = RAW_DIR / f"{run_id}.json"
    raw_path.write_text(raw_text or "", encoding="utf-8")

    try:
        parsed = json.loads(raw_text)
        parse_ok = 1
    except (json.JSONDecodeError, TypeError):
        parsed = None
        parse_ok = 0

    row = {
        "run_id": run_id,
        "timestamp": int(time.time()),
        "model": model_cfg["name"],
        "condition": condition,
        "sample": sample,
        "repeat": repeat,
        "prompt_version": prompt_version,
        "latency_sec": round(latency, 2),
        "input_tokens": resp.usage.prompt_tokens if resp.usage else None,
        "output_tokens": resp.usage.completion_tokens if resp.usage else None,
        "json_parse_ok": parse_ok,
        "raw_response_path": str(raw_path.relative_to(ROOT)),
    }

    print(f"  [{run_id}] {latency:.1f}s  in={row['input_tokens']} out={row['output_tokens']} "
          f"parse_ok={parse_ok}")
    if parsed:
        for k, v in parsed.get("값", {}).items():
            print(f"      {k}: {v!r}")
    return row


def append_runs_csv(rows: list[dict]) -> None:
    is_new = not RUNS_CSV.exists()
    with RUNS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RUNS_CSV_HEADER)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", action="store_true", help="A × C1 × 1회만 실행")
    mode.add_argument("--full", action="store_true", help="3조건 × 3샘플 × 3반복 = 27회")
    # held-out 샘플(D 등)은 config.yaml의 samples에 넣지 않는다. 넣으면 --full의
    # 정의(27회)가 바뀌어 기존 baseline과 비교가 끊긴다. 대신 여기서 직접 지정한다.
    mode.add_argument("--sample", help="샘플 1종만 실행 (예: D). --condition/--repeats와 함께 사용")
    ap.add_argument("--condition", default="C2_wide", help="--sample과 함께 쓸 조건 (기본 C2_wide)")
    ap.add_argument("--repeats", type=int, default=3, help="--sample과 함께 쓸 반복 횟수 (기본 3)")
    ap.add_argument("--prompt", default="v1_tier1", help="prompts/ 아래 파일명(확장자 제외). 기본 v1_tier1")
    ap.add_argument("--schema", choices=["tier1", "tier12"], default="tier1", help="Structured Outputs 스키마")
    args = ap.parse_args()

    cfg = load_config()
    client = OpenAI()  # OPENAI_API_KEY는 .env에서 load_dotenv로 이미 로드됨

    if args.pilot:
        plan = [("A", "C1", 1)]
    elif args.sample:
        plan = [(args.sample, args.condition, r) for r in range(1, args.repeats + 1)]
    else:
        plan = [
            (s["id"], c["id"], r)
            for s in cfg["samples"]
            for c in cfg["conditions"]
            for r in range(1, cfg["repeats"] + 1)
        ]

    print(f"실행 계획: {len(plan)}건 (모델={cfg['model']['name']}, "
          f"reasoning_effort={cfg['model']['reasoning_effort']}, 프롬프트={args.prompt}, 스키마={args.schema})")

    rows = []
    for sample, condition, repeat in plan:
        print(f"\n{sample} / {condition} / repeat {repeat}")
        rows.append(run_once(client, cfg["model"], sample, condition, repeat, args.prompt, args.schema))

    append_runs_csv(rows)
    print(f"\nruns.csv에 {len(rows)}행 기록 완료.")
    fail = [r for r in rows if not r["json_parse_ok"]]
    if fail:
        print(f"!! json_parse_ok=0인 실행 {len(fail)}건: {[r['run_id'] for r in fail]}")


if __name__ == "__main__":
    main()
