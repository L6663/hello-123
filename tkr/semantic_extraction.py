"""Evidence-bound six-predicate extraction and factual-status separation."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from os import PathLike
from pathlib import Path

from .anomaly_detection import inspect_source_anomalies
from .chunking import UnitSpan
from .claim_validation import ClaimCandidate, ClaimValidationResult, validate_claim
from .entity_normalization import EntityNormalizationError, normalize_entities
from .hashing import DEFAULT_BLOCK_SIZE, HashingError, sha256_file
from .semantic_model_tasks import make_model_task
from .semantic_models import (
    CLAIM_TYPES, DISCOURSE_STATUSES, FACTUAL_STATUSES, OFFSET_BASIS,
    SEMANTIC_CANDIDATE_SCHEMA_VERSION, SEMANTIC_EXTRACTOR_VERSION,
    SEMANTIC_REPORT_SCHEMA_VERSION, ModelExtractionTask, SemanticCandidate,
    SemanticExtractionError, SemanticExtractionReport, SemanticFinding,
    SemanticPolicy, candidate_id, make_finding,
)
from .semantic_rules import AMBIGUOUS_CUE_RE, proposals
from .semantic_text import classify_discourse, iter_clauses, iter_unit_texts, line_number
from .structure_detection import (
    StructureInspectionError, inspect_source_structure, validate_structure_report,
)
from .structure_models import UnitRecord


def _blocked_report(structure, policy: SemanticPolicy) -> SemanticExtractionReport:
    return SemanticExtractionReport(
        SEMANTIC_REPORT_SCHEMA_VERSION, SEMANTIC_EXTRACTOR_VERSION,
        structure.source_id, structure.source_sha256, structure.size_bytes,
        structure.selected_encoding, OFFSET_BASIS, "blocked", 0, 0, 0, 0, 0, 0,
        0, 0, 0, {}, {}, {}, "resolve_structure_blockers",
        tuple(dict.fromkeys((*structure.blockers, "STRUCTURE_NOT_READY_FOR_SEMANTIC_EXTRACTION"))),
        tuple(structure.warnings), policy.to_dict(), (), (), (), (), {}, False, False, False,
    )


def _validate(
    proposal: dict[str, object], discourse_status: str, source_text: str,
    source_id: str, unit: UnitRecord, start: int, end: int, evidence: str,
) -> tuple[ClaimCandidate, ClaimValidationResult | None, str, tuple[str, ...], bool]:
    candidate = ClaimCandidate(
        claim_type=str(proposal["claim_type"]), subject=str(proposal["subject"]),
        object=str(proposal["object"]), value=proposal["value"], unit=str(proposal["unit"]),
        polarity=bool(proposal["polarity"]), source_id=source_id, unit_id=unit.unit_id,
        evidence_start=start, evidence_end=end, evidence_text=evidence,
    )
    if discourse_status != "assertion":
        return candidate, None, "not_validated_nonassertive", ("NONASSERTIVE_DISCOURSE",), False
    result = validate_claim(
        candidate, source_text,
        unit_span=UnitSpan(unit.unit_id, unit.start_char, unit.end_char, unit.source_id),
        require_unit=True,
    )
    return candidate, result, result.status, result.reason_codes, (
        result.status == "accepted" and result.may_index and not result.may_freeze
    )


def _factual_status(discourse_status: str, polarity: bool) -> str:
    if discourse_status == "assertion":
        return "asserted_fact" if polarity else "negated_fact"
    return discourse_status


def _overlaps(start: int, end: int, spans) -> tuple[tuple[str, str], ...]:
    return tuple(
        (rule_id, category)
        for span_start, span_end, rule_id, category in spans
        if start < span_end and span_start < end
    )


def _normalization(accepted_records, source_text: str, units) -> dict[str, object]:
    if not accepted_records:
        return {}
    try:
        bundle = normalize_entities(
            accepted_records,
            source_text,
            [UnitSpan(item.unit_id, item.start_char, item.end_char, item.source_id) for item in units],
        )
    except EntityNormalizationError as exc:
        raise SemanticExtractionError(f"entity normalization failed: {exc}") from exc
    return {
        "report": bundle.report,
        "mentions": [item.to_dict() for item in bundle.mentions],
        "entities": [item.to_dict() for item in bundle.entities],
        "facts": [item.to_dict() for item in bundle.facts],
        "timeline": [item.to_dict() for item in bundle.timeline],
        "conflicts": [item.to_dict() for item in bundle.conflicts],
        "ambiguity_groups": [item.to_dict() for item in bundle.ambiguity_groups],
    }


def inspect_source_semantics(
    path: str | PathLike[str], *, policy: SemanticPolicy | None = None,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> SemanticExtractionReport:
    """Extract deterministic candidates from exact Stage 2 Unit body spans."""

    active = policy or SemanticPolicy()
    try:
        structure = inspect_source_structure(path, block_size=block_size)
        validate_structure_report(structure)
    except StructureInspectionError as exc:
        raise SemanticExtractionError(str(exc)) from exc
    if structure.scan_status != "completed" or structure.selected_encoding is None:
        return _blocked_report(structure, active)

    anomaly = inspect_source_anomalies(path, block_size=block_size)
    unsafe_spans = tuple(
        (item.start_char, item.end_char, item.rule_id, item.category)
        for item in anomaly.findings
        if item.category in {"contamination_candidate", "paratext_candidate"}
        or (item.category == "text_anomaly" and item.severity == "high")
    )
    path_value = Path(path)
    unit_rows = list(iter_unit_texts(path_value, structure))
    source_text = "".join(text for _, text in unit_rows)
    if len(source_text) != structure.scanned_character_count:
        raise SemanticExtractionError("semantic source reconstruction does not match structure length")

    candidates: list[SemanticCandidate] = []
    findings: list[SemanticFinding] = []
    tasks: list[ModelExtractionTask] = []
    accepted_records: list[dict[str, object]] = []
    warnings = list(structure.warnings)
    if unsafe_spans:
        warnings.append("UPSTREAM_ANOMALY_REVIEW_SPANS_PRESENT")
    candidate_limit = finding_limit = task_limit = False

    def add_finding(item: SemanticFinding) -> None:
        nonlocal finding_limit
        if len(findings) >= active.max_findings:
            finding_limit = True
        else:
            findings.append(item)

    for unit, unit_text in unit_rows:
        body_local = max(0, unit.body_start_char - unit.start_char)
        for local_start, local_end, clause in iter_clauses(unit_text, body_local):
            global_start, global_end = unit.start_char + local_start, unit.start_char + local_end
            start_line = line_number(unit, unit_text, local_start)
            end_line = line_number(unit, unit_text, local_end)
            if len(clause) > active.max_clause_characters:
                add_finding(make_finding(
                    source_id=structure.source_id, source_sha256=structure.source_sha256,
                    rule_id="CLAUSE_EXCEEDS_EXTRACTION_LIMIT", severity="medium", confidence="high",
                    action="review_clause_or_raise_policy_limit", unit_id=unit.unit_id,
                    candidate_id_value=None, start=global_start, end=global_end,
                    start_line=start_line, end_line=end_line, signals=(f"length={len(clause)}",),
                ))
                continue
            discourse, attributor, proposition_offset = classify_discourse(clause)
            if discourse not in DISCOURSE_STATUSES:
                raise SemanticExtractionError("unsupported discourse status")
            rows = list(proposals(clause[proposition_offset:]))
            if not rows and active.emit_model_tasks and AMBIGUOUS_CUE_RE.search(clause):
                if len(tasks) >= active.max_model_tasks:
                    task_limit = True
                else:
                    tasks.append(make_model_task(
                        source_id=structure.source_id, source_sha256=structure.source_sha256,
                        unit_id=unit.unit_id, evidence_start=global_start,
                        evidence_end=global_end, evidence_text=clause,
                    ))
            for proposal in rows:
                if len(candidates) >= active.max_candidates:
                    candidate_limit = True
                    continue
                candidate, validation, status, reasons, may_index = _validate(
                    proposal, discourse, source_text, structure.source_id, unit,
                    global_start, global_end, clause,
                )
                upstream = _overlaps(global_start, global_end, unsafe_spans)
                if unit.review_status != "accepted_candidate":
                    may_index = False
                    reasons = tuple(dict.fromkeys((*reasons, "UNIT_REQUIRES_STRUCTURE_REVIEW")))
                if upstream:
                    may_index = False
                    reasons = tuple(dict.fromkeys((*reasons, "EVIDENCE_OVERLAPS_UPSTREAM_ANOMALY")))
                factual = _factual_status(discourse, candidate.polarity)
                if factual not in FACTUAL_STATUSES:
                    raise SemanticExtractionError("unsupported factual status")
                normalized = {
                    "claim_type": candidate.claim_type, "subject": candidate.subject,
                    "object": candidate.object, "value": candidate.value, "unit": candidate.unit,
                    "polarity": candidate.polarity, "discourse_status": discourse,
                    "factual_status": factual, "attributor": attributor,
                }
                identifier = candidate_id(
                    source_sha256=structure.source_sha256, unit_id=unit.unit_id,
                    claim_type=candidate.claim_type, evidence_start=global_start,
                    evidence_end=global_end, normalized_payload=normalized,
                )
                trigger_start = global_start + proposition_offset + int(proposal["trigger_start"])
                trigger_end = global_start + proposition_offset + int(proposal["trigger_end"])
                requires_review = (
                    discourse != "assertion" or status != "accepted"
                    or unit.review_status != "accepted_candidate" or bool(upstream)
                )
                semantic = SemanticCandidate(
                    SEMANTIC_CANDIDATE_SCHEMA_VERSION, identifier, candidate.claim_type,
                    candidate.subject, candidate.object, candidate.value, candidate.unit,
                    candidate.polarity, discourse, factual, attributor, structure.source_id,
                    structure.source_sha256, unit.unit_id, str(proposal["rule"]),
                    "high" if discourse == "assertion" else "medium",
                    global_start, global_end, start_line, end_line,
                    sha256(clause.encode("utf-8")).hexdigest(), clause,
                    trigger_start, trigger_end, status,
                    None if validation is None else validation.result_id,
                    tuple(reasons), may_index, requires_review,
                )
                candidates.append(semantic)
                if unit.review_status != "accepted_candidate":
                    add_finding(make_finding(
                        source_id=structure.source_id, source_sha256=structure.source_sha256,
                        rule_id="CANDIDATE_IN_REVIEW_UNIT", severity="medium", confidence="high",
                        action="resolve_structure_review_before_indexing", unit_id=unit.unit_id,
                        candidate_id_value=identifier, start=global_start, end=global_end,
                        start_line=start_line, end_line=end_line,
                        signals=(f"unit_review_status={unit.review_status}",),
                    ))
                if upstream:
                    add_finding(make_finding(
                        source_id=structure.source_id, source_sha256=structure.source_sha256,
                        rule_id="EVIDENCE_OVERLAPS_UPSTREAM_ANOMALY", severity="high", confidence="high",
                        action="resolve_anomaly_before_indexing", unit_id=unit.unit_id,
                        candidate_id_value=identifier, start=global_start, end=global_end,
                        start_line=start_line, end_line=end_line,
                        signals=tuple(f"{rule}:{category}" for rule, category in upstream),
                    ))
                if validation is not None and may_index:
                    accepted_records.append({
                        "candidate_line": len(candidates), "candidate": candidate.to_dict(),
                        "validation": validation.to_dict(), "semantic_candidate_id": identifier,
                        "discourse_status": discourse,
                    })
                if discourse != "assertion":
                    add_finding(make_finding(
                        source_id=structure.source_id, source_sha256=structure.source_sha256,
                        rule_id="NONASSERTIVE_PROPOSITION_CANDIDATE", severity="medium", confidence="high",
                        action="retain_as_attributed_proposition_not_canonical_fact",
                        unit_id=unit.unit_id, candidate_id_value=identifier,
                        start=global_start, end=global_end, start_line=start_line, end_line=end_line,
                        signals=(f"discourse_status={discourse}", f"attributor={attributor}"),
                    ))
                elif status != "accepted":
                    add_finding(make_finding(
                        source_id=structure.source_id, source_sha256=structure.source_sha256,
                        rule_id="DETERMINISTIC_CANDIDATE_NOT_ACCEPTED", severity="medium", confidence="high",
                        action="review_candidate_and_validator_reasons", unit_id=unit.unit_id,
                        candidate_id_value=identifier, start=global_start, end=global_end,
                        start_line=start_line, end_line=end_line, signals=tuple(reasons),
                    ))

    normalization = _normalization(accepted_records, source_text, structure.units) if active.run_entity_normalization else {}
    try:
        final_sha256 = sha256_file(path_value, block_size=block_size)
    except HashingError as exc:
        raise SemanticExtractionError(str(exc)) from exc
    if final_sha256 != structure.source_sha256:
        raise SemanticExtractionError("source changed during semantic extraction")
    if candidate_limit:
        warnings.append("CANDIDATE_LIMIT_REACHED")
    if finding_limit:
        warnings.append("SEMANTIC_FINDING_LIMIT_REACHED")
    if task_limit:
        warnings.append("MODEL_TASK_LIMIT_REACHED")

    candidates.sort(key=lambda item: (item.evidence_start, item.trigger_start, item.claim_type, item.candidate_id))
    findings.sort(key=lambda item: (item.start_char, item.end_char, item.rule_id, item.finding_id))
    tasks.sort(key=lambda item: (item.evidence_start, item.evidence_end, item.task_id))
    accepted_records.sort(key=lambda item: str(item.get("semantic_candidate_id", "")))
    validation_counts = Counter(item.validation_status for item in candidates)
    action = (
        "review_incomplete_candidates" if candidate_limit else
        "review_nonassertive_or_rejected_candidates" if findings else
        "semantic_candidates_ready"
    )
    return SemanticExtractionReport(
        SEMANTIC_REPORT_SCHEMA_VERSION, SEMANTIC_EXTRACTOR_VERSION,
        structure.source_id, structure.source_sha256, structure.size_bytes,
        structure.selected_encoding, OFFSET_BASIS, "completed",
        structure.scanned_character_count, len(structure.units), len(candidates),
        sum(item.may_index for item in candidates),
        sum(item.validation_status in {"review", "not_validated_nonassertive"} for item in candidates),
        sum(item.validation_status == "rejected" for item in candidates),
        sum(item.discourse_status != "assertion" for item in candidates),
        len(tasks), len(findings),
        dict(sorted(Counter(item.claim_type for item in candidates).items())),
        dict(sorted(Counter(item.discourse_status for item in candidates).items())),
        dict(sorted(validation_counts.items())), action, (),
        tuple(dict.fromkeys(warnings)), active.to_dict(), tuple(candidates),
        tuple(findings), tuple(tasks), tuple(accepted_records), normalization,
        False, False, False,
    )


def validate_semantic_report(report: SemanticExtractionReport) -> None:
    if report.project_acceptance_performed or report.may_accept_project or report.may_freeze:
        raise SemanticExtractionError("Stage 3 cannot authorize project acceptance or freezing")
    if report.scan_status == "blocked":
        if report.candidates or report.accepted_records or report.model_tasks:
            raise SemanticExtractionError("blocked semantic report contains extraction artifacts")
        return
    if report.candidate_count != len(report.candidates):
        raise SemanticExtractionError("semantic candidate count mismatch")
    if report.accepted_candidate_count != sum(item.may_index for item in report.candidates):
        raise SemanticExtractionError("accepted semantic candidate count mismatch")
    if report.nonassertive_candidate_count != sum(item.discourse_status != "assertion" for item in report.candidates):
        raise SemanticExtractionError("nonassertive semantic candidate count mismatch")
    seen: set[str] = set()
    for item in report.candidates:
        if item.candidate_id in seen:
            raise SemanticExtractionError("duplicate semantic candidate ID")
        seen.add(item.candidate_id)
        if item.claim_type not in CLAIM_TYPES or item.discourse_status not in DISCOURSE_STATUSES or item.factual_status not in FACTUAL_STATUSES:
            raise SemanticExtractionError("semantic candidate contains unsupported enum value")
        expected = _factual_status(item.discourse_status, item.polarity)
        if item.factual_status != expected:
            raise SemanticExtractionError("semantic candidate factual status is inconsistent")
        if item.discourse_status in {"belief", "suspicion", "accusation"} and not item.attributor:
            raise SemanticExtractionError("attributed proposition lacks an attributor")
        if item.evidence_start < 0 or item.evidence_end <= item.evidence_start:
            raise SemanticExtractionError("semantic candidate evidence span is invalid")
        if sha256(item.evidence_text.encode("utf-8")).hexdigest() != item.evidence_sha256:
            raise SemanticExtractionError("semantic candidate evidence hash mismatch")
        if item.may_index and (
            item.discourse_status != "assertion" or item.validation_status != "accepted"
            or item.requires_review
        ):
            raise SemanticExtractionError("non-canonical candidate was marked indexable")


__all__ = [
    "ModelExtractionTask", "SemanticCandidate", "SemanticExtractionError",
    "SemanticExtractionReport", "SemanticFinding", "SemanticPolicy",
    "inspect_source_semantics", "validate_semantic_report",
]
