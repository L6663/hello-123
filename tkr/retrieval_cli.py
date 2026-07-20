"""CLI for Phase 5 auditable hybrid indexing and predicate retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .hybrid_retrieval import RetrievalError, build_hybrid_index, query_hybrid_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tkr-retrieval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build a hash-verified SQLite retrieval index")
    build.add_argument("source", type=Path)
    build.add_argument("accepted_claims", type=Path)
    build.add_argument("entity_dir", type=Path)
    build.add_argument("--units", type=Path, required=True)
    build.add_argument("--identity-links", type=Path)
    build.add_argument("--database", type=Path, required=True)
    build.add_argument("--report", type=Path)
    build.add_argument("--mode", choices=("review", "canonical"), default="review")
    build.add_argument("--source-id", default="source")

    query = subparsers.add_parser("query", help="query typed facts with conservative answerability")
    query.add_argument("database", type=Path)
    query.add_argument("question")
    query.add_argument("--source-id")
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--report", type=Path)
    query.add_argument(
        "--skip-integrity-check",
        action="store_true",
        help="skip the default database SHA-256 check for trusted interactive use",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            payload = build_hybrid_index(
                args.source,
                args.units,
                args.accepted_claims,
                args.entity_dir,
                args.database,
                identity_links_path=args.identity_links,
                index_mode=args.mode,
                source_id=args.source_id,
                report_path=args.report,
            )
        else:
            payload = query_hybrid_index(
                args.database,
                args.question,
                source_id=args.source_id,
                limit=args.limit,
                verify_database=not args.skip_integrity_check,
                report_path=args.report,
            ).to_dict()
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"retrieval failed: {exc}") from exc
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
