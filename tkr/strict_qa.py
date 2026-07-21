"""Strict evidence-bound question answering for the closed typed predicate set.

Phase 6 never treats lexical similarity as proof and never generates open-ended
prose.  It consumes a verified Phase 5 ``QueryResult``, renders one deterministic
answer (or a deterministic refusal), attaches exact Fact citations, and can
recompute the complete packet to detect any later modification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Sequence
import unicodedata

from .hybrid_retrieval import (
    INDEX_SCHEMA_VERSION,
    QUERY_PARSER_VERSION,
    PredicateQuery,
    QueryResult,
    RetrievalError,
    RetrievalHit,
    query_hybrid_index,
)

QA_SCHEMA_VERSION = "tkr-strict-qa-v1"
CITATION_SCHEMA_VERSION = "tkr-fact-citation-v1"
REFUSAL_POLICY_VERSION = "tkr-refusal-policy-v1"

_DATE_LABELS = {
    "birth_date": "出生日期",
    "death_date": "去世日期",
    "start_date": "开始日期",
    "end_date": "结束日期",
    "event_date": "发生日期",
    "generic_date": "日期",
}


class StrictQAError(ValueError):
    """Raised when a strict QA request or packet is malformed."""


@dataclass(frozen=True, slots=True)
class EvidenceCitation:
    citation_id: str
    citation_schema_version: str
    fact_id: str
    source_id: str
    unit_id: str
    evidence_start: int
    evidence_end: int
    evidence_text: str
    evidence_sha256: str
    claim_type: str
    predicate_scope: str
    canonical_status: str
    fact_polarity: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnswerClaim:
    predicate: str
    requested_role: str
    subject: str
    object: str
    value: object
    unit: str
    predicate_scope: str
    fact_polarity: bool | None
    boolean_answer: bool | None
    temporal_scope: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StrictQAPacket:
    qa_schema_version: str
    refusal_policy_version: str
    query_parser_version: str
    index_schema_version: str
    index_logical_sha256: str
    database_sha256: str
    index_report_sha256: str
    question: str
    normalized_question: str
    source_id_filter: str | None
    retrieval_limit: int
    max_citations: int
    decision: str
    refusal_kind: str | None
    reason_codes: tuple[str, ...]
    answer_text: str
    answer_claim: AnswerClaim | None
    citations: tuple[EvidenceCitation, ...]
    citation_entailment: str
    lexical_evidence_count: int
    may_present: bool
    may_freeze: bool
    packet_id: str

    @property
    def answered(self) -> bool:
        return self.decision == "answered"

    def to_dict(self) -> dict[str, object]:
        return {
            "qa_schema_version": self.qa_schema_version,
            "refusal_policy_version": self.refusal_policy_version,
            "query_parser_version": self.query_parser_version,
            "index_schema_version": self.index_schema_version,
            "index_logical_sha256": self.index_logical_sha256,
            "database_sha256": self.database_sha256,
            "index_report_sha256": self.index_report_sha256,
            "question": self.question,
            "normalized_question": self.normalized_question,
            "source_id_filter": self.source_id_filter,
            "retrieval_limit": self.retrieval_limit,
            "max_citations": self.max_citations,
            "decision": self.decision,
            "answered": self.answered,
            "refusal_kind": self.refusal_kind,
            "reason_codes": list(self.reason_codes),
            "answer_text": self.answer_text,
            "answer_claim": self.answer_claim.to_dict() if self.answer_claim else None,
            "citations": [item.to_dict() for item in self.citations],
            "citation_entailment": self.citation_entailment,
            "lexical_evidence_count": self.lexical_evidence_count,
            "may_present": self.may_present,
            "may_freeze": self.may_freeze,
            "packet_id": self.packet_id,
        }


@dataclass(frozen=True, slots=True)
class PacketVerification:
    status: str
    accepted: bool
    reason_codes: tuple[str, ...]
    supplied_packet_id: str
    expected_packet_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "accepted": self.accepted,
            "reason_codes": list(self.reason_codes),
            "supplied_packet_id": self.supplied_packet_id,
            "expected_packet_id": self.expected_packet_id,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _validate_limits(retrieval_limit: int, max_citations: int) -> None:
    if isinstance(retrieval_limit, bool) or not isinstance(retrieval_limit, int):
        raise StrictQAError("retrieval_limit must be an integer")
    if not 1 <= retrieval_limit <= 100:
        raise StrictQAError("retrieval_limit must be between 1 and 100")
    if isinstance(max_citations, bool) or not isinstance(max_citations, int):
        raise StrictQAError("max_citations must be an integer")
    if not 1 <= max_citations <= 20:
        raise StrictQAError("max_citations must be between 1 and 20")


def _report_path(database_path: Path, report_path: str | Path | None) -> Path:
    return Path(report_path) if report_path is not None else database_path.with_suffix(".report.json")


def _permission_inverse_question(intent: PredicateQuery) -> str:
    if intent.predicate != "permission" or intent.requested_role != "boolean":
        raise StrictQAError("permission inverse requested for a non-permission query")
    verb = "禁止" if intent.polarity is True else "允许"
    return f"{intent.subject}{verb}{intent.object}吗？"


def _support_result(
    database_path: Path,
    primary: QueryResult,
    *,
    source_id: str | None,
    retrieval_limit: int,
    verify_database: bool,
    report_path: str | Path | None,
) -> tuple[QueryResult, bool]:
    """Return explicit support, including the opposite permission polarity.

    Absence is never treated as a negative answer.  For permission questions only,
    an explicit opposite-polarity Fact can support a deterministic ``no`` answer.
    """

    if primary.answerability != "not_answerable":
        return primary, False
    intent = primary.intent
    if intent.predicate != "permission" or intent.requested_role != "boolean":
        return primary, False
    inverse = query_hybrid_index(
        database_path,
        _permission_inverse_question(intent),
        source_id=source_id,
        limit=retrieval_limit,
        verify_database=verify_database,
        report_path=report_path,
    )
    if inverse.answerability == "answerable":
        return inverse, True
    if inverse.answerability == "ambiguous":
        return inverse, True
    return primary, False


def _alias_answer(intent: PredicateQuery, hit: RetrievalHit) -> str:
    query_name = _normalized(intent.subject)
    if _normalized(hit.subject or "") == query_name:
        return hit.object or ""
    if _normalized(hit.object or "") == query_name:
        return hit.subject or ""
    # Entity resolution can connect an alias query to a Fact whose surface differs.
    # In that case prefer the non-empty object side of the accepted alias Fact.
    return hit.object or hit.subject or ""


def _claim_from_hit(
    intent: PredicateQuery,
    hit: RetrievalHit,
    *,
    opposite_permission: bool,
) -> AnswerClaim:
    predicate = intent.predicate
    requested_role = intent.requested_role
    subject = intent.subject
    object_value = intent.object
    value: object = None
    unit = hit.unit or intent.unit
    scope = hit.predicate_scope or intent.predicate_scope
    fact_polarity = hit.polarity
    boolean_answer: bool | None = None

    if predicate == "alias":
        if requested_role == "object":
            object_value = _alias_answer(intent, hit)
        else:
            subject = intent.subject
            object_value = intent.object
            boolean_answer = bool(fact_polarity)
    elif predicate == "defeats":
        if requested_role == "subject":
            subject = hit.subject or ""
            object_value = intent.object
        elif requested_role == "object":
            subject = intent.subject
            object_value = hit.object or ""
        else:
            boolean_answer = bool(fact_polarity)
    elif predicate == "located_in":
        if requested_role == "object":
            object_value = hit.object or ""
        else:
            boolean_answer = bool(fact_polarity)
    elif predicate == "count":
        value = hit.value
    elif predicate == "date":
        value = hit.value
    elif predicate == "permission":
        expected = intent.polarity
        if expected is None or fact_polarity is None:
            raise StrictQAError("permission answer lacks explicit polarity")
        boolean_answer = bool(fact_polarity) == bool(expected)
        if opposite_permission and boolean_answer:
            raise StrictQAError("opposite permission support cannot yield a positive answer")
    else:
        raise StrictQAError(f"unsupported strict answer predicate: {predicate}")

    return AnswerClaim(
        predicate=predicate,
        requested_role=requested_role,
        subject=subject,
        object=object_value,
        value=value,
        unit=unit,
        predicate_scope=scope,
        fact_polarity=fact_polarity,
        boolean_answer=boolean_answer,
        temporal_scope=intent.temporal_scope,
    )


def _claim_key(claim: AnswerClaim) -> str:
    return _canonical_json(claim.to_dict())


def _citation(hit: RetrievalHit, ordinal: int) -> EvidenceCitation:
    if hit.hit_type != "fact" or not hit.fact_id or not hit.claim_type:
        raise StrictQAError("strict answers may cite only typed Fact hits")
    if hit.evidence_end <= hit.evidence_start or not hit.evidence_text:
        raise StrictQAError("Fact citation has an invalid evidence span")
    return EvidenceCitation(
        citation_id=f"E{ordinal}",
        citation_schema_version=CITATION_SCHEMA_VERSION,
        fact_id=hit.fact_id,
        source_id=hit.source_id,
        unit_id=hit.unit_id,
        evidence_start=hit.evidence_start,
        evidence_end=hit.evidence_end,
        evidence_text=hit.evidence_text,
        evidence_sha256=_sha256_bytes(hit.evidence_text.encode("utf-8")),
        claim_type=hit.claim_type,
        predicate_scope=hit.predicate_scope or "",
        canonical_status=hit.canonical_status or "",
        fact_polarity=bool(hit.polarity),
    )


def _markers(citations: Sequence[EvidenceCitation]) -> str:
    return "".join(f"[{item.citation_id}]" for item in citations)


def _render_answer(claim: AnswerClaim, citations: Sequence[EvidenceCitation]) -> str:
    markers = _markers(citations)
    if not markers:
        raise StrictQAError("an answered packet requires at least one citation")

    if claim.requested_role == "boolean":
        if claim.boolean_answer is None:
            raise StrictQAError("boolean query lacks a boolean answer")
        prefix = "是。" if claim.boolean_answer else "否。"
        if claim.predicate == "permission":
            relation = "允许" if claim.fact_polarity else "禁止"
            return f"{prefix}{claim.subject}{relation}{claim.object}。{markers}"
        if claim.boolean_answer:
            relation = {
                "alias": "又称",
                "defeats": "击败了",
                "located_in": "位于",
            }.get(claim.predicate, "符合该关系")
            return f"{prefix}{claim.subject}{relation}{claim.object}。{markers}"
        return f"{prefix}证据中的类型化事实明确否定了该关系。{markers}"

    if claim.predicate == "alias":
        return f"{claim.subject}又称{claim.object}。{markers}"
    if claim.predicate == "defeats":
        return f"{claim.subject}击败了{claim.object}。{markers}"
    if claim.predicate == "located_in":
        return f"{claim.subject}位于{claim.object}。{markers}"
    if claim.predicate == "count":
        return f"{claim.subject}共有{claim.value}{claim.unit}。{markers}"
    if claim.predicate == "date":
        label = _DATE_LABELS.get(claim.predicate_scope, "日期")
        return f"{claim.subject}的{label}是{claim.value}。{markers}"
    raise StrictQAError("no deterministic renderer for this answer claim")


def _refusal(
    answerability: str,
    reason_codes: Sequence[str],
) -> tuple[str, str, tuple[str, ...]]:
    if answerability == "unsupported":
        return (
            "refused_unsupported",
            "当前知识库不支持对此类问题作出可靠回答。",
            tuple(dict.fromkeys((*reason_codes, "REFUSAL_UNSUPPORTED_PREDICATE"))),
        )
    if answerability == "ambiguous":
        return (
            "refused_ambiguous",
            "现有证据存在歧义、冲突或未限定的时间版本，无法给出唯一答案。",
            tuple(dict.fromkeys((*reason_codes, "REFUSAL_AMBIGUOUS_EVIDENCE"))),
        )
    return (
        "refused_insufficient_evidence",
        "现有证据没有记录该问题所需的类型化事实。",
        tuple(dict.fromkeys((*reason_codes, "REFUSAL_INSUFFICIENT_TYPED_EVIDENCE"))),
    )


def _packet_id(payload: Mapping[str, object]) -> str:
    return "qa_" + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:24]


def _make_packet(
    *,
    result: QueryResult,
    database_path: Path,
    report_file: Path,
    question: str,
    source_id: str | None,
    retrieval_limit: int,
    max_citations: int,
    decision: str,
    refusal_kind: str | None,
    reason_codes: Sequence[str],
    answer_text: str,
    answer_claim: AnswerClaim | None,
    citations: Sequence[EvidenceCitation],
) -> StrictQAPacket:
    base: dict[str, object] = {
        "qa_schema_version": QA_SCHEMA_VERSION,
        "refusal_policy_version": REFUSAL_POLICY_VERSION,
        "query_parser_version": result.query_parser_version,
        "index_schema_version": result.index_schema_version,
        "index_logical_sha256": result.index_logical_sha256,
        "database_sha256": _sha256_bytes(database_path.read_bytes()),
        "index_report_sha256": _sha256_bytes(report_file.read_bytes()),
        "question": question,
        "normalized_question": result.intent.normalized_query,
        "source_id_filter": source_id,
        "retrieval_limit": retrieval_limit,
        "max_citations": max_citations,
        "decision": decision,
        "answered": decision == "answered",
        "refusal_kind": refusal_kind,
        "reason_codes": list(reason_codes),
        "answer_text": answer_text,
        "answer_claim": answer_claim.to_dict() if answer_claim else None,
        "citations": [item.to_dict() for item in citations],
        "citation_entailment": "entailed_structured" if decision == "answered" else "not_applicable",
        "lexical_evidence_count": len(result.lexical_hits),
        "may_present": True,
        "may_freeze": False,
    }
    identifier = _packet_id(base)
    return StrictQAPacket(
        qa_schema_version=QA_SCHEMA_VERSION,
        refusal_policy_version=REFUSAL_POLICY_VERSION,
        query_parser_version=result.query_parser_version,
        index_schema_version=result.index_schema_version,
        index_logical_sha256=result.index_logical_sha256,
        database_sha256=str(base["database_sha256"]),
        index_report_sha256=str(base["index_report_sha256"]),
        question=question,
        normalized_question=result.intent.normalized_query,
        source_id_filter=source_id,
        retrieval_limit=retrieval_limit,
        max_citations=max_citations,
        decision=decision,
        refusal_kind=refusal_kind,
        reason_codes=tuple(reason_codes),
        answer_text=answer_text,
        answer_claim=answer_claim,
        citations=tuple(citations),
        citation_entailment=str(base["citation_entailment"]),
        lexical_evidence_count=len(result.lexical_hits),
        may_present=True,
        may_freeze=False,
        packet_id=identifier,
    )


def answer_strict(
    database_path: str | Path,
    question: str,
    *,
    source_id: str | None = None,
    retrieval_limit: int = 20,
    max_citations: int = 5,
    verify_database: bool = True,
    report_path: str | Path | None = None,
) -> StrictQAPacket:
    """Return a deterministic answered or refused evidence packet."""

    _validate_limits(retrieval_limit, max_citations)
    if not isinstance(question, str) or not question.strip():
        raise StrictQAError("question must be a non-empty string")
    if source_id is not None and (not isinstance(source_id, str) or not source_id.strip()):
        raise StrictQAError("source_id must be a non-empty string when supplied")

    database = Path(database_path)
    report_file = _report_path(database, report_path)
    primary = query_hybrid_index(
        database,
        question,
        source_id=source_id,
        limit=retrieval_limit,
        verify_database=verify_database,
        report_path=report_path,
    )
    support, opposite_permission = _support_result(
        database,
        primary,
        source_id=source_id,
        retrieval_limit=retrieval_limit,
        verify_database=verify_database,
        report_path=report_path,
    )

    if support.answerability != "answerable":
        answerability = support.answerability if opposite_permission else primary.answerability
        reasons = support.reason_codes if opposite_permission else primary.reason_codes
        decision, message, refusal_reasons = _refusal(answerability, reasons)
        return _make_packet(
            result=primary,
            database_path=database,
            report_file=report_file,
            question=question,
            source_id=source_id,
            retrieval_limit=retrieval_limit,
            max_citations=max_citations,
            decision=decision,
            refusal_kind=decision,
            reason_codes=refusal_reasons,
            answer_text=message,
            answer_claim=None,
            citations=(),
        )

    fact_hits = [item for item in support.hits if item.hit_type == "fact"]
    if not fact_hits:
        decision, message, refusal_reasons = _refusal(
            "not_answerable", ("ANSWERABLE_WITHOUT_TYPED_FACT",)
        )
        return _make_packet(
            result=primary,
            database_path=database,
            report_file=report_file,
            question=question,
            source_id=source_id,
            retrieval_limit=retrieval_limit,
            max_citations=max_citations,
            decision=decision,
            refusal_kind=decision,
            reason_codes=refusal_reasons,
            answer_text=message,
            answer_claim=None,
            citations=(),
        )

    claims = [
        _claim_from_hit(primary.intent, hit, opposite_permission=opposite_permission)
        for hit in fact_hits
    ]
    distinct_claims = {_claim_key(item) for item in claims}
    if len(distinct_claims) != 1:
        decision, message, refusal_reasons = _refusal(
            "ambiguous", ("PHASE6_MULTIPLE_SEMANTIC_ANSWERS",)
        )
        return _make_packet(
            result=primary,
            database_path=database,
            report_file=report_file,
            question=question,
            source_id=source_id,
            retrieval_limit=retrieval_limit,
            max_citations=max_citations,
            decision=decision,
            refusal_kind=decision,
            reason_codes=refusal_reasons,
            answer_text=message,
            answer_claim=None,
            citations=(),
        )

    selected_hits = sorted(
        fact_hits,
        key=lambda item: (item.source_id, item.evidence_start, item.evidence_end, item.fact_id or ""),
    )[:max_citations]
    citations = tuple(_citation(hit, index) for index, hit in enumerate(selected_hits, start=1))
    claim = claims[0]
    answer_text = _render_answer(claim, citations)
    reasons = tuple(
        dict.fromkeys(
            (*primary.reason_codes, *(support.reason_codes if opposite_permission else ()),
             "STRICT_TYPED_ANSWER", "CITATIONS_STRUCTURALLY_ENTAILED")
        )
    )
    return _make_packet(
        result=primary,
        database_path=database,
        report_file=report_file,
        question=question,
        source_id=source_id,
        retrieval_limit=retrieval_limit,
        max_citations=max_citations,
        decision="answered",
        refusal_kind=None,
        reason_codes=reasons,
        answer_text=answer_text,
        answer_claim=claim,
        citations=citations,
    )


def _load_packet(packet: Mapping[str, object] | str | Path) -> dict[str, object]:
    if isinstance(packet, Mapping):
        return dict(packet)
    path = Path(packet)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StrictQAError(f"invalid QA packet JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise StrictQAError("QA packet must be a JSON object")
    return payload


def verify_strict_packet(
    database_path: str | Path,
    packet: Mapping[str, object] | str | Path,
    *,
    report_path: str | Path | None = None,
) -> PacketVerification:
    """Recompute a packet and reject any changed answer, citation, or hash field."""

    try:
        supplied = _load_packet(packet)
    except (OSError, UnicodeError, StrictQAError) as exc:
        return PacketVerification(
            "rejected", False, ("MALFORMED_QA_PACKET", type(exc).__name__), "", ""
        )

    supplied_id = supplied.get("packet_id") if isinstance(supplied.get("packet_id"), str) else ""
    question = supplied.get("question")
    source_id = supplied.get("source_id_filter")
    retrieval_limit = supplied.get("retrieval_limit")
    max_citations = supplied.get("max_citations")
    if not isinstance(question, str):
        return PacketVerification("rejected", False, ("PACKET_QUESTION_INVALID",), supplied_id, "")
    if source_id is not None and not isinstance(source_id, str):
        return PacketVerification("rejected", False, ("PACKET_SOURCE_FILTER_INVALID",), supplied_id, "")
    if isinstance(retrieval_limit, bool) or not isinstance(retrieval_limit, int):
        return PacketVerification("rejected", False, ("PACKET_RETRIEVAL_LIMIT_INVALID",), supplied_id, "")
    if isinstance(max_citations, bool) or not isinstance(max_citations, int):
        return PacketVerification("rejected", False, ("PACKET_CITATION_LIMIT_INVALID",), supplied_id, "")

    try:
        expected = answer_strict(
            database_path,
            question,
            source_id=source_id,
            retrieval_limit=retrieval_limit,
            max_citations=max_citations,
            verify_database=True,
            report_path=report_path,
        )
    except (OSError, UnicodeError, RetrievalError, StrictQAError):
        return PacketVerification(
            "rejected", False, ("DATABASE_OR_INDEX_INTEGRITY_ERROR",), supplied_id, ""
        )

    expected_payload = expected.to_dict()
    reasons: list[str] = []
    expected_keys = set(expected_payload)
    supplied_keys = set(supplied)
    if supplied_keys != expected_keys:
        if expected_keys - supplied_keys:
            reasons.append("PACKET_FIELDS_MISSING")
        if supplied_keys - expected_keys:
            reasons.append("PACKET_FIELDS_UNEXPECTED")

    field_codes = {
        "qa_schema_version": "QA_SCHEMA_VERSION_MISMATCH",
        "refusal_policy_version": "REFUSAL_POLICY_VERSION_MISMATCH",
        "query_parser_version": "QUERY_PARSER_VERSION_MISMATCH",
        "index_schema_version": "INDEX_SCHEMA_VERSION_MISMATCH",
        "index_logical_sha256": "INDEX_LOGICAL_HASH_MISMATCH",
        "database_sha256": "DATABASE_HASH_MISMATCH",
        "index_report_sha256": "INDEX_REPORT_HASH_MISMATCH",
        "decision": "DECISION_MISMATCH",
        "refusal_kind": "REFUSAL_KIND_MISMATCH",
        "reason_codes": "REASON_CODES_MISMATCH",
        "answer_text": "ANSWER_TEXT_NOT_ENTAILED",
        "answer_claim": "ANSWER_CLAIM_NOT_ENTAILED",
        "citations": "CITATIONS_NOT_ENTAILED",
        "citation_entailment": "CITATION_STATUS_MISMATCH",
        "may_present": "PRESENTATION_AUTHORITY_MISMATCH",
        "may_freeze": "FREEZE_AUTHORITY_MISMATCH",
        "packet_id": "PACKET_ID_MISMATCH",
    }
    for field, code in field_codes.items():
        if supplied.get(field) != expected_payload.get(field):
            reasons.append(code)

    # Compare the remaining fields as a final completeness gate.
    if _canonical_json(supplied) != _canonical_json(expected_payload):
        reasons.append("PACKET_RECOMPUTATION_MISMATCH")

    unique_reasons = tuple(dict.fromkeys(reasons))
    if unique_reasons:
        return PacketVerification(
            "rejected", False, unique_reasons, supplied_id, expected.packet_id
        )
    return PacketVerification(
        "accepted",
        True,
        ("PACKET_RECOMPUTED_EXACTLY", "CITATIONS_STRUCTURALLY_ENTAILED"),
        supplied_id,
        expected.packet_id,
    )
