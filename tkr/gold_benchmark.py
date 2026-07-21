"""Immutable Gold Benchmark evaluation for strict typed QA.

Phase 7 evaluates Phase 6 packets against a non-vacuous JSONL Gold set.  The
policy is selected from built-in profiles; callers cannot lower metric floors,
minimum case counts, predicate coverage, refusal coverage, or hard-negative
requirements.  Every report is bound to the Gold bytes, SQLite database, index
report, evaluator version, and policy identifier, and can be recomputed exactly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

from .hybrid_retrieval import RetrievalError
from .strict_qa import StrictQAError, StrictQAPacket, answer_strict, verify_strict_packet

BENCHMARK_SCHEMA_VERSION = "tkr-gold-benchmark-v1"
EVALUATOR_VERSION = "tkr-gold-evaluator-v1"
GOLD_SCHEMA_VERSION = "tkr-gold-cases-v1"

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
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_CASE_FIELDS = frozenset(
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


class BenchmarkError(ValueError):
    """Raised when a Gold set, report, or evaluation request is unsafe."""


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
    min_exact_case_accuracy: float
    min_decision_accuracy: float
    min_answer_claim_accuracy: float
    min_citation_entailment_rate: float
    min_answer_precision: float
    min_answer_recall: float
    min_refusal_precision: float
    min_refusal_recall: float
    max_hallucination_rate: float
    max_overanswer_count: int
    max_wrong_answer_count: int
    max_citation_mismatch_count: int
    max_integrity_error_count: int

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["required_hard_negative_tags"] = sorted(self.required_hard_negative_tags)
        payload["min_refusal_by_decision"] = dict(sorted(self.min_refusal_by_decision.items()))
        return payload


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
        min_exact_case_accuracy=1.0,
        min_decision_accuracy=1.0,
        min_answer_claim_accuracy=1.0,
        min_citation_entailment_rate=1.0,
        min_answer_precision=1.0,
        min_answer_recall=1.0,
        min_refusal_precision=1.0,
        min_refusal_recall=1.0,
        max_hallucination_rate=0.0,
        max_overanswer_count=0,
        max_wrong_answer_count=0,
        max_citation_mismatch_count=0,
        max_integrity_error_count=0,
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
        min_exact_case_accuracy=0.98,
        min_decision_accuracy=0.99,
        min_answer_claim_accuracy=1.0,
        min_citation_entailment_rate=1.0,
        min_answer_precision=1.0,
        min_answer_recall=0.98,
        min_refusal_precision=1.0,
        min_refusal_recall=0.98,
        max_hallucination_rate=0.0,
        max_overanswer_count=0,
        max_wrong_answer_count=0,
        max_citation_mismatch_count=0,
        max_integrity_error_count=0,
    ),
}


@dataclass(frozen=True, slots=True)
class GoldCase:
    gold_schema_version: str
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
            "gold_schema_version": self.gold_schema_version,
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
class BenchmarkCaseResult:
    case_id: str
    expected_decision: str
    actual_decision: str
    expected_predicate: str
    actual_predicate: str
    decision_correct: bool
    answer_claim_correct: bool
    citations_correct: bool
    packet_integrity_verified: bool
    hallucination: bool
    overanswer: bool
    wrong_answer: bool
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
    cases: tuple[BenchmarkCaseResult, ...]
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


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _non_empty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{label} must be a non-empty string")
    return value.strip()


def _string_tuple(value: object, label: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BenchmarkError(f"{label} must be a JSON array")
    result: list[str] = []
    for item in value:
        text = _non_empty_text(item, label)
        if text in result:
            raise BenchmarkError(f"{label} contains a duplicate value: {text}")
        result.append(text)
    if not allow_empty and not result:
        raise BenchmarkError(f"{label} must not be empty")
    return tuple(result)


def _case_from_dict(row: Mapping[str, object], line_number: int) -> GoldCase:
    unknown = set(row) - _ALLOWED_CASE_FIELDS
    if unknown:
        raise BenchmarkError(
            f"Gold case line {line_number} contains unsupported fields: {', '.join(sorted(unknown))}"
        )
    schema = _non_empty_text(row.get("gold_schema_version"), "gold_schema_version")
    if schema != GOLD_SCHEMA_VERSION:
        raise BenchmarkError(f"Gold case line {line_number} schema version mismatch")
    case_id = _non_empty_text(row.get("case_id"), "case_id")
    question = _non_empty_text(row.get("question"), "question")
    decision = _non_empty_text(row.get("expected_decision"), "expected_decision")
    if decision not in EXPECTED_DECISIONS:
        raise BenchmarkError(f"Gold case {case_id} has unsupported expected_decision: {decision}")
    predicate = _non_empty_text(row.get("expected_predicate"), "expected_predicate")
    if predicate not in (*SUPPORTED_PREDICATES, "unsupported"):
        raise BenchmarkError(f"Gold case {case_id} has unsupported expected_predicate: {predicate}")
    source_id = row.get("source_id_filter")
    if source_id is not None:
        source_id = _non_empty_text(source_id, "source_id_filter")
    tags = _string_tuple(row.get("tags"), "tags", allow_empty=False)
    fact_ids = _string_tuple(row.get("expected_fact_ids", []), "expected_fact_ids", allow_empty=True)
    evidence_hashes = _string_tuple(
        row.get("expected_evidence_sha256", []), "expected_evidence_sha256", allow_empty=True
    )
    for digest in evidence_hashes:
        if not _HEX64_RE.fullmatch(digest):
            raise BenchmarkError(f"Gold case {case_id} contains an invalid evidence SHA-256")

    answer_claim = row.get("expected_answer_claim")
    if decision == "answered":
        if predicate not in SUPPORTED_PREDICATES:
            raise BenchmarkError(f"answered Gold case {case_id} requires a supported predicate")
        if not isinstance(answer_claim, dict) or not answer_claim:
            raise BenchmarkError(f"answered Gold case {case_id} requires expected_answer_claim")
        if not fact_ids:
            raise BenchmarkError(f"answered Gold case {case_id} requires expected_fact_ids")
        if not evidence_hashes:
            raise BenchmarkError(f"answered Gold case {case_id} requires expected_evidence_sha256")
        claim_predicate = answer_claim.get("predicate")
        if claim_predicate != predicate:
            raise BenchmarkError(f"Gold case {case_id} answer Claim predicate mismatch")
    else:
        if answer_claim is not None:
            raise BenchmarkError(f"refusal Gold case {case_id} must not provide expected_answer_claim")
        if fact_ids or evidence_hashes:
            raise BenchmarkError(f"refusal Gold case {case_id} must not provide citation expectations")
        if decision == "refused_unsupported" and predicate != "unsupported":
            raise BenchmarkError(f"unsupported Gold case {case_id} must use expected_predicate=unsupported")
        if decision != "refused_unsupported" and predicate not in SUPPORTED_PREDICATES:
            raise BenchmarkError(f"typed refusal Gold case {case_id} requires a supported predicate")

    return GoldCase(
        gold_schema_version=schema,
        case_id=case_id,
        question=question,
        expected_decision=decision,
        expected_predicate=predicate,
        expected_answer_claim=dict(answer_claim) if isinstance(answer_claim, dict) else None,
        expected_fact_ids=fact_ids,
        expected_evidence_sha256=evidence_hashes,
        source_id_filter=source_id,
        tags=tags,
    )


def load_gold_cases(path: str | Path) -> tuple[GoldCase, ...]:
    gold_path = Path(path)
    cases: list[GoldCase] = []
    seen: set[str] = set()
    with gold_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise BenchmarkError(f"blank Gold record at line {line_number}")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BenchmarkError(f"invalid Gold JSON at line {line_number}: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise BenchmarkError(f"Gold record at line {line_number} must be an object")
            case = _case_from_dict(row, line_number)
            if case.case_id in seen:
                raise BenchmarkError(f"duplicate Gold case_id: {case.case_id}")
            seen.add(case.case_id)
            cases.append(case)
    if not cases:
        raise BenchmarkError("Gold dataset is empty")
    return tuple(cases)


def _coverage(cases: Sequence[GoldCase]) -> dict[str, object]:
    decisions = Counter(item.expected_decision for item in cases)
    answered_predicates = Counter(
        item.expected_predicate for item in cases if item.expected_decision == "answered"
    )
    tags = Counter(tag for item in cases for tag in item.tags)
    return {
        "decision_counts": dict(sorted(decisions.items())),
        "answered_predicate_counts": {
            predicate: answered_predicates.get(predicate, 0) for predicate in SUPPORTED_PREDICATES
        },
        "hard_negative_tag_counts": {
            tag: tags.get(tag, 0) for tag in sorted(HARD_NEGATIVE_TAGS)
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
    if int(decisions.get("answered", 0)) < policy.min_answered:
        blockers.append("GOLD_ANSWERED_COUNT_BELOW_POLICY_MINIMUM")
    for decision, minimum in policy.min_refusal_by_decision.items():
        if int(decisions.get(decision, 0)) < minimum:
            blockers.append(f"GOLD_{decision.upper()}_COUNT_BELOW_POLICY_MINIMUM")
    for predicate in SUPPORTED_PREDICATES:
        if int(predicates.get(predicate, 0)) < policy.min_answered_per_predicate:
            blockers.append(f"GOLD_{predicate.upper()}_ANSWERED_COVERAGE_BELOW_POLICY_MINIMUM")
    for tag in sorted(policy.required_hard_negative_tags):
        if int(tags.get(tag, 0)) < policy.min_each_required_hard_negative:
            blockers.append(f"GOLD_HARD_NEGATIVE_{tag.upper()}_BELOW_POLICY_MINIMUM")
    return blockers


def _packet_actual_predicate(packet: StrictQAPacket) -> str:
    if packet.answer_claim is not None:
        return packet.answer_claim.predicate
    if "UNSUPPORTED_OPEN_PREDICATE" in packet.reason_codes:
        return "unsupported"
    return ""


def _evaluate_case(
    database_path: Path,
    case: GoldCase,
    *,
    report_path: Path | None,
) -> BenchmarkCaseResult:
    reasons: list[str] = []
    try:
        packet = answer_strict(
            database_path,
            case.question,
            source_id=case.source_id_filter,
            retrieval_limit=100,
            max_citations=20,
            report_path=report_path,
        )
        verification = verify_strict_packet(
            database_path,
            packet.to_dict(),
            report_path=report_path,
        )
    except (OSError, UnicodeError, RetrievalError, StrictQAError) as exc:
        return BenchmarkCaseResult(
            case_id=case.case_id,
            expected_decision=case.expected_decision,
            actual_decision="evaluator_error",
            expected_predicate=case.expected_predicate,
            actual_predicate="",
            decision_correct=False,
            answer_claim_correct=False,
            citations_correct=False,
            packet_integrity_verified=False,
            hallucination=False,
            overanswer=False,
            wrong_answer=False,
            exact_pass=False,
            reason_codes=("BENCHMARK_EVALUATOR_ERROR", type(exc).__name__),
            packet_id="",
        )

    decision_correct = packet.decision == case.expected_decision
    if not decision_correct:
        reasons.append("DECISION_MISMATCH")
    actual_predicate = _packet_actual_predicate(packet)
    packet_verified = verification.accepted
    if not packet_verified:
        reasons.append("STRICT_PACKET_RECOMPUTATION_FAILED")

    answer_claim_correct = True
    citations_correct = True
    if case.expected_decision == "answered":
        actual_claim = packet.answer_claim.to_dict() if packet.answer_claim is not None else None
        answer_claim_correct = _canonical_json(actual_claim) == _canonical_json(case.expected_answer_claim)
        if not answer_claim_correct:
            reasons.append("ANSWER_CLAIM_MISMATCH")
        actual_fact_ids = tuple(sorted(item.fact_id for item in packet.citations))
        expected_fact_ids = tuple(sorted(case.expected_fact_ids))
        actual_hashes = tuple(sorted(item.evidence_sha256 for item in packet.citations))
        expected_hashes = tuple(sorted(case.expected_evidence_sha256))
        citations_correct = (
            packet.citation_entailment == "entailed_structured"
            and actual_fact_ids == expected_fact_ids
            and actual_hashes == expected_hashes
            and bool(packet.citations)
        )
        if not citations_correct:
            reasons.append("CITATION_EXPECTATION_MISMATCH")
    else:
        answer_claim_correct = packet.answer_claim is None
        citations_correct = not packet.citations and packet.citation_entailment == "not_applicable"
        if not answer_claim_correct:
            reasons.append("REFUSAL_CONTAINS_ANSWER_CLAIM")
        if not citations_correct:
            reasons.append("REFUSAL_CONTAINS_CITATIONS")

    overanswer = case.expected_decision != "answered" and packet.decision == "answered"
    wrong_answer = case.expected_decision == "answered" and packet.decision == "answered" and (
        not answer_claim_correct or not citations_correct
    )
    hallucination = overanswer or wrong_answer
    if overanswer:
        reasons.append("OVERANSWERED_GOLD_REFUSAL")
    if wrong_answer:
        reasons.append("ANSWERED_WITH_WRONG_CLAIM_OR_CITATION")

    exact = (
        decision_correct
        and answer_claim_correct
        and citations_correct
        and packet_verified
        and actual_predicate == case.expected_predicate
    )
    if actual_predicate != case.expected_predicate:
        reasons.append("PREDICATE_MISMATCH")
    if exact:
        reasons.append("GOLD_CASE_EXACT_MATCH")

    return BenchmarkCaseResult(
        case_id=case.case_id,
        expected_decision=case.expected_decision,
        actual_decision=packet.decision,
        expected_predicate=case.expected_predicate,
        actual_predicate=actual_predicate,
        decision_correct=decision_correct,
        answer_claim_correct=answer_claim_correct,
        citations_correct=citations_correct,
        packet_integrity_verified=packet_verified,
        hallucination=hallucination,
        overanswer=overanswer,
        wrong_answer=wrong_answer,
        exact_pass=exact,
        reason_codes=tuple(dict.fromkeys(reasons)),
        packet_id=packet.packet_id,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _metrics(cases: Sequence[GoldCase], results: Sequence[BenchmarkCaseResult]) -> dict[str, float | int]:
    total = len(cases)
    expected_answered = sum(item.expected_decision == "answered" for item in cases)
    expected_refused = total - expected_answered
    actual_answered = sum(item.actual_decision == "answered" for item in results)
    actual_refused = sum(item.actual_decision in REFUSAL_DECISIONS for item in results)
    correct_answered = sum(
        item.expected_decision == "answered" and item.exact_pass for item in results
    )
    correct_refused = sum(
        item.expected_decision in REFUSAL_DECISIONS and item.exact_pass for item in results
    )
    answered_results = [item for item in results if item.expected_decision == "answered"]
    return {
        "exact_case_accuracy": _ratio(sum(item.exact_pass for item in results), total),
        "decision_accuracy": _ratio(sum(item.decision_correct for item in results), total),
        "answer_claim_accuracy": _ratio(
            sum(item.answer_claim_correct for item in answered_results), expected_answered
        ),
        "citation_entailment_rate": _ratio(
            sum(item.citations_correct and item.packet_integrity_verified for item in answered_results),
            expected_answered,
        ),
        "answer_precision": _ratio(correct_answered, actual_answered),
        "answer_recall": _ratio(correct_answered, expected_answered),
        "refusal_precision": _ratio(correct_refused, actual_refused),
        "refusal_recall": _ratio(correct_refused, expected_refused),
        "hallucination_rate": _ratio(sum(item.hallucination for item in results), total),
        "overanswer_count": sum(item.overanswer for item in results),
        "wrong_answer_count": sum(item.wrong_answer for item in results),
        "citation_mismatch_count": sum(
            item.expected_decision == "answered" and not item.citations_correct for item in results
        ),
        "integrity_error_count": sum(not item.packet_integrity_verified for item in results),
        "evaluator_error_count": sum(item.actual_decision == "evaluator_error" for item in results),
    }


def _metric_blockers(metrics: Mapping[str, float | int], policy: BenchmarkPolicy) -> list[str]:
    blockers: list[str] = []
    minimums = {
        "exact_case_accuracy": policy.min_exact_case_accuracy,
        "decision_accuracy": policy.min_decision_accuracy,
        "answer_claim_accuracy": policy.min_answer_claim_accuracy,
        "citation_entailment_rate": policy.min_citation_entailment_rate,
        "answer_precision": policy.min_answer_precision,
        "answer_recall": policy.min_answer_recall,
        "refusal_precision": policy.min_refusal_precision,
        "refusal_recall": policy.min_refusal_recall,
    }
    for name, minimum in minimums.items():
        if float(metrics[name]) < minimum:
            blockers.append(f"METRIC_{name.upper()}_BELOW_POLICY_FLOOR")
    if float(metrics["hallucination_rate"]) > policy.max_hallucination_rate:
        blockers.append("METRIC_HALLUCINATION_RATE_ABOVE_POLICY_CEILING")
    maximums = {
        "overanswer_count": policy.max_overanswer_count,
        "wrong_answer_count": policy.max_wrong_answer_count,
        "citation_mismatch_count": policy.max_citation_mismatch_count,
        "integrity_error_count": policy.max_integrity_error_count,
        "evaluator_error_count": policy.max_integrity_error_count,
    }
    for name, maximum in maximums.items():
        if int(metrics[name]) > maximum:
            blockers.append(f"METRIC_{name.upper()}_ABOVE_POLICY_CEILING")
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
    if not database.is_file():
        raise BenchmarkError("benchmark database is missing")
    if not index_report.is_file():
        raise BenchmarkError("benchmark index report is missing")
    if not gold_file.is_file():
        raise BenchmarkError("Gold dataset is missing")

    cases = load_gold_cases(gold_file)
    coverage = _coverage(cases)
    blockers = _coverage_blockers(cases, policy)
    results = tuple(
        _evaluate_case(database, case, report_path=index_report)
        for case in cases
    )
    metrics = _metrics(cases, results)
    blockers.extend(_metric_blockers(metrics, policy))
    blockers = list(dict.fromkeys(blockers))
    passed = not blockers

    logical_cases = [item.to_dict() for item in cases]
    base: dict[str, object] = {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "gold_schema_version": GOLD_SCHEMA_VERSION,
        "policy_profile": profile,
        "policy": policy.to_dict(),
        "database_sha256": _sha256_bytes(database.read_bytes()),
        "index_report_sha256": _sha256_bytes(index_report.read_bytes()),
        "gold_file_sha256": _sha256_bytes(gold_file.read_bytes()),
        "gold_logical_sha256": _sha256_bytes(_canonical_json(logical_cases).encode("utf-8")),
        "case_count": len(cases),
        "coverage": coverage,
        "metrics": metrics,
        "blockers": blockers,
        "cases": [item.to_dict() for item in results],
        "passed": passed,
        "may_certify_release": passed and policy.certifies_release,
        "may_freeze": False,
    }
    identifier = _report_id(base)
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
        report_id=identifier,
    )


def _load_report(report: Mapping[str, object] | str | Path) -> dict[str, object]:
    if isinstance(report, Mapping):
        return dict(report)
    path = Path(report)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
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
    field_codes = {
        "benchmark_schema_version": "BENCHMARK_SCHEMA_VERSION_MISMATCH",
        "evaluator_version": "BENCHMARK_EVALUATOR_VERSION_MISMATCH",
        "gold_schema_version": "GOLD_SCHEMA_VERSION_MISMATCH",
        "policy_profile": "BENCHMARK_POLICY_PROFILE_MISMATCH",
        "policy": "IMMUTABLE_POLICY_MISMATCH",
        "database_sha256": "BENCHMARK_DATABASE_HASH_MISMATCH",
        "index_report_sha256": "BENCHMARK_INDEX_REPORT_HASH_MISMATCH",
        "gold_file_sha256": "GOLD_FILE_HASH_MISMATCH",
        "gold_logical_sha256": "GOLD_LOGICAL_HASH_MISMATCH",
        "coverage": "BENCHMARK_COVERAGE_MISMATCH",
        "metrics": "BENCHMARK_METRICS_MISMATCH",
        "blockers": "BENCHMARK_BLOCKERS_MISMATCH",
        "cases": "BENCHMARK_CASE_RESULTS_MISMATCH",
        "passed": "BENCHMARK_PASS_STATUS_MISMATCH",
        "may_certify_release": "BENCHMARK_CERTIFICATION_AUTHORITY_MISMATCH",
        "may_freeze": "BENCHMARK_FREEZE_AUTHORITY_MISMATCH",
        "report_id": "BENCHMARK_REPORT_ID_MISMATCH",
    }
    for field, code in field_codes.items():
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
