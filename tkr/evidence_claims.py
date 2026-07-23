"""Claim-to-Evidence graph contracts for Stage 1.

The literary assertion model stores the epistemic tier and direct support IDs.
This module turns those references into an explicit graph that can represent
supporting, contradicting, and contextual Evidence without weakening the A/B/C
contract.

The graph is deterministic and fail-closed:

* A Claims require at least one clean supporting Evidence record;
* the set of support edges must equal the Claim's declared evidence IDs;
* B Claims require multiple independent supports through Evidence or A Claims;
* C Claims remain explicitly attributed interpretations;
* contradicting/context edges are retained but never silently counted as
  positive support;
* unknown Claim or Evidence identifiers invalidate the graph.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Iterable, Mapping, Sequence

from .literary_models import KnowledgeAssertion, stable_id

CLAIM_EVIDENCE_EDGE_SCHEMA_VERSION: Final = "tkr-claim-evidence-edge-v1"
CLAIM_GRAPH_REPORT_SCHEMA_VERSION: Final = "tkr-claim-graph-report-v1"
CLAIM_GRAPH_VERSION: Final = "tkr-claim-evidence-graph-v1"
EDGE_RELATIONS: Final = frozenset({"support", "contradict", "context"})
KNOWN_EVIDENCE_STATUSES: Final = frozenset(
    {"clean", "contaminated", "non_body", "needs_review"}
)


class ClaimEvidenceError(ValueError):
    """Raised when a Claim-Evidence graph violates its evidence contract."""


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClaimEvidenceError(f"{name} must be a non-empty string")
    return value


def _require_positive(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ClaimEvidenceError(f"{name} must be a positive integer")
    return value


def claim_evidence_edge_id(
    assertion_id: str,
    evidence_id: str,
    relation: str,
) -> str:
    return stable_id(
        "cee_",
        CLAIM_EVIDENCE_EDGE_SCHEMA_VERSION,
        assertion_id,
        evidence_id,
        relation,
    )


@dataclass(frozen=True, slots=True)
class ClaimEvidenceEdge:
    schema_version: str
    edge_id: str
    assertion_id: str
    evidence_id: str
    relation: str
    evidence_source_status: str
    ordinal: int
    confidence: float
    review_status: str

    def __post_init__(self) -> None:
        if self.schema_version != CLAIM_EVIDENCE_EDGE_SCHEMA_VERSION:
            raise ClaimEvidenceError("Claim-Evidence edge schema version mismatch")
        for name in (
            "edge_id",
            "assertion_id",
            "evidence_id",
            "relation",
            "evidence_source_status",
            "review_status",
        ):
            _require_text(getattr(self, name), name)
        if self.relation not in EDGE_RELATIONS:
            raise ClaimEvidenceError(f"unsupported Claim-Evidence relation: {self.relation}")
        if self.evidence_source_status not in KNOWN_EVIDENCE_STATUSES:
            raise ClaimEvidenceError("unsupported evidence source status")
        _require_positive(self.ordinal, "ordinal")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise ClaimEvidenceError("edge confidence must be numeric")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ClaimEvidenceError("edge confidence must be between zero and one")
        expected = claim_evidence_edge_id(self.assertion_id, self.evidence_id, self.relation)
        if self.edge_id != expected:
            raise ClaimEvidenceError("Claim-Evidence edge identifier mismatch")
        if self.review_status not in {"accepted_edge", "review_edge"}:
            raise ClaimEvidenceError("unsupported edge review status")
        if self.relation == "support" and self.review_status != "accepted_edge":
            raise ClaimEvidenceError("support edges must be accepted edges")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ClaimGraphFinding:
    code: str
    assertion_id: str
    evidence_id: str
    message: str

    def __post_init__(self) -> None:
        for name in ("code", "assertion_id", "message"):
            _require_text(getattr(self, name), name)
        if not isinstance(self.evidence_id, str):
            raise ClaimEvidenceError("evidence_id must be a string")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ClaimGraphReport:
    schema_version: str
    claim_graph_version: str
    valid: bool
    assertion_count: int
    edge_count: int
    support_edge_count: int
    contradict_edge_count: int
    context_edge_count: int
    tier_a_count: int
    tier_b_count: int
    tier_c_count: int
    unsupported_assertion_count: int
    unknown_evidence_reference_count: int
    blocked_support_count: int
    findings: tuple[ClaimGraphFinding, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CLAIM_GRAPH_REPORT_SCHEMA_VERSION:
            raise ClaimEvidenceError("Claim graph report schema version mismatch")
        if self.claim_graph_version != CLAIM_GRAPH_VERSION:
            raise ClaimEvidenceError("Claim graph version mismatch")
        for name in (
            "assertion_count",
            "edge_count",
            "support_edge_count",
            "contradict_edge_count",
            "context_edge_count",
            "tier_a_count",
            "tier_b_count",
            "tier_c_count",
            "unsupported_assertion_count",
            "unknown_evidence_reference_count",
            "blocked_support_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ClaimEvidenceError(f"{name} must be a non-negative integer")
        if self.edge_count != (
            self.support_edge_count + self.contradict_edge_count + self.context_edge_count
        ):
            raise ClaimEvidenceError("edge relation counts do not sum to edge_count")
        if self.assertion_count != self.tier_a_count + self.tier_b_count + self.tier_c_count:
            raise ClaimEvidenceError("tier counts do not sum to assertion_count")
        if self.valid != (not self.findings):
            raise ClaimEvidenceError("Claim graph valid flag does not match findings")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["findings"] = [item.to_dict() for item in self.findings]
        return payload


@dataclass(frozen=True, slots=True)
class ClaimGraphBuildResult:
    edges: tuple[ClaimEvidenceEdge, ...]
    report: ClaimGraphReport


def _normalize_optional_edges(
    values: Mapping[str, Sequence[str]] | None,
) -> dict[str, tuple[str, ...]]:
    if values is None:
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for assertion_id, evidence_ids in values.items():
        _require_text(assertion_id, "assertion_id")
        if isinstance(evidence_ids, (str, bytes)) or not isinstance(evidence_ids, Sequence):
            raise ClaimEvidenceError("optional evidence edges must be sequences")
        cleaned: list[str] = []
        for evidence_id in evidence_ids:
            value = _require_text(evidence_id, "evidence_id")
            if value not in cleaned:
                cleaned.append(value)
        result[assertion_id] = tuple(cleaned)
    return result


def build_claim_evidence_edges(
    assertions: Sequence[KnowledgeAssertion],
    evidence_status_by_id: Mapping[str, str],
    *,
    contradicting_evidence: Mapping[str, Sequence[str]] | None = None,
    contextual_evidence: Mapping[str, Sequence[str]] | None = None,
) -> ClaimGraphBuildResult:
    """Build explicit deterministic edges and immediately validate the graph."""

    contradiction_map = _normalize_optional_edges(contradicting_evidence)
    context_map = _normalize_optional_edges(contextual_evidence)
    assertion_ids = {item.assertion_id for item in assertions}
    unknown_optional_claims = (set(contradiction_map) | set(context_map)) - assertion_ids
    if unknown_optional_claims:
        raise ClaimEvidenceError(
            "optional evidence edges reference unknown Claims: "
            + ",".join(sorted(unknown_optional_claims))
        )

    edges: list[ClaimEvidenceEdge] = []
    for assertion in sorted(assertions, key=lambda item: item.assertion_id):
        relation_groups = (
            ("support", assertion.evidence_anchor_ids),
            ("contradict", contradiction_map.get(assertion.assertion_id, ())),
            ("context", context_map.get(assertion.assertion_id, ())),
        )
        for relation, evidence_ids in relation_groups:
            for ordinal, evidence_id in enumerate(sorted(set(evidence_ids)), start=1):
                status = evidence_status_by_id.get(evidence_id, "needs_review")
                edges.append(
                    ClaimEvidenceEdge(
                        CLAIM_EVIDENCE_EDGE_SCHEMA_VERSION,
                        claim_evidence_edge_id(assertion.assertion_id, evidence_id, relation),
                        assertion.assertion_id,
                        evidence_id,
                        relation,
                        status,
                        ordinal,
                        1.0 if relation == "support" else float(assertion.confidence),
                        "accepted_edge" if relation == "support" else "review_edge",
                    )
                )
    report = validate_claim_evidence_graph(assertions, evidence_status_by_id, edges)
    return ClaimGraphBuildResult(tuple(edges), report)


def validate_claim_evidence_graph(
    assertions: Sequence[KnowledgeAssertion],
    evidence_status_by_id: Mapping[str, str],
    edges: Sequence[ClaimEvidenceEdge],
) -> ClaimGraphReport:
    """Validate referential integrity and the non-promoting A/B/C contract."""

    assertion_by_id: dict[str, KnowledgeAssertion] = {}
    findings: list[ClaimGraphFinding] = []
    for assertion in assertions:
        if assertion.assertion_id in assertion_by_id:
            findings.append(
                ClaimGraphFinding(
                    "CLAIM_IDENTIFIER_DUPLICATE",
                    assertion.assertion_id,
                    "",
                    "Claim identifier occurs more than once",
                )
            )
        assertion_by_id[assertion.assertion_id] = assertion

    edge_ids: set[str] = set()
    edges_by_claim: dict[str, list[ClaimEvidenceEdge]] = {}
    unknown_evidence_references = 0
    blocked_supports = 0
    for edge in edges:
        if edge.edge_id in edge_ids:
            findings.append(
                ClaimGraphFinding(
                    "CLAIM_EVIDENCE_EDGE_DUPLICATE",
                    edge.assertion_id,
                    edge.evidence_id,
                    "Claim-Evidence edge identifier occurs more than once",
                )
            )
        edge_ids.add(edge.edge_id)
        if edge.assertion_id not in assertion_by_id:
            findings.append(
                ClaimGraphFinding(
                    "CLAIM_EDGE_UNKNOWN_ASSERTION",
                    edge.assertion_id,
                    edge.evidence_id,
                    "Claim-Evidence edge references an unknown Claim",
                )
            )
            continue
        edges_by_claim.setdefault(edge.assertion_id, []).append(edge)
        if edge.evidence_id not in evidence_status_by_id:
            unknown_evidence_references += 1
            findings.append(
                ClaimGraphFinding(
                    "CLAIM_EDGE_UNKNOWN_EVIDENCE",
                    edge.assertion_id,
                    edge.evidence_id,
                    "Claim-Evidence edge references unknown Evidence",
                )
            )
        if edge.relation == "support" and edge.evidence_source_status != "clean":
            blocked_supports += 1
            findings.append(
                ClaimGraphFinding(
                    "CLAIM_SUPPORT_NON_CLEAN_EVIDENCE",
                    edge.assertion_id,
                    edge.evidence_id,
                    "positive support cannot use contaminated, non-body, or review Evidence",
                )
            )
        expected_status = evidence_status_by_id.get(edge.evidence_id)
        if expected_status is not None and expected_status != edge.evidence_source_status:
            findings.append(
                ClaimGraphFinding(
                    "CLAIM_EDGE_EVIDENCE_STATUS_MISMATCH",
                    edge.assertion_id,
                    edge.evidence_id,
                    "edge source status differs from the Evidence registry",
                )
            )

    unsupported_assertions = 0
    for assertion in assertions:
        claim_edges = edges_by_claim.get(assertion.assertion_id, [])
        support_ids = {
            edge.evidence_id for edge in claim_edges if edge.relation == "support"
        }
        declared_support = set(assertion.evidence_anchor_ids)
        if support_ids != declared_support:
            findings.append(
                ClaimGraphFinding(
                    "CLAIM_SUPPORT_DECLARATION_MISMATCH",
                    assertion.assertion_id,
                    "",
                    "support edge set differs from the Claim evidence declaration",
                )
            )
        if assertion.tier == "A":
            clean_supports = {
                evidence_id
                for evidence_id in support_ids
                if evidence_status_by_id.get(evidence_id) == "clean"
            }
            if not clean_supports:
                unsupported_assertions += 1
                findings.append(
                    ClaimGraphFinding(
                        "TIER_A_WITHOUT_CLEAN_EVIDENCE",
                        assertion.assertion_id,
                        "",
                        "A Claim requires at least one exact clean Evidence record",
                    )
                )
        elif assertion.tier == "B":
            independent_count = len(support_ids) + len(set(assertion.supporting_assertion_ids))
            if independent_count < 2:
                unsupported_assertions += 1
                findings.append(
                    ClaimGraphFinding(
                        "TIER_B_WITHOUT_MULTIPLE_SUPPORTS",
                        assertion.assertion_id,
                        "",
                        "B Claim requires at least two independent supports",
                    )
                )
            for support_claim_id in assertion.supporting_assertion_ids:
                supporting = assertion_by_id.get(support_claim_id)
                if supporting is None:
                    findings.append(
                        ClaimGraphFinding(
                            "TIER_B_UNKNOWN_SUPPORTING_CLAIM",
                            assertion.assertion_id,
                            "",
                            f"supporting Claim is unknown: {support_claim_id}",
                        )
                    )
                elif supporting.tier != "A":
                    findings.append(
                        ClaimGraphFinding(
                            "TIER_B_SUPPORT_NOT_TIER_A",
                            assertion.assertion_id,
                            "",
                            f"B synthesis support is not A-grade: {support_claim_id}",
                        )
                    )
        else:
            if assertion.assertion_kind != "interpretation" or assertion.attribution != "model_interpretation":
                unsupported_assertions += 1
                findings.append(
                    ClaimGraphFinding(
                        "TIER_C_ATTRIBUTION_INVALID",
                        assertion.assertion_id,
                        "",
                        "C Claim must remain explicit model interpretation",
                    )
                )
            if not support_ids and not assertion.supporting_assertion_ids:
                unsupported_assertions += 1
                findings.append(
                    ClaimGraphFinding(
                        "TIER_C_WITHOUT_SUPPORT",
                        assertion.assertion_id,
                        "",
                        "C interpretation requires explicit A/B support",
                    )
                )

    support_count = sum(edge.relation == "support" for edge in edges)
    contradict_count = sum(edge.relation == "contradict" for edge in edges)
    context_count = sum(edge.relation == "context" for edge in edges)
    return ClaimGraphReport(
        CLAIM_GRAPH_REPORT_SCHEMA_VERSION,
        CLAIM_GRAPH_VERSION,
        not findings,
        len(assertions),
        len(edges),
        support_count,
        contradict_count,
        context_count,
        sum(item.tier == "A" for item in assertions),
        sum(item.tier == "B" for item in assertions),
        sum(item.tier == "C" for item in assertions),
        unsupported_assertions,
        unknown_evidence_references,
        blocked_supports,
        tuple(findings),
    )


def edge_from_dict(payload: Mapping[str, object]) -> ClaimEvidenceEdge:
    try:
        return ClaimEvidenceEdge(**dict(payload))
    except TypeError as exc:
        raise ClaimEvidenceError(f"invalid Claim-Evidence edge record: {exc}") from exc


def graph_report_from_dict(payload: Mapping[str, object]) -> ClaimGraphReport:
    data = dict(payload)
    raw_findings = data.get("findings", [])
    if not isinstance(raw_findings, list):
        raise ClaimEvidenceError("findings must be a JSON array")
    findings: list[ClaimGraphFinding] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            raise ClaimEvidenceError("finding must be a JSON object")
        findings.append(ClaimGraphFinding(**item))
    data["findings"] = tuple(findings)
    try:
        return ClaimGraphReport(**data)
    except TypeError as exc:
        raise ClaimEvidenceError(f"invalid Claim graph report: {exc}") from exc


__all__ = [
    "CLAIM_EVIDENCE_EDGE_SCHEMA_VERSION",
    "CLAIM_GRAPH_REPORT_SCHEMA_VERSION",
    "CLAIM_GRAPH_VERSION",
    "EDGE_RELATIONS",
    "ClaimEvidenceEdge",
    "ClaimEvidenceError",
    "ClaimGraphBuildResult",
    "ClaimGraphFinding",
    "ClaimGraphReport",
    "build_claim_evidence_edges",
    "claim_evidence_edge_id",
    "edge_from_dict",
    "graph_report_from_dict",
    "validate_claim_evidence_graph",
]
