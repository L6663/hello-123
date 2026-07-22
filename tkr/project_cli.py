"""Unified CLI for Stage 4 end-to-end typed knowledge projects."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .knowledge_models import KnowledgeProjectPolicy
from .knowledge_project import build_knowledge_project, verify_knowledge_project
from .knowledge_query import answer_knowledge_project, verify_knowledge_answer


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
        prog="tkr-project",
        description=(
            "Build, verify, and query one evidence-bound typed knowledge project. "
            "This command does not perform final project acceptance."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a self-contained project atomically")
    build.add_argument("source", type=Path)
    build.add_argument("--outdir", type=Path, required=True)
    build.add_argument("--index-mode", choices=("review", "canonical"), default="review")
    build.add_argument("--max-candidates", type=int, default=200_000)
    build.add_argument("--max-findings", type=int, default=50_000)
    build.add_argument("--max-model-tasks", type=int, default=50_000)
    build.add_argument("--max-clause-characters", type=int, default=600)
    build.add_argument("--no-model-tasks", action="store_true")
    mode = build.add_mutually_exclusive_group()
    mode.add_argument("--reuse", action="store_true", help="reuse only after full verification")
    mode.add_argument("--force", action="store_true", help="atomically replace an existing project")

    verify = commands.add_parser("verify", help="verify the complete immutable project hash chain")
    verify.add_argument("project", type=Path)
    verify.add_argument("--output", type=Path)

    query = commands.add_parser("query", help="answer one supported typed question or refuse")
    query.add_argument("project", type=Path)
    query.add_argument("question")
    query.add_argument("--source-id")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--max-citations", type=int, default=5)
    query.add_argument("--output", type=Path)

    check_answer = commands.add_parser("verify-answer", help="recompute a saved Stage 4 answer")
    check_answer.add_argument("project", type=Path)
    check_answer.add_argument("packet", type=Path)
    check_answer.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            report = build_knowledge_project(
                args.source,
                args.outdir,
                policy=KnowledgeProjectPolicy(
                    index_mode=args.index_mode,
                    max_candidates=args.max_candidates,
                    max_findings=args.max_findings,
                    max_model_tasks=args.max_model_tasks,
                    max_clause_characters=args.max_clause_characters,
                    emit_model_tasks=not args.no_model_tasks,
                    reuse_verified_project=args.reuse,
                    replace_existing_project=args.force,
                ),
            )
            payload = report.to_dict()
            payload["project_directory"] = str(args.outdir)
            payload["reused_verified_project"] = bool(args.reuse)
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "verify":
            result = verify_knowledge_project(args.project)
            _write_json(args.output, result.to_dict())
            return 0 if result.valid else 2
        if args.command == "query":
            packet = answer_knowledge_project(
                args.project,
                args.question,
                source_id=args.source_id,
                retrieval_limit=args.limit,
                max_citations=args.max_citations,
            )
            _write_json(args.output, packet.to_dict())
            return 0
        result = verify_knowledge_answer(args.project, args.packet)
        _write_json(args.output, result.to_dict())
        return 0 if result.accepted else 2
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"knowledge project failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
