"""Command line interface for the Stage 7 literary knowledge engine."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .literary_engine import build_literary_engine, verify_literary_engine
from .literary_export import export_literary_notion_package
from .literary_query import query_literary_engine


def _write_json(path: Path | None, payload: dict[str, object]) -> None:
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
        prog="tkr-literary",
        description=(
            "Build, verify, query, and export a chapter-addressable A/B/C literary knowledge sidecar. "
            "This command has no project-acceptance or freeze authority."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a literary sidecar from one verified TKR project")
    build.add_argument("project", type=Path)
    build.add_argument("--outdir", type=Path, required=True)
    build.add_argument("--annotations", type=Path)
    build.add_argument("--force", action="store_true")

    verify = commands.add_parser("verify", help="verify sidecar hashes, SQLite integrity, and tier contracts")
    verify.add_argument("sidecar", type=Path)
    verify.add_argument("--output", type=Path)

    query = commands.add_parser("query", help="answer from A/B/C records or refuse")
    query.add_argument("sidecar", type=Path)
    query.add_argument("question")
    query.add_argument("--max-items", type=int, default=20)
    query.add_argument("--max-citations", type=int, default=12)
    query.add_argument("--output", type=Path)

    export = commands.add_parser("export-notion", help="emit a deterministic Notion-ready package")
    export.add_argument("sidecar", type=Path)
    export.add_argument("--outdir", type=Path, required=True)
    export.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_literary_engine(
                args.project,
                args.outdir,
                annotations_path=args.annotations,
                replace_existing=args.force,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "verify":
            result = verify_literary_engine(args.sidecar)
            _write_json(args.output, result.to_dict())
            return 0 if result.valid else 2
        if args.command == "query":
            packet = query_literary_engine(
                args.sidecar,
                args.question,
                max_items=args.max_items,
                max_citations=args.max_citations,
            )
            _write_json(args.output, packet.to_dict())
            return 0
        result = export_literary_notion_package(
            args.sidecar,
            args.outdir,
            replace_existing=args.force,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"literary knowledge engine failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
