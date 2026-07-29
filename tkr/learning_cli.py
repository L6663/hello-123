"""CLI for Stage 8-R7 learning panorama projects."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .learning_engine import build_learning_project, query_learning_project, verify_learning_project


def _write(path: Path | None, payload: object) -> None:
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
        prog="tkr-learning",
        description=(
            "Build, verify, and query source-bound learning panoramas: chapter cards, "
            "entity trajectories, relationships, events, world model, and evidence-bound model tasks."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("literary_projects", nargs="+", type=Path)
    build.add_argument("--outdir", required=True, type=Path)
    build.add_argument("--source-project", action="append", dest="source_projects", type=Path, default=[])
    build.add_argument("--book-id", action="append", dest="book_ids", default=[])
    build.add_argument("--book-title", action="append", dest="book_titles", default=[])
    build.add_argument("--observations", type=Path)
    build.add_argument("--max-task-evidence", type=int, default=12)
    build.add_argument("--force", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("project", type=Path)
    verify.add_argument("--literary-project", action="append", dest="literary_projects", type=Path, default=[])
    verify.add_argument("--source-project", action="append", dest="source_projects", type=Path, default=[])
    verify.add_argument("--book-id", action="append", dest="book_ids", default=[])
    verify.add_argument("--book-title", action="append", dest="book_titles", default=[])
    verify.add_argument("--output", type=Path)
    query = commands.add_parser("query")
    query.add_argument("project", type=Path)
    query.add_argument("question")
    query.add_argument("--max-items", type=int, default=20)
    query.add_argument("--book-id")
    query.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_learning_project(
                args.literary_projects,
                args.outdir,
                source_projects=args.source_projects,
                book_ids=args.book_ids,
                book_titles=args.book_titles,
                observation_file=args.observations,
                replace_existing=args.force,
                max_task_evidence=args.max_task_evidence,
            )
            _write(None, result.to_dict())
            return 0
        if args.command == "verify":
            result = verify_learning_project(
                args.project,
                args.literary_projects,
                args.source_projects,
                book_ids=args.book_ids,
                book_titles=args.book_titles,
            )
            _write(args.output, result.to_dict())
            return 0 if result.valid else 2
        result = query_learning_project(args.project, args.question, max_items=args.max_items, book_id=args.book_id)
        _write(args.output, result)
        return 0 if result["status"] == "answered" else 2
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"learning panorama failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
