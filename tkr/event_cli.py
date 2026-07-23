"""Command line interface and evidence-linked queries for Event Projects."""
from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import sqlite3
from typing import Mapping, Sequence

from .event_project import (
    EventProjectError,
    build_event_project,
    verify_event_project,
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
        prog="tkr-event",
        description=(
            "Build, verify, and query a focused evidence-bound Event Causality project. "
            "Unsupported causal paths refuse instead of being inferred."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build an Event Project")
    build.add_argument("chapter_project", type=Path)
    build.add_argument("annotations", type=Path)
    build.add_argument("--source-project", action="append", dest="source_projects", type=Path, required=True)
    build.add_argument("--literary-project", action="append", dest="literary_projects", type=Path, required=True)
    build.add_argument("--outdir", type=Path, required=True)
    build.add_argument("--force", action="store_true")

    verify = commands.add_parser("verify", help="verify an Event Project")
    verify.add_argument("event_project", type=Path)
    verify.add_argument("chapter_project", type=Path)
    verify.add_argument("annotations", type=Path)
    verify.add_argument("--source-project", action="append", dest="source_projects", type=Path, required=True)
    verify.add_argument("--literary-project", action="append", dest="literary_projects", type=Path, required=True)
    verify.add_argument("--output", type=Path)

    query = commands.add_parser("query", help="query a verified active event graph")
    query.add_argument("event_project", type=Path)
    query.add_argument("chapter_project", type=Path)
    query.add_argument("annotations", type=Path)
    query.add_argument("--source-project", action="append", dest="source_projects", type=Path, required=True)
    query.add_argument("--literary-project", action="append", dest="literary_projects", type=Path, required=True)
    selector = query.add_mutually_exclusive_group(required=True)
    selector.add_argument("--event-id")
    selector.add_argument("--name")
    selector.add_argument("--upstream")
    selector.add_argument("--downstream")
    selector.add_argument("--path", nargs=2, metavar=("FROM_EVENT", "TO_EVENT"))
    selector.add_argument("--foreshadowing", action="store_true")
    query.add_argument("--component", choices=("cause", "process", "outcome", "consequence", "foreshadowing", "recovery"))
    query.add_argument("--max-depth", type=int, default=4)
    query.add_argument("--output", type=Path)
    return parser


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, object]]:
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _row(cursor: sqlite3.Cursor) -> dict[str, object] | None:
    names = [item[0] for item in cursor.description]
    value = cursor.fetchone()
    return dict(zip(names, value)) if value is not None else None


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


def _event(connection: sqlite3.Connection, event_id: str) -> dict[str, object] | None:
    cursor = connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,))
    item = _row(cursor)
    if item is None:
        return None
    item["participant_entity_ids"] = _ids(
        connection, "event_participants", "event_id", event_id, "entity_id"
    )
    item["place_entity_ids"] = _ids(
        connection, "event_places", "event_id", event_id, "entity_id"
    )
    item["evidence_anchor_ids"] = _ids(
        connection, "event_evidence", "event_id", event_id, "anchor_id"
    )
    item["limitations"] = json.loads(str(item.pop("limitations_json")))
    return item


def _components(
    connection: sqlite3.Connection,
    event_id: str,
    component_type: str | None,
    assertions: Mapping[str, object],
    evidence: Mapping[str, object],
) -> list[dict[str, object]]:
    if component_type:
        cursor = connection.execute(
            "SELECT * FROM components WHERE event_id=? AND component_type=? "
            "ORDER BY CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,component_id",
            (event_id, component_type),
        )
    else:
        cursor = connection.execute(
            "SELECT * FROM components WHERE event_id=? "
            "ORDER BY component_type,CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,component_id",
            (event_id,),
        )
    rows = _rows(cursor)
    for item in rows:
        component_id = str(item["component_id"])
        assertion_ids = _ids(
            connection, "component_assertions", "component_id", component_id, "assertion_id"
        )
        evidence_ids = _ids(
            connection, "component_evidence", "component_id", component_id, "anchor_id"
        )
        item["supporting_component_ids"] = _ids(
            connection,
            "component_supports",
            "component_id",
            component_id,
            "supporting_component_id",
        )
        item["support"] = _expand_support(
            assertion_ids, evidence_ids, assertions, evidence
        )
        item["limitations"] = json.loads(str(item.pop("limitations_json")))
    return rows


