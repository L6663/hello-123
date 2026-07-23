"""Command line interface for Stage 2 Chapter Structure projects."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from typing import Sequence

from .chapter_project import (
    ChapterProjectError,
    build_chapter_project,
    verify_chapter_project,
)


def _write(payload: object, output: Path | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-chapter",
        description=(
            "Build, verify, and query a deterministic multi-source chapter catalog. "
            "Canonical order is a reviewable candidate and never rewrites source text."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a Chapter Structure project")
    build.add_argument("source_projects", nargs="+", type=Path)
    build.add_argument("--outdir", type=Path, required=True)
    build.add_argument("--force", action="store_true")

    verify = commands.add_parser("verify", help="verify a Chapter Structure project")
    verify.add_argument("chapter_project", type=Path)
    verify.add_argument(
        "--source-project", dest="source_projects", action="append", type=Path, required=True
    )
    verify.add_argument("--output", type=Path)

    query = commands.add_parser("query", help="query a verified chapter catalog")
    query.add_argument("chapter_project", type=Path)
    query.add_argument(
        "--source-project", dest="source_projects", action="append", type=Path, required=True
    )
    selector = query.add_mutually_exclusive_group(required=True)
    selector.add_argument("--chapter-id")
    selector.add_argument("--rule")
    selector.add_argument("--address", nargs=2, metavar=("VOLUME", "CHAPTER"), type=int)
    query.add_argument("--neighbors", choices=("physical", "canonical"))
    query.add_argument("--output", type=Path)
    return parser


def _row_dict(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    return {description[0]: value for description, value in zip(cursor.description, row)}


def _chapter_by_id(connection: sqlite3.Connection, chapter_id: str) -> dict[str, object] | None:
    cursor = connection.execute("SELECT * FROM chapters WHERE chapter_id=?", (chapter_id,))
    row = cursor.fetchone()
    return _row_dict(cursor, row) if row is not None else None


def _neighbors(
    connection: sqlite3.Connection,
    chapter: dict[str, object],
    mode: str,
) -> dict[str, object]:
    if mode == "physical":
        position = chapter["global_physical_order"]
        column = "global_physical_order"
        table = "chapters"
        id_column = "chapter_id"
    else:
        found = connection.execute(
            "SELECT canonical_position FROM canonical_order WHERE chapter_id=?",
            (chapter["chapter_id"],),
        ).fetchone()
        if found is None:
            return {"previous": None, "next": None}
        position = found[0]
        column = "canonical_position"
        table = "canonical_order"
        id_column = "chapter_id"
    result: dict[str, object] = {}
    for label, delta in (("previous", -1), ("next", 1)):
        found = connection.execute(
            f"SELECT {id_column} FROM {table} WHERE {column}=?",
            (position + delta,),
        ).fetchone()
        result[label] = _chapter_by_id(connection, found[0]) if found else None
    return result


def _query(args: argparse.Namespace) -> dict[str, object]:
    verification = verify_chapter_project(args.source_projects, args.chapter_project)
    if not verification.valid:
        return {
            "schema_version": "tkr-chapter-query-v1",
            "decision": "refused",
            "reason_codes": list(verification.reason_codes),
            "may_present": True,
            "may_accept_project": False,
            "may_freeze": False,
        }
    database = args.chapter_project / "chapter.sqlite"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        if args.address:
            volume, chapter_number = args.address
            cursor = connection.execute(
                "SELECT * FROM chapters WHERE volume_ordinal=? AND chapter_ordinal=? "
                "ORDER BY global_physical_order",
                (volume, chapter_number),
            )
            rows = [_row_dict(cursor, row) for row in cursor.fetchall()]
            return {
                "schema_version": "tkr-chapter-query-v1",
                "decision": "answered" if rows else "refused",
                "query_type": "address",
                "volume_ordinal": volume,
                "chapter_ordinal": chapter_number,
                "chapters": rows,
                "reason_codes": [] if rows else ["CHAPTER_ADDRESS_NOT_FOUND"],
                "may_present": True,
                "may_accept_project": False,
                "may_freeze": False,
            }
        if args.rule:
            cursor = connection.execute(
                "SELECT * FROM findings WHERE rule_id=? ORDER BY finding_id", (args.rule,)
            )
            rows = []
            for row in cursor.fetchall():
                item = _row_dict(cursor, row)
                item["chapter_ids"] = [
                    value[0] for value in connection.execute(
                        "SELECT chapter_id FROM finding_chapters WHERE finding_id=? ORDER BY chapter_id",
                        (item["finding_id"],),
                    )
                ]
                rows.append(item)
            return {
                "schema_version": "tkr-chapter-query-v1",
                "decision": "answered" if rows else "refused",
                "query_type": "finding_rule",
                "rule_id": args.rule,
                "findings": rows,
                "reason_codes": [] if rows else ["CHAPTER_FINDING_RULE_NOT_FOUND"],
                "may_present": True,
                "may_accept_project": False,
                "may_freeze": False,
            }
        chapter = _chapter_by_id(connection, args.chapter_id)
        if chapter is None:
            return {
                "schema_version": "tkr-chapter-query-v1",
                "decision": "refused",
                "query_type": "chapter_id",
                "reason_codes": ["CHAPTER_ID_NOT_FOUND"],
                "may_present": True,
                "may_accept_project": False,
                "may_freeze": False,
            }
        payload: dict[str, object] = {
            "schema_version": "tkr-chapter-query-v1",
            "decision": "answered",
            "query_type": "chapter_id",
            "chapter": chapter,
            "reason_codes": [],
            "may_present": True,
            "may_accept_project": False,
            "may_freeze": False,
        }
        if args.neighbors:
            payload["neighbors"] = _neighbors(connection, chapter, args.neighbors)
            payload["neighbor_basis"] = args.neighbors
        return payload
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            report = build_chapter_project(
                args.source_projects,
                args.outdir,
                replace_existing=args.force,
            )
            _write(report)
            return 0
        if args.command == "verify":
            verification = verify_chapter_project(
                args.source_projects, args.chapter_project
            )
            _write(verification.to_dict(), args.output)
            return 0 if verification.valid else 2
        packet = _query(args)
        _write(packet, args.output)
        return 0 if packet["decision"] == "answered" else 2
    except (OSError, UnicodeError, TypeError, ValueError, ChapterProjectError) as exc:
        raise SystemExit(f"chapter structure engine failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
