"""CLI for Phase 7 immutable Gold Benchmark evaluation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Sequence
from .gold_benchmark import BenchmarkError, evaluate_gold_benchmark, verify_benchmark_report
from .hybrid_retrieval import RetrievalError
from .strict_qa import StrictQAError


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-gold-benchmark",
        description="Run or verify immutable Gold Benchmark gates for strict QA.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="evaluate a JSONL Gold set")
    run.add_argument("database", type=Path)
    run.add_argument("gold", type=Path)
    run.add_argument("--index-report", type=Path)
    run.add_argument("--profile", choices=("smoke", "release"), default="smoke")
    run.add_argument("--output", type=Path)
    verify = subparsers.add_parser("verify", help="recompute and verify a benchmark report")
    verify.add_argument("database", type=Path)
    verify.add_argument("gold", type=Path)
    verify.add_argument("benchmark_report", type=Path)
    verify.add_argument("--index-report", type=Path)
    verify.add_argument("--require-profile", choices=("smoke", "release"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            report = evaluate_gold_benchmark(
                args.database,
                args.gold,
                profile=args.profile,
                report_path=args.index_report,
            )
            payload = report.to_dict()
            if args.output is not None:
                _write_json(args.output, payload)
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0 if report.passed else 2
        result = verify_benchmark_report(
            args.database,
            args.gold,
            args.benchmark_report,
            index_report_path=args.index_report,
            expected_profile=args.require_profile,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0 if result.accepted else 2
    except (OSError, UnicodeError, RetrievalError, StrictQAError, BenchmarkError) as exc:
        raise SystemExit(f"Gold Benchmark failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
