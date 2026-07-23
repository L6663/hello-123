"""CLI for the deterministic Stage 7 literary regression benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .literary_benchmark import (
    LiteraryBenchmarkError,
    evaluate_benchmark,
    read_report,
    verify_benchmark_report,
    write_report,
)


def _write(payload: object, path: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-literary-benchmark",
        description=(
            "Evaluate immutable literary Gold cases against already-produced A/B/C/H "
            "answer packets. The evaluator never generates or self-grades answers."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    evaluate = commands.add_parser("evaluate", help="evaluate Gold cases and observations")
    evaluate.add_argument("cases", type=Path)
    evaluate.add_argument("observations", type=Path)
    evaluate.add_argument("--profile", choices=("smoke", "release"), required=True)
    evaluate.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser("verify", help="recompute and verify a benchmark report")
    verify.add_argument("cases", type=Path)
    verify.add_argument("observations", type=Path)
    verify.add_argument("report", type=Path)
    verify.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "evaluate":
            report = evaluate_benchmark(args.cases, args.observations, profile=args.profile)
            write_report(report, args.output)
            _write(report.to_dict(), None)
            return 0 if report.passed else 2

        supplied = read_report(args.report)
        verification = verify_benchmark_report(args.cases, args.observations, supplied)
        _write(verification.to_dict(), args.output)
        return 0 if verification.valid else 2
    except (OSError, UnicodeError, json.JSONDecodeError, LiteraryBenchmarkError) as exc:
        raise SystemExit(f"literary benchmark command failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
