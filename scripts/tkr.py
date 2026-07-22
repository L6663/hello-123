#!/usr/bin/env python3
"""Self-contained entry point for the Text Knowledge Reader Agent Skill."""
from __future__ import annotations

from pathlib import Path
import sys

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from tkr.project_cli import main as project_main  # noqa: E402
from tkr.skill_cli import main as skill_main  # noqa: E402

SKILL_COMMANDS = {"doctor", "audit", "profiles", "show-profile"}
PROJECT_COMMANDS = {"build", "verify", "query", "verify-answer"}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(
            "Text Knowledge Reader commands:\n"
            "  doctor | audit | profiles | show-profile\n"
            "  build | verify | query | verify-answer\n\n"
            "Examples:\n"
            "  python scripts/tkr.py doctor\n"
            "  python scripts/tkr.py build corpus.txt --outdir project --profile balanced\n"
            "  python scripts/tkr.py verify project\n"
            "  python scripts/tkr.py query project '陆川击败了谁？'"
        )
        return 0

    command = args[0]
    if command in SKILL_COMMANDS:
        if command in {"doctor", "audit"} and "--root" not in args:
            args.extend(["--root", str(SKILL_ROOT)])
        return skill_main(args)
    if command in PROJECT_COMMANDS:
        return project_main(args)
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
