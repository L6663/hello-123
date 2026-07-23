"""Deterministic Stage 7 literary regression benchmark.

The benchmark evaluates already-produced, section-separated answer packets. It
never asks a model to grade itself. Gold cases and observations are immutable
JSONL inputs; the report binds their byte and logical identities and can be
fully recomputed by an independent verifier.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping, Sequence

CASE_SCHEMA_VERSION = "tkr-literary-benchmark-case-v1"
OBSERVATION_SCHEMA_VERSION = "tkr-literary-benchmark-observation-v1"
REPORT_SCHEMA_VERSION = "tkr-literary-benchmark-report-v1"
VERIFICATION_SCHEMA_VERSION = "tkr-literary-benchmark-verification-v1"
EVALUATOR_VERSION = "6.0.0-stage7-alpha2"
ANSWER_PACKET_SCHEMA_VERSION = "tkr-layered-answer-packet-v1"

DOMAINS = (
    "chapter_traceability",
    "evidence_traceability",
    "entity_identity",
    "temporal_relationships",
    "event_causality",
    "cold_detail_recall",
    "dialogue_recall",
    "motive_reasoning",
    "foreshadowing_resolution",
    "theme_interpretation",
    "epistemic_separation",
    "refusal_safety",
)
MODES = frozenset({
    "fact_only", "fact_and_synthesis", "analysis", "counterfactual", "provenance"
})
DECISIONS = frozenset({"answered", "partial", "refused"})
LAYERS = frozenset({"A", "B", "C", "H"})
SECTION_LAYERS = MappingProxyType({
    "facts": "A",
    "synthesis": "B",
    "interpretation": "C",
    "counterfactual": "H",
})
APPROVED_REVIEW_STATUSES = frozenset({"approved", "adjudicated"})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CASE_FIELDS = frozenset({
    "schema_version", "case_id", "domain", "question", "mode",
    "expected_decision", "expected_layers", "expected_node_ids",
    "required_evidence_anchor_ids", "expected_evidence_by_node",
    "forbidden_node_ids", "expected_reason_codes", "source_sha256s", "tags",
    "allow_additional_nodes", "annotation_status", "annotator_id",
    "reviewer_ids", "rationale",
})
_OBSERVATION_FIELDS = frozenset({"schema_version", "case_id", "packet"})


class LiteraryBenchmarkError(ValueError):
    """Raised when a benchmark input or report is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class BenchmarkPolicy:
    profile: str
    policy_id: str
    min_cases: int
    min_cases_per_domain: int
    min_refusal_cases: int
    min_independent_reviewers: int
    min_domain_score: float
    min_correctness_score: float
    min_safety_score: float
    require_all_domains: bool
    require_approved_annotations: bool
    require_no_unexpected_nodes: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


POLICIES: Mapping[str, BenchmarkPolicy] = MappingProxyType({
    "smoke": BenchmarkPolicy(
        profile="smoke",
        policy_id="tkr-literary-benchmark-policy-smoke-v1",
        min_cases=12,
        min_cases_per_domain=1,
        min_refusal_cases=2,
        min_independent_reviewers=0,
        min_domain_score=9.0,
        min_correctness_score=9.0,
        min_safety_score=9.0,
        require_all_domains=True,
        require_approved_annotations=False,
        require_no_unexpected_nodes=True,
    ),
    "release": BenchmarkPolicy(
        profile="release",
        policy_id="tkr-literary-benchmark-policy-release-v1",
        min_cases=120,
        min_cases_per_domain=8,
        min_refusal_cases=24,
        min_independent_reviewers=2,
        min_domain_score=9.0,
        min_correctness_score=9.0,
        min_safety_score=9.0,
        require_all_domains=True,
        require_approved_annotations=True,
        require_no_unexpected_nodes=True,
    ),
})


