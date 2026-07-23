"""CLI for immutable Stage 5 Reasoning Projects and separated answer packets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence

from .reasoning_engine import (
    REASONING_EDGE_SCHEMA_VERSION,
    REASONING_FINDING_SCHEMA_VERSION,
    REASONING_NODE_SCHEMA_VERSION,
    REASONING_REPORT_SCHEMA_VERSION,
    ReasoningEdge,
    ReasoningFinding,
    ReasoningGraph,
    ReasoningGraphReport,
    ReasoningNode,
    build_answer_packet,
)
from .reasoning_project import (
    ReasoningProjectError,
    _upstream_context,
    build_reasoning_project,
    verify_reasoning_project,
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


def _add_upstream_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("chapter_project", type=Path)
    parser.add_argument("event_project", type=Path)
    parser.add_argument("event_annotations", type=Path)
    parser.add_argument("character_project", type=Path)
    parser.add_argument("character_annotations", type=Path)
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
        help="repeat one verified source/literary/Evidence triple",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-reason",
        description=(
            "Build, verify, and query an A/B/C/H-separated Reasoning Project. "
            "Query mode is a ceiling and never authorizes unsupported inference."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a Reasoning Project")
    _add_upstream_inputs(build)
    build.add_argument("--outdir", type=Path, required=True)
    build.add_argument("--force", action="store_true")

    verify = commands.add_parser("verify", help="verify a Reasoning Project")
    verify.add_argument("reasoning_project", type=Path)
    _add_upstream_inputs(verify)
    verify.add_argument("--output", type=Path)

    query = commands.add_parser("query", help="build a separated answer packet")
    query.add_argument("reasoning_project", type=Path)
    _add_upstream_inputs(query)
    query.add_argument(
        "--mode",
        choices=("fact_only", "fact_and_synthesis", "analysis", "counterfactual", "provenance"),
        required=True,
    )
    selector = query.add_mutually_exclusive_group(required=True)
    selector.add_argument("--node-id", action="append", dest="node_ids")
    selector.add_argument("--intent-tag")
    selector.add_argument("--all", action="store_true")
    query.add_argument("--output", type=Path)
    return parser


def _bindings(values: Sequence[Sequence[str]]) -> tuple[tuple[Path, Path, Path], ...]:
    return tuple((Path(first), Path(second), Path(third)) for first, second, third in values)


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ReasoningProjectError(f"non-object JSONL record in {path.name}")
            rows.append(value)
    return rows


def _tuple_values(row: dict[str, object], names: Sequence[str]) -> dict[str, object]:
    result = dict(row)
    for name in names:
        value = result.get(name, [])
        if not isinstance(value, list):
            raise ReasoningProjectError(f"{name} must be a JSON array")
        result[name] = tuple(value)
    return result


def _load_graph(root: Path) -> ReasoningGraph:
    nodes = tuple(
        ReasoningNode(**_tuple_values(row, (
            "intent_tags", "chapter_ids", "entity_ids", "event_ids",
            "upstream_record_ids", "support_node_ids", "evidence_anchor_ids",
            "independence_groups", "limitations", "alternatives",
        )))
        for row in _load_jsonl(root / "reasoning-nodes.jsonl")
    )
    edges = tuple(
        ReasoningEdge(**_tuple_values(row, ("limitations",)))
        for row in _load_jsonl(root / "reasoning-edges.jsonl")
    )
    findings = tuple(
        ReasoningFinding(**_tuple_values(row, ("node_ids", "edge_ids", "signals")))
        for row in _load_jsonl(root / "reasoning-findings.jsonl")
    )
    report_row = json.loads((root / "reasoning-project-report.json").read_text(encoding="utf-8"))
    report = ReasoningGraphReport(
        REASONING_REPORT_SCHEMA_VERSION,
        str(report_row["status"]),
        bool(report_row["graph_valid"]),
        int(report_row["node_count"]),
        int(report_row["edge_count"]),
        {str(key): int(value) for key, value in dict(report_row["layer_counts"]).items()},
        int(report_row["finding_count"]),
        int(report_row["blocking_finding_count"]),
    )
    if any(node.schema_version != REASONING_NODE_SCHEMA_VERSION for node in nodes):
        raise ReasoningProjectError("reasoning node schema mismatch")
    if any(edge.schema_version != REASONING_EDGE_SCHEMA_VERSION for edge in edges):
        raise ReasoningProjectError("reasoning edge schema mismatch")
    if any(item.schema_version != REASONING_FINDING_SCHEMA_VERSION for item in findings):
        raise ReasoningProjectError("reasoning finding schema mismatch")
    return ReasoningGraph(nodes, edges, findings, report)


def _selected_ids(graph: ReasoningGraph, args: argparse.Namespace) -> list[str]:
    if args.node_ids:
        return list(dict.fromkeys(args.node_ids))
    if args.intent_tag:
        return [
            item.node_id
            for item in graph.nodes
            if args.intent_tag in item.intent_tags
        ]
    if args.all:
        return [item.node_id for item in graph.nodes]
    return []


def _expanded_provenance(
    packet: Mapping[str, object],
    upstream_rows: Mapping[str, Mapping[str, object]],
    evidence_rows: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    raw = packet.get("provenance", [])
    if not isinstance(raw, list):
        return []
    expanded: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        upstream_ids = item.get("upstream_record_ids", [])
        evidence_ids = item.get("evidence_anchor_ids", [])
        expanded.append({
            **item,
            "upstream_records": [
                upstream_rows[value]
                for value in upstream_ids
                if isinstance(value, str) and value in upstream_rows
            ] if isinstance(upstream_ids, list) else [],
            "evidence_anchors": [
                evidence_rows[value]
                for value in evidence_ids
                if isinstance(value, str) and value in evidence_rows
            ] if isinstance(evidence_ids, list) else [],
        })
    return expanded


def _verify(args: argparse.Namespace):
    return verify_reasoning_project(
        args.chapter_project,
        args.source_projects,
        args.literary_projects,
        _bindings(args.evidence_binding),
        args.event_project,
        args.event_annotations,
        args.character_project,
        args.character_annotations,
        args.reasoning_annotations,
        args.reasoning_project,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_reasoning_project(
                args.chapter_project,
                args.source_projects,
                args.literary_projects,
                _bindings(args.evidence_binding),
                args.event_project,
                args.event_annotations,
                args.character_project,
                args.character_annotations,
                args.reasoning_annotations,
                args.outdir,
                replace_existing=args.force,
            )
            _write(result.to_dict(), None)
            return 0
        if args.command == "verify":
            result = _verify(args)
            _write(result.to_dict(), args.output)
            return 0 if result.valid else 2

        verification = _verify(args)
        base = {
            "schema_version": "tkr-reasoning-query-response-v1",
            "reasoning_project_logical_sha256": verification.logical_sha256,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        if not verification.valid:
            _write({
                **base,
                "decision": "refused",
                "reason_codes": list(verification.reason_codes),
            }, args.output)
            return 2
        graph = _load_graph(args.reasoning_project)
        selected = _selected_ids(graph, args)
        packet = build_answer_packet(graph, selected, mode=args.mode)
        context = _upstream_context(
            args.chapter_project,
            tuple(args.source_projects),
            tuple(args.literary_projects),
            _bindings(args.evidence_binding),
            args.event_project,
            args.event_annotations,
            args.character_project,
            args.character_annotations,
        )
        response = {
            **base,
            **packet,
            "resolved_provenance": _expanded_provenance(
                packet, context.upstream_rows, context.evidence_rows
            ),
        }
        _write(response, args.output)
        return 0 if response.get("decision") in {"answered", "partial"} else 2
    except (OSError, UnicodeError, json.JSONDecodeError, ReasoningProjectError, ValueError) as exc:
        raise SystemExit(f"reasoning command failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
