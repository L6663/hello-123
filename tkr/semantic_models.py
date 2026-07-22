"""Typed Stage 3 semantic extraction contracts and deterministic identifiers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Final, Iterable, Mapping

SEMANTIC_CANDIDATE_SCHEMA_VERSION: Final = "tkr-semantic-candidate-v1"
SEMANTIC_FINDING_SCHEMA_VERSION: Final = "tkr-semantic-finding-v1"
MODEL_EXTRACTION_TASK_SCHEMA_VERSION: Final = "tkr-model-extraction-task-v1"
SEMANTIC_REPORT_SCHEMA_VERSION: Final = "tkr-semantic-report-v1"
SEMANTIC_EXTRACTOR_VERSION: Final = "5.9.0-stage3"
OFFSET_BASIS: Final = "decoded_text_without_external_bom"

CLAIM_TYPES: Final = frozenset({"alias", "defeats", "located_in", "permission", "count", "date"})
DISCOURSE_STATUSES: Final = frozenset(
    {
        "assertion",
        "belief",
        "suspicion",
        "rumor",
        "accusation",
        "hypothetical",
        "question",
        "future_intent",
    }
)
FACTUAL_STATUSES: Final = frozenset(
    {
        "asserted_fact",
        "negated_fact",
        "belief",
        "suspicion",
        "rumor",
        "accusation",
        "hypothetical",
        "question",
        "future_intent",
    }
)


class SemanticExtractionError(ValueError):
    """Raised when Stage 3 cannot finish safely or a contract is malformed."""


@dataclass(frozen=True, slots=True)
class SemanticPolicy:
    max_candidates: int = 200_000
    max_findings: int = 50_000
    max_model_tasks: int = 50_000
    max_clause_characters: int = 600
    emit_model_tasks: bool = True
    run_entity_normalization: bool = True

    def __post_init__(self) -> None:
        for name in (
            "max_candidates",
            "max_findings",
            "max_model_tasks",
            "max_clause_characters",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SemanticExtractionError(f"{name} must be a positive integer")
        for name in ("emit_model_tasks", "run_entity_normalization"):
            if not isinstance(getattr(self, name), bool):
                raise SemanticExtractionError(f"{name} must be boolean")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SemanticCandidate:
    schema_version: str
    candidate_id: str
    claim_type: str
    subject: str
    object: str
    value: str | int | float | None
    unit: str
    polarity: bool
    discourse_status: str
    factual_status: str
    attributor: str
    source_id: str
    source_sha256: str
    unit_id: str
    extraction_rule: str
    confidence: str
    evidence_start: int
    evidence_end: int
    evidence_start_line: int
    evidence_end_line: int
    evidence_sha256: str
    evidence_text: str
    trigger_start: int
    trigger_end: int
    validation_status: str
    validation_result_id: str | None
    validation_reason_codes: tuple[str, ...]
    may_index: bool
    requires_review: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["validation_reason_codes"] = list(self.validation_reason_codes)
        return payload


@dataclass(frozen=True, slots=True)
class SemanticFinding:
    schema_version: str
    finding_id: str
    rule_id: str
    severity: str
    confidence: str
    recommended_action: str
    source_id: str
    unit_id: str | None
    candidate_id: str | None
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    signals: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ModelExtractionTask:
    schema_version: str
    task_id: str
    source_id: str
    source_sha256: str
    unit_id: str
    evidence_start: int
    evidence_end: int
    evidence_sha256: str
    evidence_text: str
    allowed_claim_types: tuple[str, ...]
    instruction_version: str
    output_schema_version: str
    may_accept_directly: bool
    requires_deterministic_validation: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SemanticExtractionReport:
    schema_version: str
    extractor_version: str
    source_id: str
    source_sha256: str
    size_bytes: int
    selected_encoding: str | None
    offset_basis: str
    scan_status: str
    scanned_character_count: int
    scanned_unit_count: int
    candidate_count: int
    accepted_candidate_count: int
    review_candidate_count: int
    rejected_candidate_count: int
    nonassertive_candidate_count: int
    model_task_count: int
    finding_count: int
    claim_type_counts: dict[str, int]
    discourse_status_counts: dict[str, int]
    validation_status_counts: dict[str, int]
    recommended_action: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    policy: dict[str, object]
    candidates: tuple[SemanticCandidate, ...]
    findings: tuple[SemanticFinding, ...]
    model_tasks: tuple[ModelExtractionTask, ...]
    accepted_records: tuple[dict[str, object], ...]
    normalization: dict[str, object]
    project_acceptance_performed: bool
    may_accept_project: bool
    may_freeze: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def stable_id(prefix: str, *parts: object, length: int = 32) -> str:
    payload = "\0".join(str(part) for part in parts)
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:length]


def candidate_id(
    *,
    source_sha256: str,
    unit_id: str,
    claim_type: str,
    evidence_start: int,
    evidence_end: int,
    normalized_payload: Mapping[str, object],
) -> str:
    ordered = tuple((key, normalized_payload[key]) for key in sorted(normalized_payload))
    return stable_id(
        "sem_",
        SEMANTIC_CANDIDATE_SCHEMA_VERSION,
        source_sha256,
        unit_id,
        claim_type,
        evidence_start,
        evidence_end,
        ordered,
    )


def make_finding(
    *,
    source_id: str,
    source_sha256: str,
    rule_id: str,
    severity: str,
    confidence: str,
    action: str,
    unit_id: str | None,
    candidate_id_value: str | None,
    start: int,
    end: int,
    start_line: int,
    end_line: int,
    signals: Iterable[str],
) -> SemanticFinding:
    signal_tuple = tuple(signals)
    identifier = stable_id(
        "smf_",
        SEMANTIC_FINDING_SCHEMA_VERSION,
        source_sha256,
        rule_id,
        unit_id,
        candidate_id_value,
        start,
        end,
        signal_tuple,
    )
    return SemanticFinding(
        SEMANTIC_FINDING_SCHEMA_VERSION,
        identifier,
        rule_id,
        severity,
        confidence,
        action,
        source_id,
        unit_id,
        candidate_id_value,
        start,
        end,
        start_line,
        end_line,
        signal_tuple,
    )
