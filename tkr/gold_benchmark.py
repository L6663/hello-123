"""Immutable, non-vacuous Gold Benchmark gates for Phase 6 strict QA.

A caller chooses only a built-in profile.  Case minima, category coverage,
hard-negative coverage, metric floors, and safety ceilings cannot be supplied by
the dataset or CLI.  Reports bind the Gold bytes, logical cases, database,
index report, evaluator version, and policy, and are verified by full
recomputation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping, Sequence

from .gold_hard_negatives import validate_hard_negative_outcome
from .hybrid_retrieval import RetrievalError, parse_predicate_query
from .strict_qa import StrictQAError, StrictQAPacket, answer_strict, verify_strict_packet

GOLD_SCHEMA_VERSION = "tkr-gold-cases-v1"
BENCHMARK_SCHEMA_VERSION = "tkr-gold-benchmark-v1"
EVALUATOR_VERSION = "tkr-gold-evaluator-v1"
SUPPORTED_PREDICATES = ("alias", "defeats", "located_in", "permission", "count", "date")
EXPECTED_DECISIONS = (
    "answered",
    "refused_unsupported",
    "refused_insufficient_evidence",
    "refused_ambiguous",
)
REFUSAL_DECISIONS = frozenset(EXPECTED_DECISIONS[1:])
HARD_NEGATIVE_TAGS = frozenset(
    {
        "entity_only_no_predicate",
        "relation_direction",
        "numeric_prefix",
        "temporal_scope",
        "contested_fact",
        "unsupported_open_predicate",
        "lexical_distractor",
        "absence_not_negative",
    }
)
_ALLOWED_FIELDS = frozenset(
    {
        "gold_schema_version",
        "case_id",
        "question",
        "expected_decision",
        "expected_predicate",
        "expected_answer_claim",
        "expected_fact_ids",
        "expected_evidence_sha256",
        "source_id_filter",
        "tags",
    }
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BenchmarkError(ValueError):
    """Raised when a Gold set or benchmark artifact is unsafe."""


@dataclass(frozen=True, slots=True)
class BenchmarkPolicy:
    profile: str
    policy_id: str
    certifies_release: bool
    min_cases: int
    min_answered: int
    min_refusal_by_decision: Mapping[str, int]
    min_answered_per_predicate: int
    required_hard_negative_tags: frozenset[str]
    min_each_required_hard_negative: int
    metric_floors: Mapping[str, float]
    metric_ceilings: Mapping[str, float]
    count_ceilings: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "policy_id": self.policy_id,
            "certifies_release": self.certifies_release,
            "min_cases": self.min_cases,
            "min_answered": self.min_answered,
            "min_refusal_by_decision": dict(sorted(self.min_refusal_by_decision.items())),
            "min_answered_per_predicate": self.min_answered_per_predicate,
            "required_hard_negative_tags": sorted(self.required_hard_negative_tags),
            "min_each_required_hard_negative": self.min_each_required_hard_negative,
            "metric_floors": dict(sorted(self.metric_floors.items())),
            "metric_ceilings": dict(sorted(self.metric_ceilings.items())),
            "count_ceilings": dict(sorted(self.count_ceilings.items())),
        }


_COMMON_FLOORS = {
    "answer_claim_accuracy": 1.0,
    "citation_entailment_rate": 1.0,
    "answer_precision": 1.0,
    "refusal_precision": 1.0,
}
_COMMON_CEILINGS = {
    "overanswer_count": 0,
    "wrong_answer_count": 0,
    "citation_mismatch_count": 0,
    "integrity_error_count": 0,
    "evaluator_error_count": 0,
    "hard_negative_validation_error_count": 0,
}
POLICIES: Mapping[str, BenchmarkPolicy] = {
    "smoke": BenchmarkPolicy(
        profile="smoke",
        policy_id="tkr-gold-policy-smoke-v1",
        certifies_release=False,
        min_cases=12,
        min_answered=6,
        min_refusal_by_decision={
            "refused_unsupported": 2,
            "refused_insufficient_evidence": 2,
            "refused_ambiguous": 2,
        },
        min_answered_per_predicate=1,
        required_hard_negative_tags=frozenset(
            {
                "relation_direction",
                "temporal_scope",
                "unsupported_open_predicate",
                "lexical_distractor",
                "absence_not_negative",
            }
        ),
        min_each_required_hard_negative=1,
        metric_floors={
            **_COMMON_FLOORS,
            "exact_case_accuracy": 1.0,
            "decision_accuracy": 1.0,
            "answer_recall": 1.0,
            "refusal_recall": 1.0,
        },
        metric_ceilings={"hallucination_rate": 0.0},
        count_ceilings=_COMMON_CEILINGS,
    ),
    "release": BenchmarkPolicy(
        profile="release",
        policy_id="tkr-gold-policy-release-v1",
        certifies_release=True,
        min_cases=100,
        min_answered=42,
        min_refusal_by_decision={
            "refused_unsupported": 15,
            "refused_insufficient_evidence": 15,
            "refused_ambiguous": 15,
        },
        min_answered_per_predicate=7,
        required_hard_negative_tags=HARD_NEGATIVE_TAGS,
        min_each_required_hard_negative=3,
        metric_floors={
            **_COMMON_FLOORS,
            "exact_case_accuracy": 0.98,
            "decision_accuracy": 0.99,
            "answer_recall": 0.98,
            "refusal_recall": 0.98,
        },
        metric_ceilings={"hallucination_rate": 0.0},
        count_ceilings=_COMMON_CEILINGS,
    ),
}


def _freeze_policy(policy: BenchmarkPolicy) -> BenchmarkPolicy:
    """Return a recursively immutable copy of a built-in policy."""

    return BenchmarkPolicy(
        profile=policy.profile,
        policy_id=policy.policy_id,
        certifies_release=policy.certifies_release,
        min_cases=policy.min_cases,
        min_answered=policy.min_answered,
        min_refusal_by_decision=MappingProxyType(dict(policy.min_refusal_by_decision)),
        min_answered_per_predicate=policy.min_answered_per_predicate,
        required_hard_negative_tags=frozenset(policy.required_hard_negative_tags),
        min_each_required_hard_negative=policy.min_each_required_hard_negative,
        metric_floors=MappingProxyType(dict(policy.metric_floors)),
        metric_ceilings=MappingProxyType(dict(policy.metric_ceilings)),
        count_ceilings=MappingProxyType(dict(policy.count_ceilings)),
    )


POLICIES = MappingProxyType(
    {name: _freeze_policy(policy) for name, policy in POLICIES.items()}
)


@dataclass(frozen=True, slots=True)
class GoldCase:
    case_id: str
    question: str
    expected_decision: str
    expected_predicate: str
    expected_answer_claim: Mapping[str, object] | None
    expected_fact_ids: tuple[str, ...]
    expected_evidence_sha256: tuple[str, ...]
    source_id_filter: str | None
    tags: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "gold_schema_version": GOLD_SCHEMA_VERSION,
            "case_id": self.case_id,
            "question": self.question,
            "expected_decision": self.expected_decision,
            "expected_predicate": self.expected_predicate,
            "expected_answer_claim": dict(self.expected_answer_claim) if self.expected_answer_claim else None,
            "expected_fact_ids": list(self.expected_fact_ids),
            "expected_evidence_sha256": list(self.expected_evidence_sha256),
            "source_id_filter": self.source_id_filter,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    case_id: str
    expected_decision: str
    actual_decision: str
    expected_predicate: str
    actual_predicate: str
    decision_correct: bool
    answer_claim_correct: bool
    citations_correct: bool
    packet_integrity_verified: bool
    overanswer: bool
    wrong_answer: bool
    hallucination: bool
    exact_pass: bool
    reason_codes: tuple[str, ...]
    packet_id: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    benchmark_schema_version: str
    evaluator_version: str
    gold_schema_version: str
    policy_profile: str
    policy: Mapping[str, object]
    database_sha256: str
    index_report_sha256: str
    gold_file_sha256: str
    gold_logical_sha256: str
    case_count: int
    coverage: Mapping[str, object]
    metrics: Mapping[str, float | int]
    blockers: tuple[str, ...]
    cases: tuple[CaseEvaluation, ...]
    passed: bool
    may_certify_release: bool
    may_freeze: bool
    report_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_schema_version": self.benchmark_schema_version,
            "evaluator_version": self.evaluator_version,
            "gold_schema_version": self.gold_schema_version,
            "policy_profile": self.policy_profile,
            "policy": dict(self.policy),
            "database_sha256": self.database_sha256,
            "index_report_sha256": self.index_report_sha256,
            "gold_file_sha256": self.gold_file_sha256,
            "gold_logical_sha256": self.gold_logical_sha256,
            "case_count": self.case_count,
            "coverage": dict(self.coverage),
            "metrics": dict(self.metrics),
            "blockers": list(self.blockers),
            "cases": [item.to_dict() for item in self.cases],
            "passed": self.passed,
            "may_certify_release": self.may_certify_release,
            "may_freeze": self.may_freeze,
            "report_id": self.report_id,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkVerification:
    status: str
    accepted: bool
    reason_codes: tuple[str, ...]
    supplied_report_id: str
    expected_report_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "accepted": self.accepted,
            "reason_codes": list(self.reason_codes),
            "supplied_report_id": self.supplied_report_id,
            "expected_report_id": self.expected_report_id,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{label} must be a non-empty string")
    return value.strip()


def _strings(value: object, label: str, *, required: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BenchmarkError(f"{label} must be a JSON array")
    result: list[str] = []
    for item in value:
        text = _text(item, label)
        if text in result:
            raise BenchmarkError(f"{label} contains duplicate value: {text}")
        result.append(text)
    if required and not result:
        raise BenchmarkError(f"{label} must not be empty")
    return tuple(result)


def _validate_hard_negative_tags(
    case_id: str,
    tags: Sequence[str],
    *,
    expected_decision: str,
    expected_predicate: str,
    parsed_temporal_scope: str,
) -> None:
    """Reject category labels that contradict the case's observable structure."""

    tag_set = set(tags)
    unsupported_tags = {"unsupported_open_predicate", "entity_only_no_predicate"}
    if tag_set & unsupported_tags:
        if expected_decision != "refused_unsupported" or expected_predicate != "unsupported":
            raise BenchmarkError(f"Gold case {case_id} has a spoofed unsupported hard-negative tag")
    if "relation_direction" in tag_set:
        if expected_predicate not in {"alias", "defeats", "located_in"} or expected_decision not in REFUSAL_DECISIONS:
            raise BenchmarkError(f"Gold case {case_id} has a spoofed relation-direction tag")
    if "numeric_prefix" in tag_set:
        if expected_predicate != "count" or expected_decision == "refused_unsupported":
            raise BenchmarkError(f"Gold case {case_id} has a spoofed numeric-prefix tag")
    if "temporal_scope" in tag_set:
        if expected_decision != "refused_ambiguous" or parsed_temporal_scope != "any":
            raise BenchmarkError(f"Gold case {case_id} has a spoofed temporal-scope tag")
    if "contested_fact" in tag_set and expected_decision != "refused_ambiguous":
        raise BenchmarkError(f"Gold case {case_id} has a spoofed contested-fact tag")
    if "lexical_distractor" in tag_set and expected_decision != "refused_insufficient_evidence":
        raise BenchmarkError(f"Gold case {case_id} has a spoofed lexical-distractor tag")
    if "absence_not_negative" in tag_set:
        if expected_predicate != "permission" or expected_decision != "refused_insufficient_evidence":
            raise BenchmarkError(f"Gold case {case_id} has a spoofed absence-not-negative tag")


