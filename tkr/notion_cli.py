"""CLI for deterministic Stage 6 Notion Knowledge System packages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .notion_project import (
    NotionProjectError,
    build_notion_project,
    verify_notion_project,
)


def _write(payload: object, output: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(output)


def _add_upstream(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("chapter_project", type=Path)
    parser.add_argument("event_project", type=Path)
    parser.add_argument("event_annotations", type=Path)
    parser.add_argument("character_project", type=Path)
    parser.add_argument("character_annotations", type=Path)
    parser.add_argument("reasoning_project", type=Path)
    parser.add_argument("reasoning_annotations", type=Path)
    parser.add_argument(
        "--source-project", action="append", dest="source_projects", type=Path, required=True
    )
    parser.add_argument(
        "--literary-project", action="append", dest="literary_projects", type=Path, required=True
    )
    parser.add_argument(
        "--evidence-binding",
        action="append",
        nargs=3,
        metavar=("SOURCE_PROJECT", "LITERARY_PROJECT", "EVIDENCE_PROJECT"),
        required=True,
    )
    parser.add_argument("--ledger", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-notion",
        description=(
            "Build and verify a stable-key Notion projection and inspect its reversible "
            "incremental sync plan. No remote deletion is performed."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a Notion Project package")
    _add_upstream(build)
    build.add_argument("--outdir", type=Path, required=True)
    build.add_argument("--force", action="store_true")

    verify = commands.add_parser("verify", help="verify a Notion Project package")
    verify.add_argument("notion_project", type=Path)
    _add_upstream(verify)
    verify.add_argument("--output", type=Path)

    plan = commands.add_parser("plan", help="inspect a verified sync plan")
    plan.add_argument("notion_project", type=Path)
    _add_upstream(plan)
    plan.add_argument(
        "--action",
        choices=("create", "update", "noop", "review_missing_remote_id", "archive_candidate"),
    )
    plan.add_argument("--target-type", choices=("page", "relation_set"))
    plan.add_argument("--database-key")
    plan.add_argument("--output", type=Path)
    return parser


def _bindings(values: Sequence[Sequence[str]]) -> tuple[tuple[Path, Path, Path], ...]:
    return tuple((Path(first), Path(second), Path(third)) for first, second, third in values)


def _verify(args: argparse.Namespace):
    return verify_notion_project(
        args.chapter_project,
        args.source_projects,
        args.literary_projects,
        _bindings(args.evidence_binding),
        args.event_project,
        args.event_annotations,
        args.character_project,
        args.character_annotations,
        args.reasoning_project,
        args.reasoning_annotations,
        args.notion_project,
        ledger_path=args.ledger,
    )


def _jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise NotionProjectError(f"blank JSONL record at {path.name}:{line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise NotionProjectError(f"non-object JSONL record at {path.name}:{line_number}")
            rows.append(value)
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_notion_project(
                args.chapter_project,
                args.source_projects,
                args.literary_projects,
                _bindings(args.evidence_binding),
                args.event_project,
                args.event_annotations,
                args.character_project,
                args.character_annotations,
                args.reasoning_project,
                args.reasoning_annotations,
                args.outdir,
                ledger_path=args.ledger,
                replace_existing=args.force,
            )
            _write(result.to_dict(), None)
            return 0
        verification = _verify(args)
        if args.command == "verify":
            _write(verification.to_dict(), args.output)
            return 0 if verification.valid else 2
        base = {
            "schema_version": "tkr-notion-sync-plan-response-v1",
            "notion_project_logical_sha256": verification.logical_sha256,
            "projection_valid": verification.projection_valid,
            "may_delete_remote_pages": False,
            "archive_requires_explicit_approval": True,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        if not verification.valid:
            _write({
                **base,
                "decision": "refused",
                "reason_codes": list(verification.reason_codes),
                "actions": [],
            }, args.output)
            return 2
        pages = _jsonl(args.notion_project / "notion-pages.jsonl")
        page_database = {
            str(item.get("page_key")): str(item.get("database_key"))
            for item in pages
        }
        actions = _jsonl(args.notion_project / "notion-sync-plan.jsonl")
        if args.action:
            actions = [item for item in actions if item.get("action") == args.action]
        if args.target_type:
            actions = [item for item in actions if item.get("target_type") == args.target_type]
        if args.database_key:
            actions = [
                item
                for item in actions
                if page_database.get(str(item.get("target_key"))) == args.database_key
            ]
        _write({
            **base,
            "decision": "answered",
            "action_count": len(actions),
            "actions": actions,
        }, args.output)
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, NotionProjectError, ValueError) as exc:
        raise SystemExit(f"Notion command failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
