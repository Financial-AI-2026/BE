from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from extraction.fetch.dart import OpenDartError, run_dart_spike, run_domestic_dart_pdf_spike
from extraction.fetch.krx import DataGoKrError, sync_universe
from extraction.fetch.sec import SecEdgarError, fetch_and_save_summary_prospectus
from extraction.fetch.us_universe import NasdaqTraderError
from extraction.fetch.us_universe import sync_universe as sync_us_universe
from extraction.paths import OUT_DIR
from extraction.reporting import write_markdown_report
from extraction.scoring import (
    DOMESTIC_CODES,
    score_outputs,
    summarize_reproducibility,
    write_reproducibility_report,
    write_score_report,
)
from extraction.service import extract_profile, extract_us_profile, parse_document


def is_us_code(code: str) -> bool:
    seed_path = Path("app") / "seed" / "etfs" / f"{code}.json"
    if not seed_path.exists():
        return False
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    return data.get("master", {}).get("market") == "US"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m extraction")
    sub = parser.add_subparsers(dest="command", required=True)

    parse_cmd = sub.add_parser("parse")
    parse_cmd.add_argument("--code", required=True)

    fetch_cmd = sub.add_parser("fetch")
    fetch_cmd.add_argument("--source", choices=["dart", "sec"], required=True)
    fetch_cmd.add_argument("--code")
    fetch_cmd.add_argument("--all", action="store_true")
    fetch_cmd.add_argument("--product-name")
    fetch_cmd.add_argument("--manager-query", default="미래에셋자산운용")
    fetch_cmd.add_argument("--bgn-de", default="20240101")
    fetch_cmd.add_argument("--end-de")
    fetch_cmd.add_argument("--download-limit", type=int, default=3)

    extract_cmd = sub.add_parser("extract")
    extract_cmd.add_argument("--code")
    extract_cmd.add_argument("--all", action="store_true")

    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("--code", required=True)

    score_cmd = sub.add_parser("score")
    score_cmd.add_argument("--code", action="append", dest="codes")

    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("--code", required=True)
    verify_cmd.add_argument("--runs", type=int, default=3)

    krx_universe_cmd = sub.add_parser("krx-universe")
    krx_universe_cmd.add_argument("--bas-dd")

    us_universe_cmd = sub.add_parser("us-universe")
    us_universe_cmd.add_argument("--as-of", help="YYYYMMDD (기본: 오늘)")

    args = parser.parse_args()
    try:
        if args.command == "fetch" and args.source == "sec":
            if not args.code:
                raise SystemExit("--code is required (US code == SEC ticker, e.g. QYLD)")
            path = fetch_and_save_summary_prospectus(args.code, args.code)
            print(f"sec fetch {args.code}: saved -> {path}")
        elif args.command == "fetch":
            if args.all:
                results = run_domestic_dart_pdf_spike(
                    bgn_de=args.bgn_de,
                    end_de=args.end_de,
                    download_limit=args.download_limit,
                )
                for result in results:
                    report = (
                        f"extraction/reports/opendart_spike/{result['code']}/spike_result.md"
                    )
                    print(
                        f"opendart spike {result['code']}: "
                        f"{result['mappingConclusion']} -> {report}"
                    )
            else:
                if not args.code:
                    raise SystemExit("--code or --all is required")
                result = run_dart_spike(
                    code=args.code,
                    product_name=args.product_name,
                    manager_query=args.manager_query,
                    bgn_de=args.bgn_de,
                    end_de=args.end_de,
                    download_limit=args.download_limit,
                )
                report = f"extraction/reports/opendart_spike/{args.code}/spike_result.md"
                print(
                    f"opendart spike {args.code}: "
                    f"{result['mappingConclusion']} -> {report}"
                )
        elif args.command == "parse":
            parse_document(args.code)
            print(f"parsed {args.code}")
        elif args.command == "extract":
            if args.all:
                codes = ["418660", "441680", "435420", "133690", "448290", "102110"]
            else:
                codes = [args.code]
            if not all(codes):
                raise SystemExit("--code or --all is required")
            for code in codes:
                result = extract_us_profile(code) if is_us_code(code) else extract_profile(code)
                write_markdown_report(result)
                print(f"extracted {code}: validationPassed={result.validationPassed}")
        elif args.command == "report":
            data = json.loads((OUT_DIR / f"{args.code}.json").read_text(encoding="utf-8"))
            from extraction.schemas import ExtractionResult

            path = write_markdown_report(ExtractionResult.model_validate(data))
            print(path)
        elif args.command == "score":
            codes = tuple(args.codes) if args.codes else DOMESTIC_CODES
            score = score_outputs(codes=codes)
            _, md_path = write_score_report(score)
            print(f"score {score.passed}/{score.total} ({score.rate:.1%}) -> {md_path}")
        elif args.command == "verify":
            if args.runs < 1:
                raise SystemExit("--runs must be >= 1")
            extract_fn = extract_us_profile if is_us_code(args.code) else extract_profile
            results = [extract_fn(args.code, write_output=False) for _ in range(args.runs)]
            rows = summarize_reproducibility(results)
            _, md_path = write_reproducibility_report(args.code, rows)
            print(f"verified {args.code} runs={args.runs} -> {md_path}")
        elif args.command == "krx-universe":
            result = sync_universe(bas_dd=args.bas_dd)
            print(
                f"krx-universe {result['basDd']}: count={result['count']} "
                f"-> {result['snapshotPath']}"
            )
            if result["comparedTo"] is None:
                print("  no prior snapshot to diff against")
            else:
                print(f"  compared to {result['comparedTo']}")
                for listing in result["added"]:
                    print(f"  + {listing['code']} {listing['name']}")
                for code in result["removedCodes"]:
                    print(f"  - {code} (candidate delisting, confirm over several days)")
        elif args.command == "us-universe":
            as_of = args.as_of or date.today().strftime("%Y%m%d")
            result = sync_us_universe(as_of=as_of)
            print(f"us-universe {result['asOf']}: count={result['count']} -> {result['snapshotPath']}")
    except (OpenDartError, DataGoKrError, SecEdgarError, NasdaqTraderError, Exception) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
