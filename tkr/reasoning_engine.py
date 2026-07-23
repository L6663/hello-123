"""Deterministic epistemic-layer reasoning contracts for Stage 5.

The engine validates reviewed reasoning records and builds section-separated answer
packets.  It does not generate new source facts, literary interpretations, or
counterfactual outcomes on its own.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Final, Iterable, Mapping, Sequence

REASONING_ENGINE_VERSION: Final = "6.0.0-stage5-alpha1"
REASONING_NODE_SCHEMA_VERSION: Final = "tkr-reasoning-node-v1"
REASONING_EDGE_SCHEMA_VERSION: Final = "tkr-reasoning-edge-v1"
REASONING_FINDING_SCHEMA_VERSION: Final = "tkr-reasoning-finding-v1"
REASONING_REPORT_SCHEMA_VERSION: Final = "tkr-reasoning-graph-report-v1"
ANSWER_PACKET_SCHEMA_VERSION: Final = "tkr-layered-answer-packet-v1"

LAYERS: Final = frozenset({"A", "B", "C", "H"})
NODE_STATUSES: Final = frozenset({"active", "contested", "superseded", "review"})
EDGE_RELATIONS: Final = frozenset({
    "direct_support",
    "independent_support",
    "derived_from",
    "contradicts",
    "context",
    "alternative_reading",
    "counterfactual_premise",
    "counterfactual_inference",
})
QUERY_MODES: Final = frozenset({
    "fact_only",
    "fact_and_synthesis",
    "analysis",
    "counterfactual",
    "provenance",
})
BLOCKING_SEVERITIES: Final = frozenset({"high", "critical"})


class ReasoningEngineError(ValueError):
    """Raised when a reasoning record violates the epistemic contract."""


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReasoningEngineError(f"{name} must be non-empty text")
    return value


def _require_tuple_text(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(not isinstance(item, str) or not item for item in values):
        raise ReasoningEngineError(f"{name} must be a tuple of non-empty strings")
    if len(values) != len(set(values)):
        raise ReasoningEngineError(f"{name} must not contain duplicates")
    return values


def _require_confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReasoningEngineError("confidence must be numeric")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ReasoningEngineError("confidence must be between 0 and 1")
    return number


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\0".join(_canonical_json(part) for part in parts)
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class ReasoningNode:
    schema_version: str
    node_id: str
    layer: str
    statement: str
    intent_tags: tuple[str, ...]
    chapter_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    upstream_record_ids: tuple[str, ...]
    support_node_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    independence_groups: tuple[str, ...]
    confidence: float
    attribution: str
    limitations: tuple[str, ...]
    alternatives: tuple[str, ...]
    counterfactual_premise: str
    inference_rule: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != REASONING_NODE_SCHEMA_VERSION:
            raise ReasoningEngineError("reasoning node schema mismatch")
        _require_text(self.node_id, "node_id")
        if self.layer not in LAYERS:
            raise ReasoningEngineError(f"unsupported reasoning layer: {self.layer}")
        _require_text(self.statement, "statement")
        for name in (
            "intent_tags",
            "chapter_ids",
            "entity_ids",
            "event_ids",
            "upstream_record_ids",
            "support_node_ids",
            "evidence_anchor_ids",
            "independence_groups",
            "limitations",
            "alternatives",
        ):
            _require_tuple_text(getattr(self, name), name)
        _require_confidence(self.confidence)
        _require_text(self.attribution, "attribution")
        if self.status not in NODE_STATUSES:
            raise ReasoningEngineError(f"unsupported reasoning node status: {self.status}")

        if self.layer == "A":
            if not self.upstream_record_ids or not self.evidence_anchor_ids:
                raise ReasoningEngineError("layer A requires upstream records and exact evidence")
            if not self.chapter_ids:
                raise ReasoningEngineError("layer A requires at least one chapter location")
            if len(self.independence_groups) != 1:
                raise ReasoningEngineError("layer A requires exactly one evidence-independence group")
            if self.support_node_ids:
                raise ReasoningEngineError("layer A cannot be derived from reasoning nodes")
            if self.attribution != "source_fact":
                raise ReasoningEngineError("layer A attribution must be source_fact")
            if self.counterfactual_premise or self.inference_rule:
                raise ReasoningEngineError("layer A cannot contain counterfactual fields")

        elif self.layer == "B":
            if len(self.support_node_ids) < 2:
                raise ReasoningEngineError("layer B requires at least two support nodes")
            if len(self.independence_groups) < 2:
                raise ReasoningEngineError("layer B requires two independent support groups")
            if self.attribution != "cross_evidence_synthesis":
                raise ReasoningEngineError("layer B attribution must be cross_evidence_synthesis")
            if not self.limitations:
                raise ReasoningEngineError("layer B requires explicit limitations")
            if self.counterfactual_premise or self.inference_rule:
                raise ReasoningEngineError("layer B cannot contain counterfactual fields")

        elif self.layer == "C":
            if not self.support_node_ids:
                raise ReasoningEngineError("layer C requires A/B support nodes")
            if self.attribution != "model_interpretation":
                raise ReasoningEngineError("layer C attribution must be model_interpretation")
            if not self.limitations or not self.alternatives:
                raise ReasoningEngineError(
                    "layer C requires limitations and at least one alternative reading"
                )
            if self.counterfactual_premise or self.inference_rule:
                raise ReasoningEngineError("layer C cannot contain counterfactual fields")

        else:  # H
            if not self.support_node_ids:
                raise ReasoningEngineError("layer H requires verified premise support")
            if self.attribution != "counterfactual_inference":
                raise ReasoningEngineError("layer H attribution must be counterfactual_inference")
            _require_text(self.counterfactual_premise, "counterfactual_premise")
            _require_text(self.inference_rule, "inference_rule")
            if not self.limitations or not self.alternatives:
                raise ReasoningEngineError(
                    "layer H requires uncertainty limitations and alternative outcomes"
                )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for name in (
            "intent_tags",
            "chapter_ids",
            "entity_ids",
            "event_ids",
            "upstream_record_ids",
            "support_node_ids",
            "evidence_anchor_ids",
            "independence_groups",
            "limitations",
            "alternatives",
        ):
            payload[name] = list(payload[name])
        return payload


@dataclass(frozen=True, slots=True)
class ReasoningEdge:
    schema_version: str
    edge_id: str
    source_node_id: str
    relation: str
    target_node_id: str
    confidence: float
    limitations: tuple[str, ...]
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != REASONING_EDGE_SCHEMA_VERSION:
            raise ReasoningEngineError("reasoning edge schema mismatch")
        for name in ("edge_id", "source_node_id", "target_node_id"):
            _require_text(getattr(self, name), name)
        if self.source_node_id == self.target_node_id:
            raise ReasoningEngineError("reasoning edge endpoints must differ")
        if self.relation not in EDGE_RELATIONS:
            raise ReasoningEngineError(f"unsupported reasoning relation: {self.relation}")
        _require_confidence(self.confidence)
        _require_tuple_text(self.limitations, "limitations")
        if self.status not in NODE_STATUSES:
            raise ReasoningEngineError(f"unsupported reasoning edge status: {self.status}")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["limitations"] = list(self.limitations)
        return payload


@dataclass(frozen=True, slots=True)
class ReasoningFinding:
    schema_version: str
    finding_id: str
    rule_id: str
    severity: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    signals: tuple[str, ...]
    recommended_action: str

    def __post_init__(self) -> None:
        if self.schema_version != REASONING_FINDING_SCHEMA_VERSION:
            raise ReasoningEngineError("reasoning finding schema mismatch")
        for name in ("finding_id", "rule_id", "severity", "recommended_action"):
            _require_text(getattr(self, name), name)
        for name in ("node_ids", "edge_ids", "signals"):
            _require_tuple_text(getattr(self, name), name)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for name in ("node_ids", "edge_ids", "signals"):
            payload[name] = list(payload[name])
        return payload


@dataclass(frozen=True, slots=True)
class ReasoningGraphReport:
    schema_version: str
    status: str
    graph_valid: bool
    node_count: int
    edge_count: int
    layer_counts: dict[str, int]
    finding_count: int
    blocking_finding_count: int
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != REASONING_REPORT_SCHEMA_VERSION:
            raise ReasoningEngineError("reasoning graph report schema mismatch")
        if self.status not in {"completed", "review_required"}:
            raise ReasoningEngineError("reasoning graph status must be completed or review_required")
        if self.graph_valid != (self.status == "completed"):
            raise ReasoningEngineError("reasoning graph status and validity disagree")
        for name in ("node_count", "edge_count", "finding_count", "blocking_finding_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ReasoningEngineError(f"{name} must be a non-negative integer")
        if any((
            self.project_acceptance_performed,
            self.may_accept_project,
            self.may_release,
            self.may_freeze,
        )):
            raise ReasoningEngineError("Stage 5 graph cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReasoningGraph:
    nodes: tuple[ReasoningNode, ...]
    edges: tuple[ReasoningEdge, ...]
    findings: tuple[ReasoningFinding, ...]
    report: ReasoningGraphReport


def reasoning_node_id(layer: str, statement: str, support_ids: Sequence[str]) -> str:
    return stable_id("rrn_", REASONING_NODE_SCHEMA_VERSION, layer, statement, sorted(support_ids))


def reasoning_edge_id(source: str, relation: str, target: str) -> str:
    return stable_id("rre_", REASONING_EDGE_SCHEMA_VERSION, source, relation, target)


def _finding(
    rule_id: str,
    severity: str,
    *,
    node_ids: Iterable[str] = (),
    edge_ids: Iterable[str] = (),
    signals: Iterable[str] = (),
    action: str,
) -> ReasoningFinding:
    node_tuple = tuple(sorted(set(node_ids)))
    edge_tuple = tuple(sorted(set(edge_ids)))
    signal_tuple = tuple(sorted(set(signals)))
    return ReasoningFinding(
        REASONING_FINDING_SCHEMA_VERSION,
        stable_id(
            "rrf_",
            REASONING_FINDING_SCHEMA_VERSION,
            rule_id,
            node_tuple,
            edge_tuple,
            signal_tuple,
        ),
        rule_id,
        severity,
        node_tuple,
        edge_tuple,
        signal_tuple,
        action,
    )


def _derived_cycle(nodes: Mapping[str, ReasoningNode], edges: Sequence[ReasoningEdge]) -> tuple[str, ...]:
    adjacency: dict[str, list[str]] = {key: [] for key in nodes}
    for edge in edges:
        if edge.status != "active" or edge.relation not in {
            "direct_support",
            "independent_support",
            "derived_from",
            "counterfactual_premise",
            "counterfactual_inference",
        }:
            continue
        adjacency[edge.source_node_id].append(edge.target_node_id)
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def walk(node_id: str) -> tuple[str, ...]:
        if node_id in visiting:
            start = path.index(node_id)
            return tuple(path[start:] + [node_id])
        if node_id in visited:
            return ()
        visiting.add(node_id)
        path.append(node_id)
        for target in adjacency.get(node_id, []):
            cycle = walk(target)
            if cycle:
                return cycle
        path.pop()
        visiting.remove(node_id)
        visited.add(node_id)
        return ()

    for node_id in sorted(nodes):
        cycle = walk(node_id)
        if cycle:
            return cycle
    return ()


def build_reasoning_graph(
    nodes: Sequence[ReasoningNode],
    edges: Sequence[ReasoningEdge],
    *,
    known_upstream_record_ids: Iterable[str],
    known_evidence_anchor_ids: Iterable[str],
) -> ReasoningGraph:
    """Validate reviewed reasoning records and return a deterministic graph."""
    sorted_nodes = tuple(sorted(nodes, key=lambda item: (item.layer, item.node_id)))
    sorted_edges = tuple(sorted(edges, key=lambda item: (item.source_node_id, item.relation, item.target_node_id, item.edge_id)))
    node_by_id: dict[str, ReasoningNode] = {}
    findings: list[ReasoningFinding] = []

    for node in sorted_nodes:
        if node.node_id in node_by_id:
            findings.append(_finding(
                "DUPLICATE_REASONING_NODE_ID",
                "critical",
                node_ids=(node.node_id,),
                action="deduplicate_reviewed_reasoning_nodes",
            ))
        else:
            node_by_id[node.node_id] = node

    upstream = set(known_upstream_record_ids)
    evidence = set(known_evidence_anchor_ids)
    for node in sorted_nodes:
        missing_upstream = sorted(set(node.upstream_record_ids) - upstream)
        missing_evidence = sorted(set(node.evidence_anchor_ids) - evidence)
        if missing_upstream or missing_evidence:
            findings.append(_finding(
                "REASONING_NODE_UNKNOWN_UPSTREAM_SUPPORT",
                "critical",
                node_ids=(node.node_id,),
                signals=(
                    *(f"missing_upstream={value}" for value in missing_upstream),
                    *(f"missing_evidence={value}" for value in missing_evidence),
                ),
                action="bind_only_verified_upstream_records_and_evidence",
            ))
        missing_nodes = sorted(set(node.support_node_ids) - set(node_by_id))
        if missing_nodes:
            findings.append(_finding(
                "REASONING_NODE_UNKNOWN_REASONING_SUPPORT",
                "critical",
                node_ids=(node.node_id,),
                signals=(f"missing_support={value}" for value in missing_nodes),
                action="resolve_reasoning_support_references",
            ))
            continue
        if node.layer == "B":
            supports = [node_by_id[value] for value in node.support_node_ids]
            if any(item.layer != "A" for item in supports):
                findings.append(_finding(
                    "B_SUPPORT_NOT_DIRECT_A",
                    "high",
                    node_ids=(node.node_id, *(item.node_id for item in supports)),
                    action="support_B_with_independent_A_nodes",
                ))
            support_groups = {group for item in supports for group in item.independence_groups}
            if len(support_groups) < 2:
                findings.append(_finding(
                    "B_SUPPORT_NOT_INDEPENDENT",
                    "high",
                    node_ids=(node.node_id, *(item.node_id for item in supports)),
                    signals=(f"independent_group_count={len(support_groups)}",),
                    action="add_independent_A_support_or_downgrade_to_review",
                ))
        elif node.layer == "C":
            supports = [node_by_id[value] for value in node.support_node_ids]
            if any(item.layer not in {"A", "B"} for item in supports):
                findings.append(_finding(
                    "C_SUPPORT_USES_INTERPRETATION_OR_HYPOTHETICAL",
                    "high",
                    node_ids=(node.node_id, *(item.node_id for item in supports)),
                    action="support_C_only_with_A_or_B_nodes",
                ))
        elif node.layer == "H":
            supports = [node_by_id[value] for value in node.support_node_ids]
            if any(item.layer not in {"A", "B"} for item in supports):
                findings.append(_finding(
                    "H_PREMISE_USES_C_OR_H_SUPPORT",
                    "high",
                    node_ids=(node.node_id, *(item.node_id for item in supports)),
                    action="ground_counterfactual_premises_in_A_or_B_nodes",
                ))

    edge_ids: set[str] = set()
    for edge in sorted_edges:
        if edge.edge_id in edge_ids:
            findings.append(_finding(
                "DUPLICATE_REASONING_EDGE_ID",
                "critical",
                edge_ids=(edge.edge_id,),
                action="deduplicate_reasoning_edges",
            ))
        edge_ids.add(edge.edge_id)
        missing = [value for value in (edge.source_node_id, edge.target_node_id) if value not in node_by_id]
        if missing:
            findings.append(_finding(
                "REASONING_EDGE_UNKNOWN_ENDPOINT",
                "critical",
                edge_ids=(edge.edge_id,),
                signals=(f"missing_node={value}" for value in missing),
                action="resolve_reasoning_edge_endpoints",
            ))

    if not any(item.rule_id == "REASONING_EDGE_UNKNOWN_ENDPOINT" for item in findings):
        cycle = _derived_cycle(node_by_id, sorted_edges)
        if cycle:
            findings.append(_finding(
                "REASONING_DERIVATION_CYCLE",
                "critical",
                node_ids=cycle,
                action="break_or_review_circular_reasoning",
            ))

    findings.sort(key=lambda item: (item.severity, item.rule_id, item.finding_id))
    blocking = sum(item.severity in BLOCKING_SEVERITIES for item in findings)
    layer_counts = {layer: sum(item.layer == layer for item in sorted_nodes) for layer in sorted(LAYERS)}
    graph_valid = blocking == 0
    report = ReasoningGraphReport(
        REASONING_REPORT_SCHEMA_VERSION,
        "completed" if graph_valid else "review_required",
        graph_valid,
        len(sorted_nodes),
        len(sorted_edges),
        layer_counts,
        len(findings),
        blocking,
    )
    return ReasoningGraph(sorted_nodes, sorted_edges, tuple(findings), report)


def _allowed_layers(mode: str) -> frozenset[str]:
    if mode == "fact_only":
        return frozenset({"A"})
    if mode == "fact_and_synthesis":
        return frozenset({"A", "B"})
    if mode == "analysis":
        return frozenset({"A", "B", "C"})
    if mode == "counterfactual":
        return frozenset({"A", "B", "H"})
    if mode == "provenance":
        return frozenset(LAYERS)
    raise ReasoningEngineError(f"unsupported query mode: {mode}")


def build_answer_packet(
    graph: ReasoningGraph,
    selected_node_ids: Sequence[str],
    *,
    mode: str,
) -> dict[str, object]:
    """Build a deterministic, section-separated answer packet.

    The function never promotes a forbidden layer.  It may return a partial answer
    when some selected nodes are valid and others are missing or mode-forbidden.
    """
    if mode not in QUERY_MODES:
        raise ReasoningEngineError(f"unsupported query mode: {mode}")
    base: dict[str, object] = {
        "schema_version": ANSWER_PACKET_SCHEMA_VERSION,
        "mode": mode,
        "graph_status": graph.report.status,
        "may_accept_project": False,
        "may_release": False,
        "may_freeze": False,
    }
    if not graph.report.graph_valid and mode != "provenance":
        return {
            **base,
            "decision": "refused",
            "reason_codes": ["REASONING_GRAPH_REVIEW_REQUIRED"],
            "facts": [],
            "synthesis": [],
            "interpretation": [],
            "counterfactual": [],
            "conflicts": [item.to_dict() for item in graph.findings],
            "provenance": [],
        }

    node_by_id = {item.node_id: item for item in graph.nodes}
    allowed = _allowed_layers(mode)
    selected: list[ReasoningNode] = []
    reasons: list[str] = []
    for node_id in selected_node_ids:
        node = node_by_id.get(node_id)
        if node is None:
            reasons.append(f"REASONING_NODE_NOT_FOUND:{node_id}")
            continue
        if node.status not in {"active", "contested"}:
            reasons.append(f"REASONING_NODE_NOT_PRESENTABLE:{node_id}")
            continue
        if node.layer not in allowed:
            reasons.append(f"REASONING_LAYER_FORBIDDEN_BY_MODE:{node.layer}:{node_id}")
            continue
        selected.append(node)

    selected.sort(key=lambda item: (item.layer, item.node_id))
    sections = {
        "facts": [item.to_dict() for item in selected if item.layer == "A"],
        "synthesis": [item.to_dict() for item in selected if item.layer == "B"],
        "interpretation": [item.to_dict() for item in selected if item.layer == "C"],
        "counterfactual": [item.to_dict() for item in selected if item.layer == "H"],
    }
    provenance = [
        {
            "node_id": item.node_id,
            "layer": item.layer,
            "upstream_record_ids": list(item.upstream_record_ids),
            "support_node_ids": list(item.support_node_ids),
            "evidence_anchor_ids": list(item.evidence_anchor_ids),
            "independence_groups": list(item.independence_groups),
        }
        for item in selected
    ]
    if selected and reasons:
        decision = "partial"
    elif selected:
        decision = "answered"
    else:
        decision = "refused"
        if not reasons:
            reasons.append("NO_SUPPORTED_REASONING_NODE_SELECTED")
    return {
        **base,
        "decision": decision,
        "reason_codes": reasons,
        **sections,
        "conflicts": [
            item.to_dict()
            for item in graph.findings
            if item.rule_id.endswith("CONTRADICTION") or "CONFLICT" in item.rule_id
        ],
        "limitations": sorted({value for item in selected for value in item.limitations}),
        "alternatives": sorted({value for item in selected for value in item.alternatives}),
        "provenance": provenance,
    }


__all__ = [
    "ANSWER_PACKET_SCHEMA_VERSION",
    "EDGE_RELATIONS",
    "LAYERS",
    "QUERY_MODES",
    "REASONING_EDGE_SCHEMA_VERSION",
    "REASONING_ENGINE_VERSION",
    "REASONING_FINDING_SCHEMA_VERSION",
    "REASONING_NODE_SCHEMA_VERSION",
    "REASONING_REPORT_SCHEMA_VERSION",
    "ReasoningEdge",
    "ReasoningEngineError",
    "ReasoningFinding",
    "ReasoningGraph",
    "ReasoningGraphReport",
    "ReasoningNode",
    "build_answer_packet",
    "build_reasoning_graph",
    "reasoning_edge_id",
    "reasoning_node_id",
    "stable_id",
]