def _edge(
    connection: sqlite3.Connection,
    edge_id: str,
    assertions: Mapping[str, object],
    evidence: Mapping[str, object],
) -> dict[str, object]:
    cursor = connection.execute("SELECT * FROM edges WHERE edge_id=?", (edge_id,))
    item = _row(cursor)
    assert item is not None
    assertion_ids = _ids(connection, "edge_assertions", "edge_id", edge_id, "assertion_id")
    evidence_ids = _ids(connection, "edge_evidence", "edge_id", edge_id, "anchor_id")
    item["supporting_component_ids"] = _ids(
        connection, "edge_supports", "edge_id", edge_id, "component_id"
    )
    item["support"] = _expand_support(assertion_ids, evidence_ids, assertions, evidence)
    item["limitations"] = json.loads(str(item.pop("limitations_json")))
    return item


def _active_edges(connection: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    return [
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in connection.execute(
            "SELECT edge_id,source_event_id,relation_type,target_event_id FROM edges "
            "WHERE status IN ('active','contested') ORDER BY source_position,target_position,edge_id"
        )
    ]


def _resolve_event(connection: sqlite3.Connection, value: str) -> tuple[str | None, list[str]]:
    found = connection.execute("SELECT event_id FROM events WHERE event_id=?", (value,)).fetchone()
    if found:
        return str(found[0]), []
    rows = [
        str(row[0])
        for row in connection.execute(
            "SELECT event_id FROM events WHERE canonical_name=? ORDER BY event_id", (value,)
        )
    ]
    if len(rows) == 1:
        return rows[0], []
    if not rows:
        return None, ["EVENT_NOT_FOUND"]
    return None, ["EVENT_NAME_AMBIGUOUS"]


def _traverse(
    connection: sqlite3.Connection,
    start: str,
    direction: str,
    max_depth: int,
    assertions: Mapping[str, object],
    evidence: Mapping[str, object],
) -> list[dict[str, object]]:
    edges = _active_edges(connection)
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge_id, source, relation, target in edges:
        if relation == "recovers":
            continue
        key, next_event = (source, target) if direction == "downstream" else (target, source)
        adjacency.setdefault(key, []).append((edge_id, next_event))
    queue = deque([(start, 0)])
    visited = {start}
    result: list[dict[str, object]] = []
    while queue:
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge_id, next_event in adjacency.get(node, []):
            result.append({
                "depth": depth + 1,
                "edge": _edge(connection, edge_id, assertions, evidence),
                "event": _event(connection, next_event),
            })
            if next_event not in visited:
                visited.add(next_event)
                queue.append((next_event, depth + 1))
    return result


def _path(
    connection: sqlite3.Connection,
    start: str,
    target: str,
    max_depth: int,
    assertions: Mapping[str, object],
    evidence: Mapping[str, object],
) -> list[dict[str, object]] | None:
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge_id, source, relation, next_event in _active_edges(connection):
        if relation == "recovers":
            continue
        adjacency.setdefault(source, []).append((edge_id, next_event))
    queue = deque([(start, [])])
    visited = {start}
    while queue:
        node, path = queue.popleft()
        if len(path) >= max_depth:
            continue
        for edge_id, next_event in adjacency.get(node, []):
            next_path = [*path, edge_id]
            if next_event == target:
                return [_edge(connection, value, assertions, evidence) for value in next_path]
            if next_event not in visited:
                visited.add(next_event)
                queue.append((next_event, next_path))
    return None


def _query(args: argparse.Namespace) -> dict[str, object]:
    verification = verify_event_project(
        args.chapter_project,
        args.source_projects,
        args.literary_projects,
        args.annotations,
        args.event_project,
    )
    base = {
        "schema_version": "tkr-event-query-v1",
        "event_project_logical_sha256": verification.logical_sha256,
        "may_present": True,
        "may_accept_project": False,
        "may_release": False,
        "may_freeze": False,
    }
    if not verification.valid:
        return {
            **base,
            "decision": "refused",
            "reason_codes": list(verification.reason_codes),
        }
    if not verification.graph_valid:
        return {
            **base,
            "decision": "refused",
            "reason_codes": ["EVENT_GRAPH_REVIEW_REQUIRED"],
        }
    if args.max_depth < 1 or args.max_depth > 12:
        return {
            **base,
            "decision": "refused",
            "reason_codes": ["EVENT_QUERY_DEPTH_INVALID"],
        }
    assertions, evidence = _support_context(args.literary_projects)
    connection = sqlite3.connect(f"file:{args.event_project / 'event.sqlite'}?mode=ro", uri=True)
    try:
        if args.foreshadowing:
            cursor = connection.execute(
                "SELECT edge_id FROM edges WHERE relation_type IN ('foreshadows','recovers') "
                "AND status IN ('active','contested') ORDER BY source_position,target_position,edge_id"
            )
            rows = [
                _edge(connection, str(row[0]), assertions, evidence)
                for row in cursor.fetchall()
            ]
            return {
                **base,
                "decision": "answered" if rows else "refused",
                "query_type": "foreshadowing",
                "edges": rows,
                "reason_codes": [] if rows else ["EVENT_FORESHADOWING_NOT_FOUND"],
            }
        if args.path:
            source_id, source_reasons = _resolve_event(connection, args.path[0])
            target_id, target_reasons = _resolve_event(connection, args.path[1])
            if source_id is None or target_id is None:
                return {
                    **base,
                    "decision": "refused",
                    "reason_codes": list(dict.fromkeys([*source_reasons, *target_reasons])),
                }
            path = _path(
                connection, source_id, target_id, args.max_depth, assertions, evidence
            )
            return {
                **base,
                "decision": "answered" if path else "refused",
                "query_type": "causal_path",
                "source_event": _event(connection, source_id),
                "target_event": _event(connection, target_id),
                "path": path or [],
                "reason_codes": [] if path else ["SUPPORTED_CAUSAL_PATH_NOT_FOUND"],
            }
        raw_value = args.event_id or args.name or args.upstream or args.downstream
        assert isinstance(raw_value, str)
        event_id, reasons = _resolve_event(connection, raw_value)
        if event_id is None:
            return {**base, "decision": "refused", "reason_codes": reasons}
        if args.upstream or args.downstream:
            direction = "upstream" if args.upstream else "downstream"
            paths = _traverse(
                connection, event_id, direction, args.max_depth, assertions, evidence
            )
            return {
                **base,
                "decision": "answered" if paths else "refused",
                "query_type": direction,
                "event": _event(connection, event_id),
                "connections": paths,
                "reason_codes": [] if paths else [f"EVENT_{direction.upper()}_NOT_FOUND"],
            }
        event = _event(connection, event_id)
        assert event is not None
        incoming_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT edge_id FROM edges WHERE target_event_id=? ORDER BY source_position,edge_id",
                (event_id,),
            )
        ]
        outgoing_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT edge_id FROM edges WHERE source_event_id=? ORDER BY target_position,edge_id",
                (event_id,),
            )
        ]
        return {
            **base,
            "decision": "answered",
            "query_type": "event_profile",
            "event": event,
            "components": _components(
                connection, event_id, args.component, assertions, evidence
            ),
            "incoming_edges": [
                _edge(connection, value, assertions, evidence) for value in incoming_ids
            ],
            "outgoing_edges": [
                _edge(connection, value, assertions, evidence) for value in outgoing_ids
            ],
            "reason_codes": [],
        }
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            report = build_event_project(
                args.chapter_project,
                args.source_projects,
                args.literary_projects,
                args.annotations,
                args.outdir,
                replace_existing=args.force,
            )
            _write(report)
            return 0
        if args.command == "verify":
            verification = verify_event_project(
                args.chapter_project,
                args.source_projects,
                args.literary_projects,
                args.annotations,
                args.event_project,
            )
            _write(verification.to_dict(), args.output)
            return 0 if verification.valid else 2
        packet = _query(args)
        _write(packet, args.output)
        return 0 if packet["decision"] == "answered" else 2
    except (OSError, UnicodeError, TypeError, ValueError, EventProjectError) as exc:
        raise SystemExit(f"event causality engine failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
