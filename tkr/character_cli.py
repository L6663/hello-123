"""Command line interface and evidence-linked queries for Character Projects."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from typing import Mapping, Sequence

from .character_project import (
    CharacterProjectError,
    build_character_project,
    verify_character_project,
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


def _add_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("chapter_project", type=Path)
    parser.add_argument("event_project", type=Path)
    parser.add_argument("event_annotations", type=Path)
    parser.add_argument("character_annotations", type=Path)
    parser.add_argument("--source-project", action="append", dest="source_projects", type=Path, required=True)
    parser.add_argument("--literary-project", action="append", dest="literary_projects", type=Path, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-character",
        description=(
            "Build, verify, and query a focused evidence-bound Character Project. "
            "Placeholder and mention-only characters cannot receive invented depth."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a Character Project")
    _add_inputs(build)
    build.add_argument("--outdir", type=Path, required=True)
    build.add_argument("--force", action="store_true")

    verify = commands.add_parser("verify", help="verify a Character Project")
    verify.add_argument("character_project", type=Path)
    _add_inputs(verify)
    verify.add_argument("--output", type=Path)

    query = commands.add_parser("query", help="query a verified active Character Project")
    query.add_argument("character_project", type=Path)
    _add_inputs(query)
    selector = query.add_mutually_exclusive_group(required=True)
    selector.add_argument("--character-id")
    selector.add_argument("--name")
    selector.add_argument("--state-at", nargs=2, metavar=("CHARACTER", "POSITION"))
    selector.add_argument("--relationship-at", nargs=3, metavar=("CHARACTER_A", "CHARACTER_B", "POSITION"))
    selector.add_argument("--events")
    selector.add_argument("--arc")
    selector.add_argument("--why-selected")
    query.add_argument("--output", type=Path)
    return parser


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _support_context(literary_projects: Sequence[Path]) -> tuple[dict[str, object], dict[str, object]]:
    assertions: dict[str, object] = {}
    evidence: dict[str, object] = {}
    for project in literary_projects:
        for row in _load_jsonl(project / "assertions.jsonl"):
            identifier = row.get("assertion_id")
            if isinstance(identifier, str):
                assertions[identifier] = row
        for row in _load_jsonl(project / "evidence-anchors.jsonl"):
            identifier = row.get("anchor_id")
            if isinstance(identifier, str):
                evidence[identifier] = row
    return assertions, evidence


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, object]]:
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _row(cursor: sqlite3.Cursor) -> dict[str, object] | None:
    names = [item[0] for item in cursor.description]
    value = cursor.fetchone()
    return dict(zip(names, value)) if value is not None else None


def _ids(connection: sqlite3.Connection, table: str, key: str, value: str, column: str) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            f"SELECT {column} FROM {table} WHERE {key}=? ORDER BY {column}", (value,)
        )
    ]


def _expand_support(
    assertion_ids: Sequence[str],
    evidence_ids: Sequence[str],
    assertions: Mapping[str, object],
    evidence: Mapping[str, object],
) -> dict[str, object]:
    return {
        "assertion_ids": list(assertion_ids),
        "assertions": [assertions[value] for value in assertion_ids if value in assertions],
        "evidence_anchor_ids": list(evidence_ids),
        "evidence": [evidence[value] for value in evidence_ids if value in evidence],
    }


def _character(connection: sqlite3.Connection, character_id: str) -> dict[str, object] | None:
    cursor = connection.execute("SELECT * FROM characters WHERE character_id=?", (character_id,))
    item = _row(cursor)
    if item is None:
        return None
    item["aliases"] = _ids(connection, "aliases", "character_id", character_id, "alias")
    item["evidence_anchor_ids"] = _ids(
        connection, "character_evidence", "character_id", character_id, "anchor_id"
    )
    item["selection_reasons"] = json.loads(str(item.pop("selection_reasons_json")))
    item["limitations"] = json.loads(str(item.pop("limitations_json")))
    return item


def _resolve_character(connection: sqlite3.Connection, value: str) -> tuple[str | None, list[str]]:
    found = connection.execute(
        "SELECT character_id FROM characters WHERE character_id=?", (value,)
    ).fetchone()
    if found:
        return str(found[0]), []
    rows = [
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT character_id FROM aliases WHERE alias=? ORDER BY character_id",
            (value,),
        )
    ]
    if len(rows) == 1:
        return rows[0], []
    if not rows:
        return None, ["CHARACTER_NOT_MODELED"]
    return None, ["CHARACTER_ALIAS_AMBIGUOUS"]


def _attribute_rows(
    connection: sqlite3.Connection,
    character_id: str,
    assertions: Mapping[str, object],
    evidence: Mapping[str, object],
    *,
    attribute_type: str | None = None,
) -> list[dict[str, object]]:
    if attribute_type:
        cursor = connection.execute(
            "SELECT * FROM attributes WHERE character_id=? AND attribute_type=? "
            "ORDER BY start_position,CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,attribute_id",
            (character_id, attribute_type),
        )
    else:
        cursor = connection.execute(
            "SELECT * FROM attributes WHERE character_id=? "
            "ORDER BY attribute_type,start_position,CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,attribute_id",
            (character_id,),
        )
    rows = _rows(cursor)
    for item in rows:
        identifier = str(item["attribute_id"])
        assertion_ids = _ids(
            connection, "attribute_assertions", "attribute_id", identifier, "assertion_id"
        )
        evidence_ids = _ids(
            connection, "attribute_evidence", "attribute_id", identifier, "anchor_id"
        )
        item["supporting_attribute_ids"] = _ids(
            connection, "attribute_supports", "attribute_id", identifier, "supporting_attribute_id"
        )
        item["support"] = _expand_support(
            assertion_ids, evidence_ids, assertions, evidence
        )
        item["limitations"] = json.loads(str(item.pop("limitations_json")))
    return rows


def _state_rows(
    connection: sqlite3.Connection,
    character_id: str,
    position: int,
    assertions: Mapping[str, object],
    evidence: Mapping[str, object],
) -> list[dict[str, object]]:
    cursor = connection.execute(
        "SELECT * FROM states WHERE character_id=? AND start_position<=? AND end_position>=? "
        "AND status IN ('active','contested') ORDER BY state_type,CASE tier WHEN 'A' THEN 0 ELSE 1 END,state_id",
        (character_id, position, position),
    )
    rows = _rows(cursor)
    for item in rows:
        identifier = str(item["state_id"])
        assertion_ids = _ids(connection, "state_assertions", "state_id", identifier, "assertion_id")
        evidence_ids = _ids(connection, "state_evidence", "state_id", identifier, "anchor_id")
        item["support"] = _expand_support(
            assertion_ids, evidence_ids, assertions, evidence
        )
        item["limitations"] = json.loads(str(item.pop("limitations_json")))
    return rows


def _relationship_rows(
    connection: sqlite3.Connection,
    first: str,
    second: str,
    position: int,
    assertions: Mapping[str, object],
    evidence: Mapping[str, object],
) -> list[dict[str, object]]:
    cursor = connection.execute(
        "SELECT * FROM relationships WHERE "
        "((subject_character_id=? AND object_character_id=?) OR "
        "(subject_character_id=? AND object_character_id=?)) "
        "AND start_position<=? AND end_position>=? AND status IN ('active','contested') "
        "ORDER BY CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,relationship_id",
        (first, second, second, first, position, position),
    )
    rows = _rows(cursor)
    for item in rows:
        identifier = str(item["relationship_id"])
        assertion_ids = _ids(
            connection, "relationship_assertions", "relationship_id", identifier, "assertion_id"
        )
        evidence_ids = _ids(
            connection, "relationship_evidence", "relationship_id", identifier, "anchor_id"
        )
        item["change_event_ids"] = _ids(
            connection, "relationship_events", "relationship_id", identifier, "event_id"
        )
        item["supporting_relationship_ids"] = _ids(
            connection,
            "relationship_supports",
            "relationship_id",
            identifier,
            "supporting_relationship_id",
        )
        item["support"] = _expand_support(
            assertion_ids, evidence_ids, assertions, evidence
        )
        item["limitations"] = json.loads(str(item.pop("limitations_json")))
    return rows


def _event_links(
    connection: sqlite3.Connection,
    event_connection: sqlite3.Connection,
    character_id: str,
    assertions: Mapping[str, object],
    evidence: Mapping[str, object],
) -> list[dict[str, object]]:
    cursor = connection.execute(
        "SELECT * FROM event_links WHERE character_id=? ORDER BY event_id,role,link_id",
        (character_id,),
    )
    rows = _rows(cursor)
    for item in rows:
        identifier = str(item["link_id"])
        assertion_ids = _ids(
            connection, "event_link_assertions", "link_id", identifier, "assertion_id"
        )
        evidence_ids = _ids(
            connection, "event_link_evidence", "link_id", identifier, "anchor_id"
        )
        event_cursor = event_connection.execute(
            "SELECT event_id,canonical_name,event_type,significance,start_chapter_id,end_chapter_id,"
            "start_position,end_position,review_status FROM events WHERE event_id=?",
            (item["event_id"],),
        )
        item["event"] = _row(event_cursor)
        item["support"] = _expand_support(
            assertion_ids, evidence_ids, assertions, evidence
        )
        item["limitations"] = json.loads(str(item.pop("limitations_json")))
    return rows


def _query(args: argparse.Namespace) -> dict[str, object]:
    verification = verify_character_project(
        args.chapter_project,
        args.source_projects,
        args.literary_projects,
        args.event_project,
        args.event_annotations,
        args.character_annotations,
        args.character_project,
    )
    base = {
        "schema_version": "tkr-character-query-v1",
        "character_project_logical_sha256": verification.logical_sha256,
        "may_present": True,
        "may_accept_project": False,
        "may_release": False,
        "may_freeze": False,
    }
    if not verification.valid:
        return {**base, "decision": "refused", "reason_codes": list(verification.reason_codes)}
    if not verification.graph_valid:
        return {**base, "decision": "refused", "reason_codes": ["CHARACTER_GRAPH_REVIEW_REQUIRED"]}
    assertions, evidence = _support_context(args.literary_projects)
    connection = sqlite3.connect(f"file:{args.character_project / 'character.sqlite'}?mode=ro", uri=True)
    event_connection = sqlite3.connect(f"file:{args.event_project / 'event.sqlite'}?mode=ro", uri=True)
    try:
        if args.state_at:
            raw, raw_position = args.state_at
            try:
                position = int(raw_position)
            except ValueError:
                return {**base, "decision": "refused", "reason_codes": ["CHARACTER_POSITION_INVALID"]}
            character_id, reasons = _resolve_character(connection, raw)
            if character_id is None:
                return {**base, "decision": "refused", "reason_codes": reasons}
            rows = _state_rows(connection, character_id, position, assertions, evidence)
            return {
                **base,
                "decision": "answered" if rows else "refused",
                "query_type": "state_at",
                "character": _character(connection, character_id),
                "position": position,
                "states": rows,
                "reason_codes": [] if rows else ["CHARACTER_STATE_NOT_FOUND_AT_POSITION"],
            }
        if args.relationship_at:
            raw_first, raw_second, raw_position = args.relationship_at
            try:
                position = int(raw_position)
            except ValueError:
                return {**base, "decision": "refused", "reason_codes": ["CHARACTER_POSITION_INVALID"]}
            first, first_reasons = _resolve_character(connection, raw_first)
            second, second_reasons = _resolve_character(connection, raw_second)
            if first is None or second is None:
                return {
                    **base,
                    "decision": "refused",
                    "reason_codes": list(dict.fromkeys([*first_reasons, *second_reasons])),
                }
            first_character = _character(connection, first)
            second_character = _character(connection, second)
            assert first_character is not None and second_character is not None
            if "placeholder" in {first_character["scope"], second_character["scope"]}:
                return {
                    **base,
                    "decision": "refused",
                    "reason_codes": ["PLACEHOLDER_DEEP_RELATIONSHIP_NOT_MODELED"],
                }
            rows = _relationship_rows(
                connection, first, second, position, assertions, evidence
            )
            return {
                **base,
                "decision": "answered" if rows else "refused",
                "query_type": "relationship_at",
                "characters": [first_character, second_character],
                "position": position,
                "relationships": rows,
                "reason_codes": [] if rows else ["CHARACTER_RELATIONSHIP_NOT_FOUND_AT_POSITION"],
            }
        raw = args.character_id or args.name or args.events or args.arc or args.why_selected
        assert isinstance(raw, str)
        character_id, reasons = _resolve_character(connection, raw)
        if character_id is None:
            return {**base, "decision": "refused", "reason_codes": reasons}
        character = _character(connection, character_id)
        assert character is not None
        if args.why_selected:
            return {
                **base,
                "decision": "answered",
                "query_type": "selection_basis",
                "character": character,
                "selection_policy": (
                    "deep_model" if character["scope"] == "core"
                    else "moderate_model" if character["scope"] == "important"
                    else "minimal_placeholder"
                ),
                "reason_codes": [],
            }
        if args.events:
            if character["scope"] == "placeholder":
                links = _event_links(
                    connection, event_connection, character_id, assertions, evidence
                )
                links = [item for item in links if item["role"] == "participant"]
            else:
                links = _event_links(
                    connection, event_connection, character_id, assertions, evidence
                )
            return {
                **base,
                "decision": "answered" if links else "refused",
                "query_type": "major_events",
                "character": character,
                "event_links": links,
                "reason_codes": [] if links else ["CHARACTER_MAJOR_EVENT_NOT_FOUND"],
            }
        if args.arc:
            if character["scope"] != "core":
                return {
                    **base,
                    "decision": "refused",
                    "query_type": "character_arc",
                    "character": character,
                    "reason_codes": ["CHARACTER_ARC_RESERVED_FOR_CORE_SCOPE"],
                }
            arc = _attribute_rows(
                connection, character_id, assertions, evidence, attribute_type="arc"
            )
            choices = _attribute_rows(
                connection, character_id, assertions, evidence, attribute_type="choice"
            )
            events = _event_links(
                connection, event_connection, character_id, assertions, evidence
            )
            return {
                **base,
                "decision": "answered" if arc else "refused",
                "query_type": "character_arc",
                "character": character,
                "arc": arc,
                "key_choices": choices,
                "major_events": events,
                "reason_codes": [] if arc else ["SUPPORTED_CHARACTER_ARC_NOT_FOUND"],
            }
        attributes = _attribute_rows(connection, character_id, assertions, evidence)
        if character["scope"] == "placeholder":
            attributes = [
                item for item in attributes
                if item["attribute_type"] in {"identity", "role"} and item["tier"] == "A"
            ]
        return {
            **base,
            "decision": "answered",
            "query_type": "character_profile",
            "character": character,
            "attributes": attributes,
            "reason_codes": [],
        }
    finally:
        event_connection.close()
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            report = build_character_project(
                args.chapter_project,
                args.source_projects,
                args.literary_projects,
                args.event_project,
                args.event_annotations,
                args.character_annotations,
                args.outdir,
                replace_existing=args.force,
            )
            _write(report)
            return 0
        if args.command == "verify":
            verification = verify_character_project(
                args.chapter_project,
                args.source_projects,
                args.literary_projects,
                args.event_project,
                args.event_annotations,
                args.character_annotations,
                args.character_project,
            )
            _write(verification.to_dict(), args.output)
            return 0 if verification.valid else 2
        packet = _query(args)
        _write(packet, args.output)
        return 0 if packet["decision"] == "answered" else 2
    except (OSError, UnicodeError, TypeError, ValueError, CharacterProjectError) as exc:
        raise SystemExit(f"focused character engine failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