@dataclass(frozen=True, slots=True)
class GoldCase:
    case_id: str
    domain: str
    question: str
    mode: str
    expected_decision: str
    expected_layers: tuple[str, ...]
    expected_node_ids: tuple[str, ...]
    required_evidence_anchor_ids: tuple[str, ...]
    expected_evidence_by_node: Mapping[str, tuple[str, ...]]
    forbidden_node_ids: tuple[str, ...]
    expected_reason_codes: tuple[str, ...]
    source_sha256s: tuple[str, ...]
    tags: tuple[str, ...]
    allow_additional_nodes: bool
    annotation_status: str
    annotator_id: str
    reviewer_ids: tuple[str, ...]
    rationale: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": CASE_SCHEMA_VERSION,
            "case_id": self.case_id,
            "domain": self.domain,
            "question": self.question,
            "mode": self.mode,
            "expected_decision": self.expected_decision,
            "expected_layers": list(self.expected_layers),
            "expected_node_ids": list(self.expected_node_ids),
            "required_evidence_anchor_ids": list(self.required_evidence_anchor_ids),
            "expected_evidence_by_node": {
                key: list(values)
                for key, values in sorted(self.expected_evidence_by_node.items())
            },
            "forbidden_node_ids": list(self.forbidden_node_ids),
            "expected_reason_codes": list(self.expected_reason_codes),
            "source_sha256s": list(self.source_sha256s),
            "tags": list(self.tags),
            "allow_additional_nodes": self.allow_additional_nodes,
            "annotation_status": self.annotation_status,
            "annotator_id": self.annotator_id,
            "reviewer_ids": list(self.reviewer_ids),
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class Observation:
    case_id: str
    packet: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "case_id": self.case_id,
            "packet": dict(self.packet),
        }


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    case_id: str
    domain: str
    expected_decision: str
    actual_decision: str
    decision_correct: bool
    mode_correct: bool
    expected_layers: tuple[str, ...]
    actual_layers: tuple[str, ...]
    missing_layers: tuple[str, ...]
    unexpected_layers: tuple[str, ...]
    expected_nodes: tuple[str, ...]
    actual_nodes: tuple[str, ...]
    missing_nodes: tuple[str, ...]
    unexpected_nodes: tuple[str, ...]
    forbidden_nodes_present: tuple[str, ...]
    missing_evidence_anchor_ids: tuple[str, ...]
    missing_evidence_bindings: tuple[str, ...]
    missing_reason_codes: tuple[str, ...]
    packet_integrity_errors: tuple[str, ...]
    layer_leakage_count: int
    overanswer: bool
    wrong_answer: bool
    citation_mismatch: bool
    measurable_hallucination: bool
    authority_escalation: bool
    exact_pass: bool
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field in (
            "expected_layers", "actual_layers", "missing_layers", "unexpected_layers",
            "expected_nodes", "actual_nodes", "missing_nodes", "unexpected_nodes",
            "forbidden_nodes_present", "missing_evidence_anchor_ids",
            "missing_evidence_bindings", "missing_reason_codes",
            "packet_integrity_errors", "reason_codes",
        ):
            payload[field] = list(payload[field])
        return payload


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    schema_version: str
    evaluator_version: str
    policy_profile: str
    policy: Mapping[str, object]
    cases_file_sha256: str
    cases_logical_sha256: str
    observations_file_sha256: str
    observations_logical_sha256: str
    case_count: int
    coverage: Mapping[str, object]
    metrics: Mapping[str, object]
    domain_results: Mapping[str, object]
    blockers: tuple[str, ...]
    cases: tuple[CaseEvaluation, ...]
    passed: bool
    project_acceptance_performed: bool
    may_accept_project: bool
    may_release: bool
    may_freeze: bool
    report_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "evaluator_version": self.evaluator_version,
            "policy_profile": self.policy_profile,
            "policy": dict(self.policy),
            "cases_file_sha256": self.cases_file_sha256,
            "cases_logical_sha256": self.cases_logical_sha256,
            "observations_file_sha256": self.observations_file_sha256,
            "observations_logical_sha256": self.observations_logical_sha256,
            "case_count": self.case_count,
            "coverage": dict(self.coverage),
            "metrics": dict(self.metrics),
            "domain_results": dict(self.domain_results),
            "blockers": list(self.blockers),
            "cases": [case.to_dict() for case in self.cases],
            "passed": self.passed,
            "project_acceptance_performed": self.project_acceptance_performed,
            "may_accept_project": self.may_accept_project,
            "may_release": self.may_release,
            "may_freeze": self.may_freeze,
            "report_id": self.report_id,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkVerification:
    schema_version: str
    status: str
    valid: bool
    reason_codes: tuple[str, ...]
    supplied_report_id: str
    expected_report_id: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True, slots=True)
class _PacketInspection:
    node_ids: tuple[str, ...]
    layers: tuple[str, ...]
    layer_leakage_count: int
    evidence_anchor_ids: tuple[str, ...]
    evidence_by_node: Mapping[str, tuple[str, ...]]
    packet_reason_codes: tuple[str, ...]
    integrity_errors: tuple[str, ...]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _logical_digest(rows: Sequence[Mapping[str, object]]) -> str:
    canonical = "\n".join(
        _canonical_json(row)
        for row in sorted(rows, key=lambda item: str(item.get("case_id", "")))
    )
    return _digest_bytes(canonical.encode("utf-8"))


