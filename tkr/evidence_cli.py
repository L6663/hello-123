"""Command line interface for the Stage 1 Evidence Engine project."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .evidence_project import build_evidence_project, verify_evidence_project


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
        prog="tkr-evidence",
        description=(
            "Build and verify a deterministic Evidence Engine project from a verified "
            "source project and its literary sidecar. This command has no project-"
            "acceptance, release, or freeze authority."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a complete Evidence Engine project")
    build.add_argument("source_project", type=Path)
    build.add_argument("literary_project", type=Path)
    build.add_argument("--outdir", type=Path, required=True)
    build.add_argument("--target-chars", type=int, default=900)
    build.add_argument("--max-chars", type=int, default=1500)
    build.add_argument("--force", action="store_true")

    verify = commands.add_parser("verify", help="verify source bindings, graph, SQLite, and hashes")
    verify.add_argument("source_project", type=Path)
    verify.add_argument("literary_project", type=Path)
    verify.add_argument("evidence_project", type=Path)
    verify.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_evidence_project(
                args.source_project,
                args.literary_project,
                args.outdir,
                target_chars=args.target_chars,
                max_chars=args.max_chars,
                replace_existing=args.force,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
            return 0
        verification = verify_evidence_project(
            args.source_project,
            args.literary_project,
            args.evidence_project,
        )
        _write_json(args.output, verification.to_dict())
        return 0 if verification.valid else 2
    except (OSError, UnicodeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"Evidence Engine failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
