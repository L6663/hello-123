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
from tkr.notion_cli import main as notion_main  # noqa: E402
from tkr.project_cli import main as project_main  # noqa: E402
from tkr.reasoning_cli import main as reasoning_main  # noqa: E402
from tkr.skill_cli import main as skill_main  # noqa: E402

SKILL_COMMANDS = {"doctor", "audit", "profiles", "show-profile"}
PROJECT_COMMANDS = {"build", "verify", "query", "verify-answer"}
LITERARY_ALIASES = {
    "literary-build": "build",
    "literary-verify": "verify",
    "literary-query": "query",
    "literary-export-notion": "export-notion",
}
EVIDENCE_ALIASES = {"evidence-build": "build", "evidence-verify": "verify"}
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
REASONING_ALIASES = {
    "reasoning-build": "build",
    "reasoning-verify": "verify",
    "reasoning-query": "query",
    "reason-build": "build",
    "reason-verify": "verify",
    "reason-query": "query",
}
NOTION_ALIASES = {
    "notion-build": "build",
    "notion-verify": "verify",
    "notion-plan": "plan",
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
            "  reason build | reason verify | reason query\n"
            "  notion build | notion verify | notion plan\n"
            "  aliases: literary-*, evidence-*, chapter-*, event-*, character-*, reason-*, notion-*\n\n"
            "Reasoning query modes:\n"
            "  fact_only | fact_and_synthesis | analysis | counterfactual | provenance\n\n"
            "Examples:\n"
            "  python scripts/tkr.py doctor\n"
            "  python scripts/tkr.py build corpus.txt --outdir project --profile balanced\n"
            "  python scripts/tkr.py verify project\n"
            "  python scripts/tkr.py literary build project --outdir literary\n"
            "  python scripts/tkr.py evidence build project literary --outdir evidence-project\n"
            "  python scripts/tkr.py chapter build project-a project-b --outdir chapter-project\n"
            "  python scripts/tkr.py event --help\n"
            "  python scripts/tkr.py character --help\n"
            "  python scripts/tkr.py reason --help\n"
            "  python scripts/tkr.py notion --help"
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
        return literary_main(["--help"] if len(args) == 1 else args[1:])
    if command in LITERARY_ALIASES:
        return literary_main([LITERARY_ALIASES[command], *args[1:]])
    if command == "evidence":
        return evidence_main(["--help"] if len(args) == 1 else args[1:])
    if command in EVIDENCE_ALIASES:
        return evidence_main([EVIDENCE_ALIASES[command], *args[1:]])
    if command == "chapter":
        return chapter_main(["--help"] if len(args) == 1 else args[1:])
    if command in CHAPTER_ALIASES:
        return chapter_main([CHAPTER_ALIASES[command], *args[1:]])
    if command == "event":
        return event_main(["--help"] if len(args) == 1 else args[1:])
    if command in EVENT_ALIASES:
        return event_main([EVENT_ALIASES[command], *args[1:]])
    if command == "character":
        return character_main(["--help"] if len(args) == 1 else args[1:])
    if command in CHARACTER_ALIASES:
        return character_main([CHARACTER_ALIASES[command], *args[1:]])
    if command in {"reason", "reasoning"}:
        return reasoning_main(["--help"] if len(args) == 1 else args[1:])
    if command in REASONING_ALIASES:
        return reasoning_main([REASONING_ALIASES[command], *args[1:]])
    if command == "notion":
        return notion_main(["--help"] if len(args) == 1 else args[1:])
    if command in NOTION_ALIASES:
        return notion_main([NOTION_ALIASES[command], *args[1:]])
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