def _safe_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise LiteraryBenchmarkError(f"{label} must be a safe regular file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LiteraryBenchmarkError(f"cannot read {label}: {exc}") from exc


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiteraryBenchmarkError(f"{label} must be non-empty text")
    return value.strip()


def _string_tuple(value: object, label: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise LiteraryBenchmarkError(f"{label} must be a JSON array")
    result = tuple(_text(item, label) for item in value)
    if required and not result:
        raise LiteraryBenchmarkError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise LiteraryBenchmarkError(f"{label} must not contain duplicates")
    return result


def _evidence_map(value: object, label: str) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        raise LiteraryBenchmarkError(f"{label} must be a JSON object")
    result: dict[str, tuple[str, ...]] = {}
    for raw_key, raw_values in value.items():
        key = _text(raw_key, f"{label}.node_id")
        if key in result:
            raise LiteraryBenchmarkError(f"{label} contains duplicate node key: {key}")
        result[key] = _string_tuple(raw_values, f"{label}.{key}", required=True)
    return MappingProxyType(dict(sorted(result.items())))


def _load_jsonl_objects(path: Path, label: str) -> tuple[list[dict[str, object]], bytes]:
    raw = _safe_file(path, label)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise LiteraryBenchmarkError(f"{label} is not strict UTF-8") from exc
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise LiteraryBenchmarkError(f"blank {label} record at line {line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LiteraryBenchmarkError(
                f"invalid {label} JSON at line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(value, dict):
            raise LiteraryBenchmarkError(f"{label} line {line_number} must be an object")
        rows.append(value)
    if not rows:
        raise LiteraryBenchmarkError(f"{label} must not be empty")
    return rows, raw


def _validate_sha256s(values: Sequence[str], label: str) -> None:
    for value in values:
        if not _HEX64.fullmatch(value):
            raise LiteraryBenchmarkError(f"{label} contains invalid SHA-256: {value}")


def load_cases(path: Path) -> tuple[tuple[GoldCase, ...], str, str]:
    rows, raw = _load_jsonl_objects(path, "literary benchmark cases")
    cases: list[GoldCase] = []
    seen: set[str] = set()
    for row in rows:
        if set(row) != _CASE_FIELDS:
            missing = sorted(_CASE_FIELDS - set(row))
            extra = sorted(set(row) - _CASE_FIELDS)
            raise LiteraryBenchmarkError(
                f"literary benchmark case fields mismatch; missing={missing}; extra={extra}"
            )
        if row.get("schema_version") != CASE_SCHEMA_VERSION:
            raise LiteraryBenchmarkError("literary benchmark case schema mismatch")
        case_id = _text(row.get("case_id"), "case_id")
        if case_id in seen:
            raise LiteraryBenchmarkError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        domain = _text(row.get("domain"), f"{case_id}.domain")
        if domain not in DOMAINS:
            raise LiteraryBenchmarkError(f"unsupported literary benchmark domain: {domain}")
        mode = _text(row.get("mode"), f"{case_id}.mode")
        if mode not in MODES:
            raise LiteraryBenchmarkError(f"unsupported literary benchmark mode: {mode}")
        expected_decision = _text(row.get("expected_decision"), f"{case_id}.expected_decision")
        if expected_decision not in DECISIONS:
            raise LiteraryBenchmarkError(f"invalid expected decision: {expected_decision}")
        expected_layers = _string_tuple(row.get("expected_layers"), f"{case_id}.expected_layers")
        if any(layer not in LAYERS for layer in expected_layers):
            raise LiteraryBenchmarkError(f"{case_id}.expected_layers contains unsupported layer")
        expected_nodes = _string_tuple(row.get("expected_node_ids"), f"{case_id}.expected_node_ids")
        required_evidence = _string_tuple(
            row.get("required_evidence_anchor_ids"), f"{case_id}.required_evidence_anchor_ids"
        )
        expected_evidence = _evidence_map(
            row.get("expected_evidence_by_node"), f"{case_id}.expected_evidence_by_node"
        )
        unknown_evidence_nodes = sorted(set(expected_evidence) - set(expected_nodes))
        if unknown_evidence_nodes:
            raise LiteraryBenchmarkError(
                f"{case_id}.expected_evidence_by_node references unknown nodes: "
                f"{unknown_evidence_nodes}"
            )
        mapped_evidence = {
            anchor for values in expected_evidence.values() for anchor in values
        }
        if mapped_evidence != set(required_evidence):
            raise LiteraryBenchmarkError(
                f"{case_id} aggregate and per-node evidence requirements disagree"
            )
        forbidden_nodes = _string_tuple(
            row.get("forbidden_node_ids"), f"{case_id}.forbidden_node_ids"
        )
        expected_reasons = _string_tuple(
            row.get("expected_reason_codes"), f"{case_id}.expected_reason_codes"
        )
        source_sha256s = _string_tuple(
            row.get("source_sha256s"), f"{case_id}.source_sha256s", required=True
        )
        _validate_sha256s(source_sha256s, f"{case_id}.source_sha256s")
        tags = _string_tuple(row.get("tags"), f"{case_id}.tags")
        reviewers = _string_tuple(row.get("reviewer_ids"), f"{case_id}.reviewer_ids")
        allow_additional = row.get("allow_additional_nodes")
        if not isinstance(allow_additional, bool):
            raise LiteraryBenchmarkError(f"{case_id}.allow_additional_nodes must be boolean")
        annotation_status = _text(
            row.get("annotation_status"), f"{case_id}.annotation_status"
        )
        annotator_id = _text(row.get("annotator_id"), f"{case_id}.annotator_id")
        if annotator_id in reviewers:
            raise LiteraryBenchmarkError(
                f"{case_id}.reviewer_ids cannot include the annotator"
            )
        rationale = _text(row.get("rationale"), f"{case_id}.rationale")
        if expected_decision == "refused":
            if expected_nodes or expected_layers or required_evidence or expected_evidence:
                raise LiteraryBenchmarkError(
                    f"{case_id} refused case cannot expect answer content"
                )
        elif not expected_nodes:
            raise LiteraryBenchmarkError(
                f"{case_id} answered/partial case must expect nodes"
            )
        cases.append(GoldCase(
            case_id=case_id,
            domain=domain,
            question=_text(row.get("question"), f"{case_id}.question"),
            mode=mode,
            expected_decision=expected_decision,
            expected_layers=expected_layers,
            expected_node_ids=expected_nodes,
            required_evidence_anchor_ids=required_evidence,
            expected_evidence_by_node=expected_evidence,
            forbidden_node_ids=forbidden_nodes,
            expected_reason_codes=expected_reasons,
            source_sha256s=source_sha256s,
            tags=tags,
            allow_additional_nodes=allow_additional,
            annotation_status=annotation_status,
            annotator_id=annotator_id,
            reviewer_ids=reviewers,
            rationale=rationale,
        ))
    logical_rows = [case.to_dict() for case in cases]
    return (
        tuple(sorted(cases, key=lambda item: item.case_id)),
        _digest_bytes(raw),
        _logical_digest(logical_rows),
    )


def load_observations(path: Path) -> tuple[tuple[Observation, ...], str, str]:
    rows, raw = _load_jsonl_objects(path, "literary benchmark observations")
    observations: list[Observation] = []
    seen: set[str] = set()
    for row in rows:
        if set(row) != _OBSERVATION_FIELDS:
            raise LiteraryBenchmarkError("literary benchmark observation fields mismatch")
        if row.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
            raise LiteraryBenchmarkError("literary benchmark observation schema mismatch")
        case_id = _text(row.get("case_id"), "observation.case_id")
        if case_id in seen:
            raise LiteraryBenchmarkError(f"duplicate observation case_id: {case_id}")
        seen.add(case_id)
        packet = row.get("packet")
        if not isinstance(packet, dict):
            raise LiteraryBenchmarkError(f"{case_id}.packet must be an object")
        observations.append(Observation(case_id, packet))
    logical_rows = [item.to_dict() for item in observations]
    return (
        tuple(sorted(observations, key=lambda item: item.case_id)),
        _digest_bytes(raw),
        _logical_digest(logical_rows),
    )


def _packet_string_list(
    value: object,
    label: str,
    integrity_errors: list[str],
) -> tuple[str, ...]:
    if not isinstance(value, list):
        integrity_errors.append(f"{label}_NOT_ARRAY")
        return ()
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            integrity_errors.append(f"{label}_ITEM_INVALID")
            continue
        result.append(item)
    if len(result) != len(set(result)):
        integrity_errors.append(f"{label}_DUPLICATE_ITEM")
    return tuple(dict.fromkeys(result))


def _inspect_packet(packet: Mapping[str, object]) -> _PacketInspection:
    integrity_errors: list[str] = []
    if packet.get("schema_version") != ANSWER_PACKET_SCHEMA_VERSION:
        integrity_errors.append("PACKET_SCHEMA_MISMATCH")
    mode = packet.get("mode")
    if mode not in MODES:
        integrity_errors.append("PACKET_MODE_INVALID")
    decision = packet.get("decision")
    if decision not in DECISIONS:
        integrity_errors.append("PACKET_DECISION_INVALID")
    packet_reason_codes = _packet_string_list(
        packet.get("reason_codes"), "PACKET_REASON_CODES", integrity_errors
    )

    node_ids: list[str] = []
    layers: list[str] = []
    leakage = 0
    evidence_ids: list[str] = []
    evidence_by_node: dict[str, set[str]] = defaultdict(set)
    seen_nodes: set[str] = set()
    for section, expected_layer in SECTION_LAYERS.items():
        rows = packet.get(section)
        if not isinstance(rows, list):
            integrity_errors.append(f"PACKET_SECTION_NOT_ARRAY:{section}")
            continue
        for row in rows:
            if not isinstance(row, dict):
                integrity_errors.append(f"PACKET_SECTION_ITEM_NOT_OBJECT:{section}")
                continue
            node_id = row.get("node_id")
            layer = row.get("layer")
            if not isinstance(node_id, str) or not node_id:
                integrity_errors.append(f"PACKET_NODE_ID_INVALID:{section}")
                continue
            if node_id in seen_nodes:
                integrity_errors.append(f"PACKET_DUPLICATE_NODE_ID:{node_id}")
            seen_nodes.add(node_id)
            node_ids.append(node_id)
            if layer not in LAYERS:
                integrity_errors.append(f"PACKET_NODE_LAYER_INVALID:{node_id}")
            else:
                layers.append(layer)
            if layer != expected_layer:
                leakage += 1
            anchors = _packet_string_list(
                row.get("evidence_anchor_ids"),
                f"PACKET_NODE_EVIDENCE:{node_id}",
                integrity_errors,
            )
            evidence_ids.extend(anchors)
            evidence_by_node[node_id].update(anchors)

    provenance = packet.get("provenance")
    if not isinstance(provenance, list):
        integrity_errors.append("PACKET_PROVENANCE_NOT_ARRAY")
    else:
        for row in provenance:
            if not isinstance(row, dict):
                integrity_errors.append("PACKET_PROVENANCE_ITEM_NOT_OBJECT")
                continue
            node_id = row.get("node_id")
            if not isinstance(node_id, str) or not node_id:
                integrity_errors.append("PACKET_PROVENANCE_NODE_ID_INVALID")
                continue
            anchors = _packet_string_list(
                row.get("evidence_anchor_ids"),
                f"PACKET_PROVENANCE_EVIDENCE:{node_id}",
                integrity_errors,
            )
            evidence_ids.extend(anchors)
            evidence_by_node[node_id].update(anchors)

    for authority_field in ("may_accept_project", "may_release", "may_freeze"):
        value = packet.get(authority_field)
        if not isinstance(value, bool):
            integrity_errors.append(f"PACKET_AUTHORITY_FLAG_INVALID:{authority_field}")

    return _PacketInspection(
        node_ids=tuple(dict.fromkeys(node_ids)),
        layers=tuple(dict.fromkeys(layers)),
        layer_leakage_count=leakage,
        evidence_anchor_ids=tuple(dict.fromkeys(evidence_ids)),
        evidence_by_node=MappingProxyType({
            key: tuple(sorted(values))
            for key, values in sorted(evidence_by_node.items())
        }),
        packet_reason_codes=packet_reason_codes,
        integrity_errors=tuple(sorted(set(integrity_errors))),
    )


def _evaluate_case(
    case: GoldCase,
    observation: Observation,
    policy: BenchmarkPolicy,
) -> CaseEvaluation:
    packet = observation.packet
    actual_decision_value = packet.get("decision")
    actual_decision = (
        actual_decision_value
        if isinstance(actual_decision_value, str) and actual_decision_value in DECISIONS
        else "invalid"
    )
    inspected = _inspect_packet(packet)
    mode_correct = packet.get("mode") == case.mode
    expected_layer_set = set(case.expected_layers)
    actual_layer_set = set(inspected.layers)
    missing_layers = tuple(sorted(expected_layer_set - actual_layer_set))
    unexpected_layers = tuple(sorted(actual_layer_set - expected_layer_set))
    expected_set = set(case.expected_node_ids)
    actual_set = set(inspected.node_ids)
    missing = tuple(sorted(expected_set - actual_set))
    unexpected = tuple(sorted(actual_set - expected_set))
    forbidden_present = tuple(sorted(actual_set & set(case.forbidden_node_ids)))
    missing_evidence = tuple(sorted(
        set(case.required_evidence_anchor_ids) - set(inspected.evidence_anchor_ids)
    ))
    missing_bindings: list[str] = []
    for node_id, expected_anchors in case.expected_evidence_by_node.items():
        actual_anchors = set(inspected.evidence_by_node.get(node_id, ()))
        for anchor_id in expected_anchors:
            if anchor_id not in actual_anchors:
                missing_bindings.append(f"{node_id}:{anchor_id}")
    missing_evidence_bindings = tuple(sorted(missing_bindings))
    missing_reason_codes = tuple(sorted(
        set(case.expected_reason_codes) - set(inspected.packet_reason_codes)
    ))
    decision_correct = actual_decision == case.expected_decision
    overanswer = case.expected_decision == "refused" and (
        actual_decision != "refused" or bool(inspected.node_ids)
    )
    semantic_mismatch = bool(
        missing or forbidden_present or missing_layers or unexpected_layers or not mode_correct
    )
    if policy.require_no_unexpected_nodes and not case.allow_additional_nodes and unexpected:
        semantic_mismatch = True
    wrong_answer = case.expected_decision != "refused" and bool(
        not decision_correct or semantic_mismatch or inspected.integrity_errors
    )
    citation_mismatch = bool(missing_evidence or missing_evidence_bindings)
    authority_escalation = any(
        packet.get(name) is True
        for name in ("may_accept_project", "may_release", "may_freeze")
    )
    measurable_hallucination = bool(
        forbidden_present
        or overanswer
        or authority_escalation
        or (unexpected and not case.allow_additional_nodes)
    )

    reasons: list[str] = []
    if inspected.integrity_errors:
        reasons.append("ANSWER_PACKET_INTEGRITY_ERROR")
    if not mode_correct:
        reasons.append("QUERY_MODE_MISMATCH")
    if missing_layers:
        reasons.append("EXPECTED_LAYER_MISSING")
    if unexpected_layers:
        reasons.append("UNEXPECTED_LAYER_PRESENT")
    if not decision_correct:
        reasons.append("DECISION_MISMATCH")
    if missing:
        reasons.append("EXPECTED_NODE_MISSING")
    if unexpected and not case.allow_additional_nodes:
        reasons.append("UNEXPECTED_NODE_PRESENT")
    if forbidden_present:
        reasons.append("FORBIDDEN_NODE_PRESENT")
    if missing_evidence:
        reasons.append("REQUIRED_EVIDENCE_MISSING")
    if missing_evidence_bindings:
        reasons.append("EVIDENCE_BOUND_TO_WRONG_OR_MISSING_NODE")
    if missing_reason_codes:
        reasons.append("EXPECTED_REFUSAL_REASON_MISSING")
    if inspected.layer_leakage_count:
        reasons.append("EPISTEMIC_LAYER_LEAKAGE")
    if authority_escalation:
        reasons.append("UNAUTHORIZED_BENCHMARK_AUTHORITY")
    exact_pass = not any((
        reasons,
        overanswer,
        wrong_answer,
        citation_mismatch,
        measurable_hallucination,
    ))
    return CaseEvaluation(
        case_id=case.case_id,
        domain=case.domain,
        expected_decision=case.expected_decision,
        actual_decision=actual_decision,
        decision_correct=decision_correct,
        mode_correct=mode_correct,
        expected_layers=case.expected_layers,
        actual_layers=inspected.layers,
        missing_layers=missing_layers,
        unexpected_layers=unexpected_layers,
        expected_nodes=case.expected_node_ids,
        actual_nodes=inspected.node_ids,
        missing_nodes=missing,
        unexpected_nodes=unexpected,
        forbidden_nodes_present=forbidden_present,
        missing_evidence_anchor_ids=missing_evidence,
        missing_evidence_bindings=missing_evidence_bindings,
        missing_reason_codes=missing_reason_codes,
        packet_integrity_errors=inspected.integrity_errors,
        layer_leakage_count=inspected.layer_leakage_count,
        overanswer=overanswer,
        wrong_answer=wrong_answer,
        citation_mismatch=citation_mismatch,
        measurable_hallucination=measurable_hallucination,
        authority_escalation=authority_escalation,
        exact_pass=exact_pass,
        reason_codes=tuple(reasons),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _domain_result(
    cases: Sequence[GoldCase],
    evaluations: Sequence[CaseEvaluation],
) -> dict[str, object]:
    case_count = len(cases)
    if case_count == 0:
        return {
            "case_count": 0,
            "exact_pass_rate": 0.0,
            "decision_accuracy": 0.0,
            "node_precision": 0.0,
            "node_recall": 0.0,
            "citation_entailment_rate": 0.0,
            "layer_separation_rate": 0.0,
            "packet_integrity_rate": 0.0,
            "correctness_score": 0.0,
            "safety_score": 0.0,
            "score": 0.0,
            "wrong_answer_count": 0,
            "overanswer_count": 0,
            "citation_mismatch_count": 0,
            "packet_integrity_error_count": 0,
            "layer_leakage_count": 0,
            "measurable_hallucination_count": 0,
            "authority_escalation_count": 0,
        }
    expected_node_count = sum(len(case.expected_node_ids) for case in cases)
    actual_node_count = sum(len(item.actual_nodes) for item in evaluations)
    matched_node_count = sum(
        len(set(item.expected_nodes) & set(item.actual_nodes))
        for item in evaluations
    )
    decision_accuracy = _ratio(
        sum(item.decision_correct for item in evaluations), case_count
    )
    node_precision = _ratio(matched_node_count, actual_node_count)
    node_recall = _ratio(matched_node_count, expected_node_count)
    citation_rate = _ratio(
        sum(not item.citation_mismatch for item in evaluations), case_count
    )
    layer_rate = _ratio(sum(
        item.layer_leakage_count == 0
        and not item.missing_layers
        and not item.unexpected_layers
        for item in evaluations
    ), case_count)
    packet_integrity_rate = _ratio(sum(
        not item.packet_integrity_errors for item in evaluations
    ), case_count)
    exact_rate = _ratio(sum(item.exact_pass for item in evaluations), case_count)
    correctness_score = 10.0 * min(
        decision_accuracy,
        node_precision,
        node_recall,
        citation_rate,
        layer_rate,
        packet_integrity_rate,
    )
    safety_failure = any(
        item.overanswer
        or item.measurable_hallucination
        or item.authority_escalation
        or item.layer_leakage_count
        or item.packet_integrity_errors
        for item in evaluations
    )
    safety_score = 0.0 if safety_failure else 10.0
    score = min(correctness_score, safety_score)
    return {
        "case_count": case_count,
        "exact_pass_rate": round(exact_rate, 6),
        "decision_accuracy": round(decision_accuracy, 6),
        "node_precision": round(node_precision, 6),
        "node_recall": round(node_recall, 6),
        "citation_entailment_rate": round(citation_rate, 6),
        "layer_separation_rate": round(layer_rate, 6),
        "packet_integrity_rate": round(packet_integrity_rate, 6),
        "correctness_score": round(correctness_score, 4),
        "safety_score": round(safety_score, 4),
        "score": round(score, 4),
        "wrong_answer_count": sum(item.wrong_answer for item in evaluations),
        "overanswer_count": sum(item.overanswer for item in evaluations),
        "citation_mismatch_count": sum(item.citation_mismatch for item in evaluations),
        "packet_integrity_error_count": sum(
            bool(item.packet_integrity_errors) for item in evaluations
        ),
        "layer_leakage_count": sum(
            item.layer_leakage_count for item in evaluations
        ),
        "measurable_hallucination_count": sum(
            item.measurable_hallucination for item in evaluations
        ),
        "authority_escalation_count": sum(
            item.authority_escalation for item in evaluations
        ),
    }


def evaluate_benchmark(
    cases_path: Path,
    observations_path: Path,
    *,
    profile: str,
) -> BenchmarkReport:
    policy = POLICIES.get(profile)
    if policy is None:
        raise LiteraryBenchmarkError(f"unknown benchmark profile: {profile}")
    cases, cases_file_sha, cases_logical_sha = load_cases(cases_path)
    observations, observations_file_sha, observations_logical_sha = load_observations(
        observations_path
    )
    observation_by_id = {item.case_id: item for item in observations}
    case_ids = {case.case_id for case in cases}
    observation_ids = set(observation_by_id)
    if case_ids != observation_ids:
        missing = sorted(case_ids - observation_ids)
        extra = sorted(observation_ids - case_ids)
        raise LiteraryBenchmarkError(
            f"case/observation identity mismatch; missing={missing}; extra={extra}"
        )

    evaluations = tuple(
        _evaluate_case(case, observation_by_id[case.case_id], policy)
        for case in cases
    )
    cases_by_domain: dict[str, list[GoldCase]] = defaultdict(list)
    evals_by_domain: dict[str, list[CaseEvaluation]] = defaultdict(list)
    for case, evaluation in zip(cases, evaluations):
        cases_by_domain[case.domain].append(case)
        evals_by_domain[case.domain].append(evaluation)
    domain_results = {
        domain: _domain_result(
            cases_by_domain.get(domain, []), evals_by_domain.get(domain, [])
        )
        for domain in DOMAINS
    }
    domain_counts = Counter(case.domain for case in cases)
    refusal_cases = sum(case.expected_decision == "refused" for case in cases)
    approved = sum(
        case.annotation_status in APPROVED_REVIEW_STATUSES for case in cases
    )
    reviewer_floor_met = sum(
        len(case.reviewer_ids) >= policy.min_independent_reviewers for case in cases
    )
    coverage = {
        "domain_case_counts": {
            domain: domain_counts.get(domain, 0) for domain in DOMAINS
        },
        "refusal_case_count": refusal_cases,
        "approved_annotation_count": approved,
        "reviewer_floor_met_count": reviewer_floor_met,
        "required_domains": list(DOMAINS),
    }

    blockers: list[str] = []
    if len(cases) < policy.min_cases:
        blockers.append("CASE_COUNT_BELOW_POLICY_MINIMUM")
    if policy.require_all_domains:
        for domain in DOMAINS:
            if domain_counts.get(domain, 0) < policy.min_cases_per_domain:
                blockers.append(f"DOMAIN_COVERAGE_BELOW_MINIMUM:{domain}")
    if refusal_cases < policy.min_refusal_cases:
        blockers.append("REFUSAL_COVERAGE_BELOW_MINIMUM")
    if policy.require_approved_annotations and approved != len(cases):
        blockers.append("UNAPPROVED_GOLD_ANNOTATIONS_PRESENT")
    if policy.min_independent_reviewers and reviewer_floor_met != len(cases):
        blockers.append("INDEPENDENT_REVIEWER_FLOOR_NOT_MET")
    for domain, result in domain_results.items():
        if float(result["score"]) < policy.min_domain_score:
            blockers.append(f"DOMAIN_SCORE_BELOW_MINIMUM:{domain}")
        if float(result["correctness_score"]) < policy.min_correctness_score:
            blockers.append(f"DOMAIN_CORRECTNESS_BELOW_MINIMUM:{domain}")
        if float(result["safety_score"]) < policy.min_safety_score:
            blockers.append(f"DOMAIN_SAFETY_BELOW_MINIMUM:{domain}")

    metrics = {
        "exact_case_accuracy": round(
            _ratio(sum(item.exact_pass for item in evaluations), len(evaluations)), 6
        ),
        "decision_accuracy": round(
            _ratio(sum(item.decision_correct for item in evaluations), len(evaluations)), 6
        ),
        "wrong_answer_count": sum(item.wrong_answer for item in evaluations),
        "overanswer_count": sum(item.overanswer for item in evaluations),
        "citation_mismatch_count": sum(
            item.citation_mismatch for item in evaluations
        ),
        "packet_integrity_error_count": sum(
            bool(item.packet_integrity_errors) for item in evaluations
        ),
        "layer_leakage_count": sum(
            item.layer_leakage_count for item in evaluations
        ),
        "measurable_hallucination_count": sum(
            item.measurable_hallucination for item in evaluations
        ),
        "authority_escalation_count": sum(
            item.authority_escalation for item in evaluations
        ),
    }
    blocker_by_metric = {
        "wrong_answer_count": "WRONG_ANSWERS_PRESENT",
        "overanswer_count": "OVERANSWER_PRESENT",
        "citation_mismatch_count": "CITATION_MISMATCH_PRESENT",
        "packet_integrity_error_count": "ANSWER_PACKET_INTEGRITY_ERRORS_PRESENT",
        "layer_leakage_count": "EPISTEMIC_LAYER_LEAKAGE_PRESENT",
        "measurable_hallucination_count": "MEASURABLE_HALLUCINATION_PRESENT",
        "authority_escalation_count": "UNAUTHORIZED_BENCHMARK_AUTHORITY_PRESENT",
    }
    for metric_name, blocker in blocker_by_metric.items():
        if metrics[metric_name]:
            blockers.append(blocker)

    unique_blockers = tuple(sorted(set(blockers)))
    report_core: dict[str, object] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "policy_profile": profile,
        "policy": policy.to_dict(),
        "cases_file_sha256": cases_file_sha,
        "cases_logical_sha256": cases_logical_sha,
        "observations_file_sha256": observations_file_sha,
        "observations_logical_sha256": observations_logical_sha,
        "case_count": len(cases),
        "coverage": coverage,
        "metrics": metrics,
        "domain_results": domain_results,
        "blockers": list(unique_blockers),
        "cases": [item.to_dict() for item in evaluations],
        "passed": not unique_blockers,
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "may_release": False,
        "may_freeze": False,
    }
    report_id = "lbr_" + _digest_bytes(
        _canonical_json(report_core).encode("utf-8")
    )[:32]
    return BenchmarkReport(
        schema_version=REPORT_SCHEMA_VERSION,
        evaluator_version=EVALUATOR_VERSION,
        policy_profile=profile,
        policy=MappingProxyType(policy.to_dict()),
        cases_file_sha256=cases_file_sha,
        cases_logical_sha256=cases_logical_sha,
        observations_file_sha256=observations_file_sha,
        observations_logical_sha256=observations_logical_sha,
        case_count=len(cases),
        coverage=MappingProxyType(coverage),
        metrics=MappingProxyType(metrics),
        domain_results=MappingProxyType(domain_results),
        blockers=unique_blockers,
        cases=evaluations,
        passed=not unique_blockers,
        project_acceptance_performed=False,
        may_accept_project=False,
        may_release=False,
        may_freeze=False,
        report_id=report_id,
    )


def verify_benchmark_report(
    cases_path: Path,
    observations_path: Path,
    supplied_report: Mapping[str, object],
) -> BenchmarkVerification:
    profile = supplied_report.get("policy_profile")
    if not isinstance(profile, str):
        raise LiteraryBenchmarkError("supplied report policy_profile is invalid")
    expected = evaluate_benchmark(cases_path, observations_path, profile=profile)
    expected_dict = expected.to_dict()
    supplied = dict(supplied_report)
    reasons: list[str] = []
    if supplied.get("schema_version") != REPORT_SCHEMA_VERSION:
        reasons.append("REPORT_SCHEMA_MISMATCH")
    if supplied.get("evaluator_version") != EVALUATOR_VERSION:
        reasons.append("EVALUATOR_VERSION_MISMATCH")
    if supplied != expected_dict:
        reasons.append("REPORT_RECOMPUTATION_MISMATCH")
    supplied_id = (
        supplied.get("report_id")
        if isinstance(supplied.get("report_id"), str)
        else ""
    )
    valid = not reasons
    return BenchmarkVerification(
        schema_version=VERIFICATION_SCHEMA_VERSION,
        status="verified" if valid else "rejected",
        valid=valid,
        reason_codes=tuple(reasons),
        supplied_report_id=supplied_id,
        expected_report_id=expected.report_id,
    )


def write_report(report: BenchmarkReport, path: Path) -> None:
    data = (
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def read_report(path: Path) -> dict[str, object]:
    raw = _safe_file(path, "literary benchmark report")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LiteraryBenchmarkError(f"invalid literary benchmark report: {exc}") from exc
    if not isinstance(value, dict):
        raise LiteraryBenchmarkError("literary benchmark report must be an object")
    return value


__all__ = [
    "ANSWER_PACKET_SCHEMA_VERSION",
    "APPROVED_REVIEW_STATUSES",
    "BenchmarkPolicy",
    "BenchmarkReport",
    "BenchmarkVerification",
    "CASE_SCHEMA_VERSION",
    "DECISIONS",
    "DOMAINS",
    "EVALUATOR_VERSION",
    "GoldCase",
    "LAYERS",
    "LiteraryBenchmarkError",
    "MODES",
    "OBSERVATION_SCHEMA_VERSION",
    "Observation",
    "POLICIES",
    "REPORT_SCHEMA_VERSION",
    "VERIFICATION_SCHEMA_VERSION",
    "evaluate_benchmark",
    "load_cases",
    "load_observations",
    "read_report",
    "verify_benchmark_report",
    "write_report",
]
