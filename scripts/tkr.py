#!/usr/bin/env python3
"""Self-contained entry point for the Text Knowledge Reader Agent Skill."""
from __future__ import annotations

from pathlib import Path
import sys

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from tkr.chapter_cli import main as chapter_main  # noqa: E402
from tkr.character_cli import main as character_main  # noqa: E402
from tkr.evidence_cli import main as evidence_main  # noqa: E402
from tkr.event_cli import main as event_main  # noqa: E402
from tkr.literary_cli import main as literary_main  # noqa: E402
from tkr.project_cli import main as project_main  # noqa: E402
from tkr.skill_cli import main as skill_main  # noqa: E402

SKILL_COMMANDS = {"doctor", "audit", "profiles", "show-profile"}
PROJECT_COMMANDS = {"build", "verify", "query", "verify-answer"}
LITERARY_ALIASES = {
    "literary-build": "build",
    "literary-verify": "verify",
    "literary-query": "query",
    "literary-export-notion": "export-notion",
}
EVIDENCE_ALIASES = {
    "evidence-build": "build",
    "evidence-verify": "verify",
}
CHAPTER_ALIASES = {
    "chapter-build": "build",
    "chapter-verify": "verify",
    "chapter-query": "query",
}
EVENT_ALIASES = {
    "event-build": "build",
    "event-verify": "verify",
    "event-query": "query",
}
CHARACTER_ALIASES = {
    "character-build": "build",
    "character-verify": "verify",
    "character-query": "query",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(
            "Text Knowledge Reader commands:\n"
            "  doctor | audit | profiles | show-profile\n"
            "  build | verify | query | verify-answer\n"
            "  literary build | literary verify | literary query | literary export-notion\n"
            "  evidence build | evidence verify\n"
            "  chapter build | chapter verify | chapter query\n"
            "  event build | event verify | event query\n"
            "  character build | character verify | character query\n"
            "  literary-build | literary-verify | literary-query | literary-export-notion\n"
            "  evidence-build | evidence-verify\n"
            "  chapter-build | chapter-verify | chapter-query\n"
            "  event-build | event-verify | event-query\n"
            "  character-build | character-verify | character-query\n\n"
            "Examples:\n"
            "  python scripts/tkr.py doctor\n"
            "  python scripts/tkr.py build corpus.txt --outdir project --profile balanced\n"
            "  python scripts/tkr.py verify project\n"
            "  python scripts/tkr.py query project '陆川击败了谁？'\n"
            "  python scripts/tkr.py literary build project --outdir literary\n"
            "  python scripts/tkr.py evidence build project literary --outdir evidence-project\n"
            "  python scripts/tkr.py chapter build project-a project-b --outdir chapter-project\n"
            "  python scripts/tkr.py event build chapter-project events.jsonl --source-project project-a --source-project project-b --literary-project literary --outdir event-project\n"
            "  python scripts/tkr.py character build chapter-project characters.jsonl --source-project project-a --source-project project-b --literary-project literary --event-project event-project --event-annotations events.jsonl --outdir character-project\n"
            "  python scripts/tkr.py character query character-project chapter-project characters.jsonl --source-project project-a --source-project project-b --literary-project literary --event-project event-project --event-annotations events.jsonl --name '应飞扬' --profile\n"
            "  python scripts/tkr.py literary export-notion literary --outdir notion-package"
        )
        return 0

    command = args[0]
    if command in SKILL_COMMANDS:
        if command in {"doctor", "audit"} and "--root" not in args:
            args.extend(["--root", str(SKILL_ROOT)])
        return skill_main(args)
    if command in PROJECT_COMMANDS:
        return project_main(args)
    if command == "literary":
        if len(args) == 1:
            return literary_main(["--help"])
        return literary_main(args[1:])
    if command in LITERARY_ALIASES:
        return literary_main([LITERARY_ALIASES[command], *args[1:]])
    if command == "evidence":
        if len(args) == 1:
            return evidence_main(["--help"])
        return evidence_main(args[1:])
    if command in EVIDENCE_ALIASES:
        return evidence_main([EVIDENCE_ALIASES[command], *args[1:]])
    if command == "chapter":
        if len(args) == 1:
            return chapter_main(["--help"])
        return chapter_main(args[1:])
    if command in CHAPTER_ALIASES:
        return chapter_main([CHAPTER_ALIASES[command], *args[1:]])
    if command == "event":
        if len(args) == 1:
            return event_main(["--help"])
        return event_main(args[1:])
    if command in EVENT_ALIASES:
        return event_main([EVENT_ALIASES[command], *args[1:]])
    if command == "character":
        if len(args) == 1:
            return character_main(["--help"])
        return character_main(args[1:])
    if command in CHARACTER_ALIASES:
        return character_main([CHARACTER_ALIASES[command], *args[1:]])
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
