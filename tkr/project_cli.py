"""Unified CLI for recoverable evidence-bound typed knowledge projects."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
from typing import Sequence

from .engineering import build_engineered_project, load_engineering_profile
from .knowledge_project import verify_knowledge_project
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
            "Build, verify, and query one recoverable evidence-bound typed knowledge project. "
            "This command does not perform final project acceptance."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a cached and recoverable self-contained project")
    build.add_argument("source", type=Path)
    build.add_argument("--outdir", type=Path, required=True)
    build.add_argument(
        "--profile",
        default="balanced",
        help="built-in profile name or a path to a strict engineering profile JSON",
    )
    build.add_argument("--state-dir", type=Path, help="mutable lock, journal, and cache directory")
    build.add_argument("--index-mode", choices=("review", "canonical"))
    build.add_argument("--max-candidates", type=int)
    build.add_argument("--max-findings", type=int)
    build.add_argument("--max-model-tasks", type=int)
    build.add_argument("--max-clause-characters", type=int)
    build.add_argument("--no-model-tasks", action="store_true")
    build.add_argument("--no-cache", action="store_true", help="disable verified content-addressed cache reuse")
    build.add_argument("--no-resume", action="store_true", help="skip orphan backup and stale workspace recovery")
    build.add_argument(
        "--recover-stale-lock",
        action="store_true",
        help="remove a sufficiently old lock only when its recorded process is not alive",
    )
    mode = build.add_mutually_exclusive_group()
    mode.add_argument("--reuse", action="store_true", help="reuse an exact verified existing project")
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


def _selected_profile(args) -> object:
    profile = load_engineering_profile(args.profile)
    overrides: dict[str, object] = {}
    for argument, field in (
        (args.index_mode, "index_mode"),
        (args.max_candidates, "max_candidates"),
        (args.max_findings, "max_findings"),
        (args.max_model_tasks, "max_model_tasks"),
        (args.max_clause_characters, "max_clause_characters"),
    ):
        if argument is not None:
            overrides[field] = argument
    if args.no_model_tasks:
        overrides["emit_model_tasks"] = False
    return replace(profile, **overrides) if overrides else profile


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_engineered_project(
                args.source,
                args.outdir,
                profile=_selected_profile(args),
                state_directory=args.state_dir,
                reuse_existing=args.reuse,
                replace_existing=args.force,
                use_cache=not args.no_cache,
                resume=not args.no_resume,
                recover_stale_lock=args.recover_stale_lock,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
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
