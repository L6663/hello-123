"""Focused, evidence-bound Event Causality Engine for Stage 3.

The engine models only events with material narrative impact.  It separates
internal event components from event-to-event causal edges and preserves A/B/C
epistemic levels throughout validation and graph queries.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Final, Iterable, Mapping, Sequence

EVENT_ENGINE_VERSION: Final = "tkr-event-engine-v1"
EVENT_RECORD_SCHEMA_VERSION: Final = "tkr-causal-event-v1"
EVENT_COMPONENT_SCHEMA_VERSION: Final = "tkr-event-component-v1"
EVENT_CAUSAL_EDGE_SCHEMA_VERSION: Final = "tkr-event-causal-edge-v1"
EVENT_FINDING_SCHEMA_VERSION: Final = "tkr-event-finding-v1"
EVENT_GRAPH_REPORT_SCHEMA_VERSION: Final = "tkr-event-graph-report-v1"

_COMPONENT_TYPES: Final = frozenset(
    {"cause", "process", "outcome", "consequence", "foreshadowing", "recovery"}
)
_EDGE_TYPES: Final = frozenset(
    {
        "triggers",
        "enables",
        "escalates",
        "prevents",
        "reveals",
        "undermines",
        "resolves",
        "foreshadows",
        "recovers",
    }
)
_FORWARD_RELATIONS: Final = _EDGE_TYPES - {"recovers"}
_ACTIVE_STATUSES: Final = frozenset({"active", "contested"})


class EventEngineError(ValueError):
    """Raised when an event graph violates evidence or temporal contracts."""


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\0".join(
        json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if isinstance(part, (dict, list, tuple))
        else str(part)
        for part in parts
    )
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:32]


def _text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise EventEngineError(f"{name} must be a string")
    if not allow_empty and not value:
        raise EventEngineError(f"{name} must be non-empty")
    return value


def _position(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EventEngineError(f"{name} must be a non-negative integer")
    return value


def _confidence(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EventEngineError(f"{name} must be numeric")
    cooked = float(value)
    if not 0.0 <= cooked <= 1.0:
        raise EventEngineError(f"{name} must be between zero and one")
    return cooked


def _unique(values: Sequence[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise EventEngineError(f"{name} must contain unique identifiers")
    for value in values:
        _text(value, name)


@dataclass(frozen=True, slots=True)
class CausalEvent:
    schema_version: str
    event_id: str
    canonical_name: str
    event_type: str
    significance: str
    start_chapter_id: str
    end_chapter_id: str
    start_position: int
    end_position: int
    participant_entity_ids: tuple[str, ...]
    place_entity_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    review_status: str

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_RECORD_SCHEMA_VERSION:
            raise EventEngineError("event schema version mismatch")
        for name in (
            "event_id",
            "canonical_name",
            "event_type",
            "start_chapter_id",
            "end_chapter_id",
            "review_status",
        ):
            _text(getattr(self, name), name)
        if self.significance not in {"core", "major", "review_candidate"}:
            raise EventEngineError("unsupported event significance")
        start = _position(self.start_position, "start_position")
        end = _position(self.end_position, "end_position")
        if end < start:
            raise EventEngineError("event end precedes start")
        for name in (
            "participant_entity_ids",
            "place_entity_ids",
            "evidence_anchor_ids",
            "limitations",
        ):
            _unique(getattr(self, name), name)
        if self.review_status not in {"active", "contested", "review_only", "superseded"}:
            raise EventEngineError("unsupported event review status")
        if self.review_status in _ACTIVE_STATUSES:
            if self.significance not in {"core", "major"}:
                raise EventEngineError("active events must have core or major significance")
            if not self.evidence_anchor_ids:
                raise EventEngineError("active events require exact evidence")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in (
            "participant_entity_ids",
            "place_entity_ids",
            "evidence_anchor_ids",
            "limitations",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class EventComponent:
    schema_version: str
    component_id: str
    event_id: str
    component_type: str
    tier: str
    statement: str
    assertion_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    supporting_component_ids: tuple[str, ...]
    confidence: float
    limitations: tuple[str, ...]
    attribution: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_COMPONENT_SCHEMA_VERSION:
            raise EventEngineError("event component schema version mismatch")
        for name in ("component_id", "event_id", "statement", "attribution", "status"):
            _text(getattr(self, name), name)
        if self.component_type not in _COMPONENT_TYPES:
            raise EventEngineError("unsupported event component type")
        if self.tier not in {"A", "B", "C"}:
            raise EventEngineError("event component tier must be A, B, or C")
        for name in (
            "assertion_ids",
            "evidence_anchor_ids",
            "supporting_component_ids",
            "limitations",
        ):
            _unique(getattr(self, name), name)
        _confidence(self.confidence, "confidence")
        if self.status not in {"active", "contested", "superseded", "review_only"}:
            raise EventEngineError("unsupported event component status")
        if self.tier == "A":
            if not self.evidence_anchor_ids or not self.assertion_ids:
                raise EventEngineError("tier A event components require assertions and evidence")
            if self.attribution not in {
                "source_explicit",
                "source_direct_event",
                "source_direct_dialogue",
            }:
                raise EventEngineError("tier A event component attribution is invalid")
        elif self.tier == "B":
            if len(self.assertion_ids) < 2 and len(self.supporting_component_ids) < 2:
                raise EventEngineError("tier B event components require multiple independent supports")
            if self.attribution != "cross_evidence_synthesis":
                raise EventEngineError("tier B event component must be synthesis")
        else:
            if not (self.assertion_ids or self.supporting_component_ids):
                raise EventEngineError("tier C event components require supporting material")
            if not self.limitations:
                raise EventEngineError("tier C event components require limitations")
            if self.attribution != "model_interpretation":
                raise EventEngineError("tier C event component must be model interpretation")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in (
            "assertion_ids",
            "evidence_anchor_ids",
            "supporting_component_ids",
            "limitations",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class EventCausalEdge:
    schema_version: str
    edge_id: str
    source_event_id: str
    relation_type: str
    target_event_id: str
    tier: str
    assertion_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    supporting_component_ids: tuple[str, ...]
    source_position: int
    target_position: int
    temporal_direction: str
    confidence: float
    limitations: tuple[str, ...]
    attribution: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_CAUSAL_EDGE_SCHEMA_VERSION:
            raise EventEngineError("causal edge schema version mismatch")
        for name in (
            "edge_id",
            "source_event_id",
            "target_event_id",
            "temporal_direction",
            "attribution",
            "status",
        ):
            _text(getattr(self, name), name)
        if self.source_event_id == self.target_event_id:
            raise EventEngineError("causal edge cannot connect an event to itself")
        if self.relation_type not in _EDGE_TYPES:
            raise EventEngineError("unsupported event causal relation")
        if self.tier not in {"A", "B", "C"}:
            raise EventEngineError("causal edge tier must be A, B, or C")
        for name in (
            "assertion_ids",
            "evidence_anchor_ids",
            "supporting_component_ids",
            "limitations",
        ):
            _unique(getattr(self, name), name)
        source = _position(self.source_position, "source_position")
        target = _position(self.target_position, "target_position")
        _confidence(self.confidence, "confidence")
        expected_direction = "backward_reference" if self.relation_type == "recovers" else "forward"
        if self.temporal_direction != expected_direction:
            raise EventEngineError("causal edge temporal direction differs from relation semantics")
        if self.relation_type in _FORWARD_RELATIONS and target < source:
            raise EventEngineError("forward causal edge points backward in time")
        if self.relation_type == "recovers" and target > source:
            raise EventEngineError("recovery edge must reference an earlier event")
        if self.status not in {"active", "contested", "review_only", "superseded"}:
            raise EventEngineError("unsupported causal edge status")
        if self.status in _ACTIVE_STATUSES and not (
            self.assertion_ids or self.evidence_anchor_ids or self.supporting_component_ids
        ):
            raise EventEngineError("active causal edge requires supporting material")
        if self.tier == "A":
            if not self.assertion_ids or not self.evidence_anchor_ids:
                raise EventEngineError("tier A causal edges require assertions and exact evidence")
            if self.attribution not in {
                "source_explicit",
                "source_direct_event",
                "source_direct_dialogue",
            }:
                raise EventEngineError("tier A causal edge attribution is invalid")
        elif self.tier == "B":
            if len(self.assertion_ids) < 2 and len(self.supporting_component_ids) < 2:
                raise EventEngineError("tier B causal edges require multiple independent supports")
            if self.attribution != "cross_evidence_synthesis":
                raise EventEngineError("tier B causal edge must be synthesis")
        else:
            if not self.limitations:
                raise EventEngineError("tier C causal edges require limitations")
            if self.attribution != "model_interpretation":
                raise EventEngineError("tier C causal edge must be model interpretation")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in (
            "assertion_ids",
            "evidence_anchor_ids",
            "supporting_component_ids",
            "limitations",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class EventFinding:
    schema_version: str
    finding_id: str
    rule_id: str
    severity: str
    event_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    signals: tuple[str, ...]
    recommended_action: str

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_FINDING_SCHEMA_VERSION:
            raise EventEngineError("event finding schema version mismatch")
        for name in ("finding_id", "rule_id", "severity", "recommended_action"):
            _text(getattr(self, name), name)
        if self.severity not in {"low", "medium", "high"}:
            raise EventEngineError("unsupported event finding severity")
        for name in ("event_ids", "edge_ids", "signals"):
            _unique(getattr(self, name), name)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["event_ids"] = list(self.event_ids)
        payload["edge_ids"] = list(self.edge_ids)
        payload["signals"] = list(self.signals)
        return payload


@dataclass(frozen=True, slots=True)
class EventGraphReport:
    schema_version: str
    event_engine_version: str
    event_count: int
    component_count: int
    edge_count: int
    active_event_count: int
    active_edge_count: int
    tier_a_component_count: int
    tier_b_component_count: int
    tier_c_component_count: int
    finding_count: int
    cycle_count: int
    unsupported_reference_count: int
    temporal_violation_count: int
    graph_valid: bool
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_GRAPH_REPORT_SCHEMA_VERSION:
            raise EventEngineError("event graph report schema version mismatch")
        if self.event_engine_version != EVENT_ENGINE_VERSION:
            raise EventEngineError("event graph engine version mismatch")
        for name in (
            "event_count",
            "component_count",
            "edge_count",
            "active_event_count",
            "active_edge_count",
            "tier_a_component_count",
            "tier_b_component_count",
            "tier_c_component_count",
            "finding_count",
            "cycle_count",
            "unsupported_reference_count",
            "temporal_violation_count",
        ):
            _position(getattr(self, name), name)
        if any((
            self.project_acceptance_performed,
            self.may_accept_project,
            self.may_release,
            self.may_freeze,
        )):
            raise EventEngineError("event graph report cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EventGraph:
    events: tuple[CausalEvent, ...]
    components: tuple[EventComponent, ...]
    edges: tuple[EventCausalEdge, ...]
    findings: tuple[EventFinding, ...]
    report: EventGraphReport


def event_id(canonical_name: str, start_chapter_id: str, end_chapter_id: str) -> str:
    return _stable_id(
        "cev_", EVENT_RECORD_SCHEMA_VERSION, canonical_name, start_chapter_id, end_chapter_id
    )


def component_id(
    event_id_value: str,
    component_type: str,
    tier: str,
    statement: str,
    assertion_ids: Sequence[str],
    evidence_anchor_ids: Sequence[str],
) -> str:
    return _stable_id(
        "evc_",
        EVENT_COMPONENT_SCHEMA_VERSION,
        event_id_value,
        component_type,
        tier,
        statement,
        sorted(assertion_ids),
        sorted(evidence_anchor_ids),
    )


def causal_edge_id(
    source_event_id: str,
    relation_type: str,
    target_event_id: str,
    tier: str,
    assertion_ids: Sequence[str],
    evidence_anchor_ids: Sequence[str],
) -> str:
    return _stable_id(
        "ece_",
        EVENT_CAUSAL_EDGE_SCHEMA_VERSION,
        source_event_id,
        relation_type,
        target_event_id,
        tier,
        sorted(assertion_ids),
        sorted(evidence_anchor_ids),
    )


def _finding(
    rule_id: str,
    severity: str,
    event_ids: Iterable[str],
    edge_ids: Iterable[str],
    signals: Iterable[str],
    action: str,
) -> EventFinding:
    events = tuple(sorted(set(event_ids)))
    edges = tuple(sorted(set(edge_ids)))
    signal_tuple = tuple(signals)
    return EventFinding(
        EVENT_FINDING_SCHEMA_VERSION,
        _stable_id("evf_", EVENT_FINDING_SCHEMA_VERSION, rule_id, events, edges, signal_tuple),
        rule_id,
        severity,
        events,
        edges,
        signal_tuple,
        action,
    )


def _cycles(events: Mapping[str, CausalEvent], edges: Sequence[EventCausalEdge]) -> list[tuple[str, ...]]:
    adjacency: dict[str, list[str]] = {event_id_value: [] for event_id_value in events}
    for edge in edges:
        if edge.status not in _ACTIVE_STATUSES or edge.relation_type == "recovers":
            continue
        if edge.source_event_id in adjacency and edge.target_event_id in adjacency:
            adjacency[edge.source_event_id].append(edge.target_event_id)
    cycles: set[tuple[str, ...]] = set()
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> None:
        if node in visiting:
            index = stack.index(node)
            cycle = stack[index:] + [node]
            body = cycle[:-1]
            rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
            cycles.add(min(rotations))
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for target in sorted(adjacency[node]):
            visit(target)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(adjacency):
        visit(node)
    return sorted(cycles)


def build_event_graph(
    events: Sequence[CausalEvent],
    components: Sequence[EventComponent],
    edges: Sequence[EventCausalEdge],
    *,
    known_assertion_ids: Iterable[str],
    known_evidence_anchor_ids: Iterable[str],
) -> EventGraph:
    """Validate and assemble a deterministic focused event causality graph."""

    event_by_id = {item.event_id: item for item in events}
    component_by_id = {item.component_id: item for item in components}
    edge_by_id = {item.edge_id: item for item in edges}
    if len(event_by_id) != len(events):
        raise EventEngineError("duplicate event identifiers")
    if len(component_by_id) != len(components):
        raise EventEngineError("duplicate event component identifiers")
    if len(edge_by_id) != len(edges):
        raise EventEngineError("duplicate event causal edge identifiers")
    assertion_ids = set(known_assertion_ids)
    evidence_ids = set(known_evidence_anchor_ids)
    findings: list[EventFinding] = []
    unsupported_count = 0
    temporal_count = 0

    for event in events:
        unknown_evidence = sorted(set(event.evidence_anchor_ids) - evidence_ids)
        if unknown_evidence:
            unsupported_count += 1
            findings.append(_finding(
                "EVENT_UNKNOWN_EVIDENCE",
                "high",
                (event.event_id,),
                (),
                tuple(f"unknown_evidence={value}" for value in unknown_evidence),
                "reject_event_until_evidence_is_verified",
            ))
        if event.review_status in _ACTIVE_STATUSES and event.significance not in {"core", "major"}:
            findings.append(_finding(
                "LOW_IMPACT_ACTIVE_EVENT",
                "high",
                (event.event_id,),
                (),
                (f"significance={event.significance}",),
                "demote_to_review_only_or_demonstrate_material_impact",
            ))

    for component in components:
        if component.event_id not in event_by_id:
            unsupported_count += 1
            findings.append(_finding(
                "COMPONENT_UNKNOWN_EVENT",
                "high",
                (component.event_id,),
                (),
                (f"component_id={component.component_id}",),
                "reject_component_until_event_exists",
            ))
        unknown_assertions = sorted(set(component.assertion_ids) - assertion_ids)
        unknown_evidence = sorted(set(component.evidence_anchor_ids) - evidence_ids)
        unknown_components = sorted(
            set(component.supporting_component_ids) - set(component_by_id)
        )
        if unknown_assertions or unknown_evidence or unknown_components:
            unsupported_count += 1
            findings.append(_finding(
                "COMPONENT_UNKNOWN_SUPPORT",
                "high",
                (component.event_id,),
                (),
                (
                    *tuple(f"unknown_assertion={value}" for value in unknown_assertions),
                    *tuple(f"unknown_evidence={value}" for value in unknown_evidence),
                    *tuple(f"unknown_component={value}" for value in unknown_components),
                ),
                "reject_component_until_support_is_verified",
            ))
        if component.tier == "B":
            support_tiers = {
                component_by_id[value].tier
                for value in component.supporting_component_ids
                if value in component_by_id
            }
            if support_tiers and support_tiers != {"A"}:
                findings.append(_finding(
                    "B_COMPONENT_SUPPORT_TIER_INVALID",
                    "high",
                    (component.event_id,),
                    (),
                    tuple(f"support_tier={value}" for value in sorted(support_tiers)),
                    "bind_B_component_to_independent_A_supports",
                ))
        if component.tier == "C":
            support_tiers = {
                component_by_id[value].tier
                for value in component.supporting_component_ids
                if value in component_by_id
            }
            if "C" in support_tiers:
                findings.append(_finding(
                    "C_COMPONENT_SELF_REINFORCING_INTERPRETATION",
                    "high",
                    (component.event_id,),
                    (),
                    (f"component_id={component.component_id}",),
                    "bind_interpretation_to_A_or_B_support",
                ))

    for edge in edges:
        source = event_by_id.get(edge.source_event_id)
        target = event_by_id.get(edge.target_event_id)
        if source is None or target is None:
            unsupported_count += 1
            findings.append(_finding(
                "EDGE_UNKNOWN_EVENT",
                "high",
                (edge.source_event_id, edge.target_event_id),
                (edge.edge_id,),
                (),
                "reject_edge_until_both_events_exist",
            ))
            continue
        if source.start_position != edge.source_position or target.start_position != edge.target_position:
            temporal_count += 1
            findings.append(_finding(
                "EDGE_POSITION_BINDING_MISMATCH",
                "high",
                (source.event_id, target.event_id),
                (edge.edge_id,),
                (
                    f"stored_source={edge.source_position}",
                    f"actual_source={source.start_position}",
                    f"stored_target={edge.target_position}",
                    f"actual_target={target.start_position}",
                ),
                "rebind_edge_to_verified_event_positions",
            ))
        unknown_assertions = sorted(set(edge.assertion_ids) - assertion_ids)
        unknown_evidence = sorted(set(edge.evidence_anchor_ids) - evidence_ids)
        unknown_components = sorted(set(edge.supporting_component_ids) - set(component_by_id))
        if unknown_assertions or unknown_evidence or unknown_components:
            unsupported_count += 1
            findings.append(_finding(
                "EDGE_UNKNOWN_SUPPORT",
                "high",
                (source.event_id, target.event_id),
                (edge.edge_id,),
                (
                    *tuple(f"unknown_assertion={value}" for value in unknown_assertions),
                    *tuple(f"unknown_evidence={value}" for value in unknown_evidence),
                    *tuple(f"unknown_component={value}" for value in unknown_components),
                ),
                "reject_edge_until_support_is_verified",
            ))
        if edge.tier == "B":
            tiers = {
                component_by_id[value].tier
                for value in edge.supporting_component_ids
                if value in component_by_id
            }
            if tiers and tiers != {"A"}:
                findings.append(_finding(
                    "B_EDGE_SUPPORT_TIER_INVALID",
                    "high",
                    (source.event_id, target.event_id),
                    (edge.edge_id,),
                    tuple(f"support_tier={value}" for value in sorted(tiers)),
                    "bind_B_edge_to_independent_A_components",
                ))
        if edge.tier == "C" and any(
            component_by_id[value].tier == "C"
            for value in edge.supporting_component_ids
            if value in component_by_id
        ):
            findings.append(_finding(
                "C_EDGE_SELF_REINFORCING_INTERPRETATION",
                "high",
                (source.event_id, target.event_id),
                (edge.edge_id,),
                (),
                "bind_interpretation_to_A_or_B_support",
            ))

    cycles = _cycles(event_by_id, edges)
    for cycle in cycles:
        cycle_edges = [
            edge.edge_id
            for edge in edges
            if edge.source_event_id in cycle and edge.target_event_id in cycle
            and edge.status in _ACTIVE_STATUSES and edge.relation_type != "recovers"
        ]
        findings.append(_finding(
            "ACTIVE_CAUSAL_CYCLE",
            "high",
            cycle,
            cycle_edges,
            ("cycle=" + "->".join(cycle),),
            "review_direction_or_model_feedback_as_contested",
        ))

    findings = sorted(
        {item.finding_id: item for item in findings}.values(),
        key=lambda item: (item.rule_id, item.finding_id),
    )
    high_findings = [item for item in findings if item.severity == "high"]
    report = EventGraphReport(
        EVENT_GRAPH_REPORT_SCHEMA_VERSION,
        EVENT_ENGINE_VERSION,
        len(events),
        len(components),
        len(edges),
        sum(item.review_status in _ACTIVE_STATUSES for item in events),
        sum(item.status in _ACTIVE_STATUSES for item in edges),
        sum(item.tier == "A" for item in components),
        sum(item.tier == "B" for item in components),
        sum(item.tier == "C" for item in components),
        len(findings),
        len(cycles),
        unsupported_count,
        temporal_count,
        not high_findings,
    )
    return EventGraph(
        tuple(sorted(events, key=lambda item: (item.start_position, item.event_id))),
        tuple(sorted(components, key=lambda item: (item.event_id, item.component_type, item.component_id))),
        tuple(sorted(edges, key=lambda item: (item.source_position, item.target_position, item.edge_id))),
        tuple(findings),
        report,
    )


def event_from_dict(payload: Mapping[str, object]) -> CausalEvent:
    data = dict(payload)
    for key in (
        "participant_entity_ids",
        "place_entity_ids",
        "evidence_anchor_ids",
        "limitations",
    ):
        value = data.get(key, [])
        if not isinstance(value, list):
            raise EventEngineError(f"event.{key} must be a JSON array")
        data[key] = tuple(value)
    try:
        return CausalEvent(**data)
    except TypeError as exc:
        raise EventEngineError(f"invalid event record: {exc}") from exc


def component_from_dict(payload: Mapping[str, object]) -> EventComponent:
    data = dict(payload)
    for key in (
        "assertion_ids",
        "evidence_anchor_ids",
        "supporting_component_ids",
        "limitations",
    ):
        value = data.get(key, [])
        if not isinstance(value, list):
            raise EventEngineError(f"event component.{key} must be a JSON array")
        data[key] = tuple(value)
    try:
        return EventComponent(**data)
    except TypeError as exc:
        raise EventEngineError(f"invalid event component: {exc}") from exc


def edge_from_dict(payload: Mapping[str, object]) -> EventCausalEdge:
    data = dict(payload)
    for key in (
        "assertion_ids",
        "evidence_anchor_ids",
        "supporting_component_ids",
        "limitations",
    ):
        value = data.get(key, [])
        if not isinstance(value, list):
            raise EventEngineError(f"event edge.{key} must be a JSON array")
        data[key] = tuple(value)
    try:
        return EventCausalEdge(**data)
    except TypeError as exc:
        raise EventEngineError(f"invalid event causal edge: {exc}") from exc


__all__ = [
    "EVENT_CAUSAL_EDGE_SCHEMA_VERSION",
    "EVENT_COMPONENT_SCHEMA_VERSION",
    "EVENT_ENGINE_VERSION",
    "EVENT_FINDING_SCHEMA_VERSION",
    "EVENT_GRAPH_REPORT_SCHEMA_VERSION",
    "EVENT_RECORD_SCHEMA_VERSION",
    "CausalEvent",
    "EventCausalEdge",
    "EventComponent",
    "EventEngineError",
    "EventFinding",
    "EventGraph",
    "EventGraphReport",
    "build_event_graph",
    "causal_edge_id",
    "component_from_dict",
    "component_id",
    "edge_from_dict",
    "event_from_dict",
    "event_id",
]