def _parse_case(row: Mapping[str, object], line_number: int) -> GoldCase:
    unknown = set(row) - _ALLOWED_FIELDS
    if unknown:
        raise BenchmarkError(
            f"Gold line {line_number} contains unsupported fields: {', '.join(sorted(unknown))}"
        )
    if row.get("gold_schema_version") != GOLD_SCHEMA_VERSION:
        raise BenchmarkError(f"Gold line {line_number} schema version mismatch")
    case_id = _text(row.get("case_id"), "case_id")
    question = _text(row.get("question"), "question")
    expected_decision = _text(row.get("expected_decision"), "expected_decision")
    if expected_decision not in EXPECTED_DECISIONS:
        raise BenchmarkError(f"Gold case {case_id} has invalid expected_decision")
    expected_predicate = _text(row.get("expected_predicate"), "expected_predicate")
    parsed = parse_predicate_query(question)
    if parsed.predicate != expected_predicate:
        raise BenchmarkError(
            f"Gold case {case_id} predicate label does not match the current query parser"
        )
    source_filter = row.get("source_id_filter")
    if source_filter is not None:
        source_filter = _text(source_filter, "source_id_filter")
    tags = _strings(row.get("tags"), "tags", required=True)
    fact_ids = _strings(row.get("expected_fact_ids", []), "expected_fact_ids", required=False)
    evidence_hashes = _strings(
        row.get("expected_evidence_sha256", []), "expected_evidence_sha256", required=False
    )
    if any(not _HEX64.fullmatch(value) for value in evidence_hashes):
        raise BenchmarkError(f"Gold case {case_id} has an invalid evidence SHA-256")
    answer_claim = row.get("expected_answer_claim")

    if expected_decision == "answered":
        if expected_predicate not in SUPPORTED_PREDICATES:
            raise BenchmarkError(f"answered Gold case {case_id} requires a supported predicate")
        if not isinstance(answer_claim, dict) or not answer_claim:
            raise BenchmarkError(f"answered Gold case {case_id} requires expected_answer_claim")
        if answer_claim.get("predicate") != expected_predicate:
            raise BenchmarkError(f"Gold case {case_id} answer Claim predicate mismatch")
        if not fact_ids or not evidence_hashes:
            raise BenchmarkError(
                f"answered Gold case {case_id} requires non-empty Fact and evidence expectations"
            )
    else:
        if answer_claim is not None or fact_ids or evidence_hashes:
            raise BenchmarkError(f"refusal Gold case {case_id} must not contain answer expectations")
        if expected_decision == "refused_unsupported" and parsed.supported:
            raise BenchmarkError(f"unsupported Gold case {case_id} parses as a supported predicate")
        if expected_decision != "refused_unsupported" and not parsed.supported:
            raise BenchmarkError(f"typed refusal Gold case {case_id} parses as unsupported")

    _validate_hard_negative_tags(
        case_id,
        tags,
        expected_decision=expected_decision,
        expected_predicate=expected_predicate,
        parsed_temporal_scope=parsed.temporal_scope,
    )

    return GoldCase(
        case_id=case_id,
        question=question,
        expected_decision=expected_decision,
        expected_predicate=expected_predicate,
        expected_answer_claim=dict(answer_claim) if isinstance(answer_claim, dict) else None,
        expected_fact_ids=fact_ids,
        expected_evidence_sha256=evidence_hashes,
        source_id_filter=source_filter,
        tags=tags,
    )


