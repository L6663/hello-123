"""Command line interface for Phase 6 strict QA packets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .hybrid_retrieval import RetrievalError
from .strict_qa import StrictQAError, answer_strict, verify_strict_packet


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
        prog="tkr-strict-qa",
        description="Generate or verify deterministic evidence-bound QA packets.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    answer = subparsers.add_parser("answer", help="generate a strict answer/refusal packet")
    answer.add_argument("database", type=Path)
    answer.add_argument("question")
    answer.add_argument("--report", type=Path)
    answer.add_argument("--source-id")
    answer.add_argument("--retrieval-limit", type=int, default=20)
    answer.add_argument("--max-citations", type=int, default=5)
    answer.add_argument("--output", type=Path)

    verify = subparsers.add_parser("verify", help="recompute and verify a saved QA packet")
    verify.add_argument("database", type=Path)
    verify.add_argument("packet", type=Path)
    verify.add_argument("--report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "answer":
            packet = answer_strict(
                args.database,
                args.question,
                source_id=args.source_id,
                retrieval_limit=args.retrieval_limit,
                max_citations=args.max_citations,
                report_path=args.report,
            )
            payload = packet.to_dict()
            if args.output is not None:
                _write_json(args.output, payload)
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0

        result = verify_strict_packet(
            args.database,
            args.packet,
            report_path=args.report,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0 if result.accepted else 2
    except (OSError, UnicodeError, RetrievalError, StrictQAError) as exc:
        raise SystemExit(f"strict QA failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