def load_gold_cases(path: str | Path) -> tuple[GoldCase, ...]:
    cases: list[GoldCase] = []
    seen: set[str] = set()
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise BenchmarkError(f"blank Gold record at line {line_number}")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BenchmarkError(f"invalid Gold JSON at line {line_number}: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise BenchmarkError(f"Gold record at line {line_number} must be an object")
            case = _parse_case(row, line_number)
            if case.case_id in seen:
                raise BenchmarkError(f"duplicate Gold case_id: {case.case_id}")
            seen.add(case.case_id)
            cases.append(case)
    if not cases:
        raise BenchmarkError("Gold dataset is empty")
    return tuple(cases)


def _coverage(cases: Sequence[GoldCase]) -> dict[str, object]:
    decisions = Counter(case.expected_decision for case in cases)
    predicates = Counter(
        case.expected_predicate for case in cases if case.expected_decision == "answered"
    )
    tags = Counter(tag for case in cases for tag in case.tags)
    return {
        "decision_counts": {key: decisions.get(key, 0) for key in EXPECTED_DECISIONS},
        "answered_predicate_counts": {
            key: predicates.get(key, 0) for key in SUPPORTED_PREDICATES
        },
        "hard_negative_tag_counts": {
            key: tags.get(key, 0) for key in sorted(HARD_NEGATIVE_TAGS)
        },
    }


def _coverage_blockers(cases: Sequence[GoldCase], policy: BenchmarkPolicy) -> list[str]:
    coverage = _coverage(cases)
    decisions = coverage["decision_counts"]
    predicates = coverage["answered_predicate_counts"]
    tags = coverage["hard_negative_tag_counts"]
    blockers: list[str] = []
    if len(cases) < policy.min_cases:
        blockers.append("GOLD_CASE_COUNT_BELOW_POLICY_MINIMUM")
    if int(decisions["answered"]) < policy.min_answered:
        blockers.append("GOLD_ANSWERED_COUNT_BELOW_POLICY_MINIMUM")
    for decision, minimum in policy.min_refusal_by_decision.items():
        if int(decisions[decision]) < minimum:
            blockers.append(f"GOLD_{decision.upper()}_COUNT_BELOW_POLICY_MINIMUM")
    for predicate in SUPPORTED_PREDICATES:
        if int(predicates[predicate]) < policy.min_answered_per_predicate:
            blockers.append(f"GOLD_{predicate.upper()}_ANSWERED_COVERAGE_BELOW_POLICY_MINIMUM")
    for tag in sorted(policy.required_hard_negative_tags):
        if int(tags[tag]) < policy.min_each_required_hard_negative:
            blockers.append(f"GOLD_HARD_NEGATIVE_{tag.upper()}_BELOW_POLICY_MINIMUM")
    return blockers


def _case_result(
    database: Path,
    case: GoldCase,
    *,
    index_report: Path,
) -> CaseEvaluation:
    parsed = parse_predicate_query(case.question)
    try:
        packet = answer_strict(
            database,
            case.question,
            source_id=case.source_id_filter,
            retrieval_limit=100,
            max_citations=20,
            report_path=index_report,
        )
        verification = verify_strict_packet(database, packet.to_dict(), report_path=index_report)
        hard_negative_failures = validate_hard_negative_outcome(
            database,
            parsed,
            packet,
            case.tags,
            source_id=case.source_id_filter,
        )
    except (OSError, UnicodeError, RetrievalError, StrictQAError) as exc:
        return CaseEvaluation(
            case.case_id,
            case.expected_decision,
            "evaluator_error",
            case.expected_predicate,
            parsed.predicate,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            ("BENCHMARK_EVALUATOR_ERROR", type(exc).__name__),
            "",
        )

    reasons: list[str] = []
    decision_correct = packet.decision == case.expected_decision
    if not decision_correct:
        reasons.append("DECISION_MISMATCH")
    integrity = verification.accepted
    if not integrity:
        reasons.append("STRICT_PACKET_RECOMPUTATION_FAILED")
    reasons.extend(hard_negative_failures)

    if case.expected_decision == "answered":
        actual_claim = packet.answer_claim.to_dict() if packet.answer_claim else None
        claim_correct = _canonical_json(actual_claim) == _canonical_json(case.expected_answer_claim)
        actual_fact_ids = tuple(sorted(citation.fact_id for citation in packet.citations))
        actual_hashes = tuple(sorted(citation.evidence_sha256 for citation in packet.citations))
        citations_correct = (
            packet.citation_entailment == "entailed_structured"
            and bool(packet.citations)
            and actual_fact_ids == tuple(sorted(case.expected_fact_ids))
            and actual_hashes == tuple(sorted(case.expected_evidence_sha256))
        )
    else:
        claim_correct = packet.answer_claim is None
        citations_correct = not packet.citations and packet.citation_entailment == "not_applicable"

    if not claim_correct:
        reasons.append("ANSWER_CLAIM_MISMATCH")
    if not citations_correct:
        reasons.append("CITATION_EXPECTATION_MISMATCH")
    overanswer = case.expected_decision != "answered" and packet.decision == "answered"
    wrong_answer = case.expected_decision == "answered" and packet.decision == "answered" and (
        not claim_correct or not citations_correct
    )
    hallucination = overanswer or wrong_answer
    if overanswer:
        reasons.append("OVERANSWERED_GOLD_REFUSAL")
    if wrong_answer:
        reasons.append("ANSWERED_WITH_WRONG_CLAIM_OR_CITATION")
    predicate_correct = parsed.predicate == case.expected_predicate
    if not predicate_correct:
        reasons.append("PREDICATE_MISMATCH")
    exact = (
        decision_correct
        and claim_correct
        and citations_correct
        and integrity
        and predicate_correct
        and not hard_negative_failures
    )
    if exact:
        reasons.append("GOLD_CASE_EXACT_MATCH")

    return CaseEvaluation(
        case_id=case.case_id,
        expected_decision=case.expected_decision,
        actual_decision=packet.decision,
        expected_predicate=case.expected_predicate,
        actual_predicate=parsed.predicate,
        decision_correct=decision_correct,
        answer_claim_correct=claim_correct,
        citations_correct=citations_correct,
        packet_integrity_verified=integrity,
        overanswer=overanswer,
        wrong_answer=wrong_answer,
        hallucination=hallucination,
        exact_pass=exact,
        reason_codes=tuple(dict.fromkeys(reasons)),
        packet_id=packet.packet_id,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _metrics(cases: Sequence[GoldCase], results: Sequence[CaseEvaluation]) -> dict[str, float | int]:
    total = len(cases)
    expected_answered = sum(case.expected_decision == "answered" for case in cases)
    expected_refused = total - expected_answered
    actual_answered = sum(result.actual_decision == "answered" for result in results)
    actual_refused = sum(result.actual_decision in REFUSAL_DECISIONS for result in results)
    correct_answered = sum(
        result.expected_decision == "answered" and result.exact_pass for result in results
    )
    correct_refused = sum(
        result.expected_decision in REFUSAL_DECISIONS and result.exact_pass for result in results
    )
    answer_results = [result for result in results if result.expected_decision == "answered"]
    return {
        "exact_case_accuracy": _ratio(sum(result.exact_pass for result in results), total),
        "decision_accuracy": _ratio(sum(result.decision_correct for result in results), total),
        "answer_claim_accuracy": _ratio(
            sum(result.answer_claim_correct for result in answer_results), expected_answered
        ),
        "citation_entailment_rate": _ratio(
            sum(result.citations_correct and result.packet_integrity_verified for result in answer_results),
            expected_answered,
        ),
        "answer_precision": _ratio(correct_answered, actual_answered),
        "answer_recall": _ratio(correct_answered, expected_answered),
        "refusal_precision": _ratio(correct_refused, actual_refused),
        "refusal_recall": _ratio(correct_refused, expected_refused),
        "hallucination_rate": _ratio(sum(result.hallucination for result in results), total),
        "overanswer_count": sum(result.overanswer for result in results),
        "wrong_answer_count": sum(result.wrong_answer for result in results),
        "citation_mismatch_count": sum(
            result.expected_decision == "answered" and not result.citations_correct
            for result in results
        ),
        "integrity_error_count": sum(not result.packet_integrity_verified for result in results),
        "evaluator_error_count": sum(result.actual_decision == "evaluator_error" for result in results),
        "hard_negative_validation_error_count": sum(
            any(code.startswith("HARD_NEGATIVE_EVIDENCE_NOT_ESTABLISHED:") for code in result.reason_codes)
            for result in results
        ),
    }


def _metric_blockers(metrics: Mapping[str, float | int], policy: BenchmarkPolicy) -> list[str]:
    blockers: list[str] = []
    for metric, floor in policy.metric_floors.items():
        if float(metrics[metric]) < floor:
            blockers.append(f"METRIC_{metric.upper()}_BELOW_POLICY_FLOOR")
    for metric, ceiling in policy.metric_ceilings.items():
        if float(metrics[metric]) > ceiling:
            blockers.append(f"METRIC_{metric.upper()}_ABOVE_POLICY_CEILING")
    for metric, ceiling in policy.count_ceilings.items():
        if int(metrics[metric]) > ceiling:
            blockers.append(f"METRIC_{metric.upper()}_ABOVE_POLICY_CEILING")
    return blockers


def _report_id(payload: Mapping[str, object]) -> str:
    return "bench_" + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:24]


def evaluate_gold_benchmark(
    database_path: str | Path,
    gold_path: str | Path,
    *,
    profile: str = "smoke",
    report_path: str | Path | None = None,
) -> BenchmarkReport:
    if profile not in POLICIES:
        raise BenchmarkError(f"unknown immutable benchmark profile: {profile}")
    policy = POLICIES[profile]
    database = Path(database_path)
    gold_file = Path(gold_path)
    index_report = Path(report_path) if report_path is not None else database.with_suffix(".report.json")
    for path, label in ((database, "database"), (gold_file, "Gold dataset"), (index_report, "index report")):
        if not path.is_file():
            raise BenchmarkError(f"benchmark {label} is missing")

    cases = load_gold_cases(gold_file)
    coverage = _coverage(cases)
    results = tuple(_case_result(database, case, index_report=index_report) for case in cases)
    metrics = _metrics(cases, results)
    blockers = list(dict.fromkeys(_coverage_blockers(cases, policy) + _metric_blockers(metrics, policy)))
    passed = not blockers
    logical_cases = [case.to_dict() for case in cases]
    base: dict[str, object] = {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "gold_schema_version": GOLD_SCHEMA_VERSION,
        "policy_profile": profile,
        "policy": policy.to_dict(),
        "database_sha256": _digest(database.read_bytes()),
        "index_report_sha256": _digest(index_report.read_bytes()),
        "gold_file_sha256": _digest(gold_file.read_bytes()),
        "gold_logical_sha256": _digest(_canonical_json(logical_cases).encode("utf-8")),
        "case_count": len(cases),
        "coverage": coverage,
        "metrics": metrics,
        "blockers": blockers,
        "cases": [result.to_dict() for result in results],
        "passed": passed,
        "may_certify_release": passed and policy.certifies_release,
        "may_freeze": False,
    }
    return BenchmarkReport(
        benchmark_schema_version=BENCHMARK_SCHEMA_VERSION,
        evaluator_version=EVALUATOR_VERSION,
        gold_schema_version=GOLD_SCHEMA_VERSION,
        policy_profile=profile,
        policy=policy.to_dict(),
        database_sha256=str(base["database_sha256"]),
        index_report_sha256=str(base["index_report_sha256"]),
        gold_file_sha256=str(base["gold_file_sha256"]),
        gold_logical_sha256=str(base["gold_logical_sha256"]),
        case_count=len(cases),
        coverage=coverage,
        metrics=metrics,
        blockers=tuple(blockers),
        cases=results,
        passed=passed,
        may_certify_release=passed and policy.certifies_release,
        may_freeze=False,
        report_id=_report_id(base),
    )


def _load_report(value: Mapping[str, object] | str | Path) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        payload = json.loads(Path(value).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"invalid benchmark report JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkError("benchmark report must be a JSON object")
    return payload


def verify_benchmark_report(
    database_path: str | Path,
    gold_path: str | Path,
    report: Mapping[str, object] | str | Path,
    *,
    index_report_path: str | Path | None = None,
    expected_profile: str | None = None,
) -> BenchmarkVerification:
    try:
        supplied = _load_report(report)
    except (OSError, UnicodeError, BenchmarkError) as exc:
        return BenchmarkVerification(
            "rejected", False, ("MALFORMED_BENCHMARK_REPORT", type(exc).__name__), "", ""
        )
    supplied_id = supplied.get("report_id") if isinstance(supplied.get("report_id"), str) else ""
    profile = supplied.get("policy_profile")
    if not isinstance(profile, str) or profile not in POLICIES:
        return BenchmarkVerification(
            "rejected", False, ("BENCHMARK_POLICY_PROFILE_INVALID",), supplied_id, ""
        )
    if expected_profile is not None:
        if expected_profile not in POLICIES:
            return BenchmarkVerification(
                "rejected", False, ("BENCHMARK_REQUIRED_PROFILE_INVALID",), supplied_id, ""
            )
        if profile != expected_profile:
            return BenchmarkVerification(
                "rejected", False, ("BENCHMARK_REQUIRED_PROFILE_MISMATCH",), supplied_id, ""
            )
    try:
        expected = evaluate_gold_benchmark(
            database_path,
            gold_path,
            profile=profile,
            report_path=index_report_path,
        )
    except (OSError, UnicodeError, RetrievalError, StrictQAError, BenchmarkError):
        return BenchmarkVerification(
            "rejected", False, ("BENCHMARK_RECOMPUTATION_ERROR",), supplied_id, ""
        )
    expected_payload = expected.to_dict()
    reasons: list[str] = []
    if set(supplied) != set(expected_payload):
        if set(expected_payload) - set(supplied):
            reasons.append("BENCHMARK_REPORT_FIELDS_MISSING")
        if set(supplied) - set(expected_payload):
            reasons.append("BENCHMARK_REPORT_FIELDS_UNEXPECTED")
    checks = {
        "benchmark_schema_version": "BENCHMARK_SCHEMA_VERSION_MISMATCH",
        "evaluator_version": "BENCHMARK_EVALUATOR_VERSION_MISMATCH",
        "gold_schema_version": "GOLD_SCHEMA_VERSION_MISMATCH",
        "policy_profile": "BENCHMARK_POLICY_PROFILE_MISMATCH",
        "policy": "IMMUTABLE_POLICY_MISMATCH",
        "database_sha256": "BENCHMARK_DATABASE_HASH_MISMATCH",
        "index_report_sha256": "BENCHMARK_INDEX_REPORT_HASH_MISMATCH",
        "gold_file_sha256": "GOLD_FILE_HASH_MISMATCH",
        "gold_logical_sha256": "GOLD_LOGICAL_HASH_MISMATCH",
        "case_count": "BENCHMARK_CASE_COUNT_MISMATCH",
        "coverage": "BENCHMARK_COVERAGE_MISMATCH",
        "metrics": "BENCHMARK_METRICS_MISMATCH",
        "blockers": "BENCHMARK_BLOCKERS_MISMATCH",
        "cases": "BENCHMARK_CASE_RESULTS_MISMATCH",
        "passed": "BENCHMARK_PASS_STATUS_MISMATCH",
        "may_certify_release": "BENCHMARK_CERTIFICATION_AUTHORITY_MISMATCH",
        "may_freeze": "BENCHMARK_FREEZE_AUTHORITY_MISMATCH",
        "report_id": "BENCHMARK_REPORT_ID_MISMATCH",
    }
    for field, code in checks.items():
        if supplied.get(field) != expected_payload.get(field):
            reasons.append(code)
    if _canonical_json(supplied) != _canonical_json(expected_payload):
        reasons.append("BENCHMARK_REPORT_RECOMPUTATION_MISMATCH")
    unique = tuple(dict.fromkeys(reasons))
    if unique:
        return BenchmarkVerification("rejected", False, unique, supplied_id, expected.report_id)
    return BenchmarkVerification(
        "accepted",
        True,
        ("BENCHMARK_RECOMPUTED_EXACTLY", "IMMUTABLE_POLICY_CONFIRMED"),
        supplied_id,
        expected.report_id,
    )
