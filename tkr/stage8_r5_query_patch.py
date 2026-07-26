"""Stage 8-R5 natural count and directional Tier-A query compatibility."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import hybrid_retrieval as _hybrid
from . import literary_query as _literary

_APPLIED = False
_ORIGINAL_PREDICATE_PARSE = _hybrid.parse_predicate_query
_ORIGINAL_LITERARY_PARSE = _literary.parse_literary_query
_ORIGINAL_LITERARY_QUERY = _literary.query_literary_engine
_COUNT_RE = re.compile(r"^(?P<subject>.+?)(?:现在|目前|最初|原先|以前)?(?:一共|共有|有)?几(?P<unit>[\u4e00-\u9fffA-Za-z]+)[？?]*$")
_DEFEAT_SUBJECT_RE = re.compile(r"^谁(?:曾经|后来|最终)?(?:击败|战胜|打败|击溃)了?(?P<object>.+?)[？?]*$")
_DEFEAT_OBJECT_RE = re.compile(r"^(?P<subject>.+?)(?:曾经|后来|最终)?(?:击败|战胜|打败|击溃)了?谁[？?]*$")


def _parse_predicate_query(question: str):
    intent = _ORIGINAL_PREDICATE_PARSE(question)
    if intent.supported:
        return intent
    raw = _hybrid.unicodedata.normalize("NFKC", question).strip()
    compact = re.sub(r"\s+", "", raw)
    match = _COUNT_RE.match(compact)
    if match is None:
        return intent
    subject = _hybrid._clean_capture(match.group("subject"))
    unit = _hybrid._clean_capture(match.group("unit"))
    if not subject:
        return intent
    return _hybrid.PredicateQuery(
        raw_query=raw,
        normalized_query=_hybrid._normalize_surface(raw),
        predicate="count",
        subject=subject,
        object="",
        requested_role="value",
        unit=unit,
        predicate_scope="",
        polarity=None,
        temporal_scope=_hybrid._temporal_scope(compact),
        supported=True,
        reason="SUPPORTED_TYPED_PREDICATE",
    )


def _parse_literary_query(question: str):
    raw = _literary.unicodedata.normalize("NFKC", question).strip()
    compact = re.sub(r"\s+", "", raw)
    for intent_type, pattern in (
        ("directional_defeats_subject", _DEFEAT_SUBJECT_RE),
        ("directional_defeats_object", _DEFEAT_OBJECT_RE),
    ):
        match = pattern.match(compact)
        if match:
            groups = match.groupdict()
            return _literary.LiteraryQueryIntent(
                intent_type=intent_type,
                raw_question=raw,
                normalized_question=_literary._normalized(raw),
                subject=(groups.get("subject") or "").strip(),
                object=(groups.get("object") or "").strip(),
                volume_ordinal=None,
                chapter_ordinal=None,
                event_component="",
                requested_tier=None,
            )
    return _ORIGINAL_LITERARY_PARSE(question)


def _query_literary_engine(output_directory: str | Path, question: str, *, max_items: int = 20, max_citations: int = 12):
    intent = _parse_literary_query(question)
    if intent.intent_type not in {"directional_defeats_subject", "directional_defeats_object"}:
        return _ORIGINAL_LITERARY_QUERY(output_directory, question, max_items=max_items, max_citations=max_citations)
    if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 100:
        raise _literary.LiteraryQueryError("max_items must be an integer between 1 and 100")
    root = Path(output_directory)
    verification = _literary.verify_literary_engine(root)
    if not verification.valid:
        raise _literary.LiteraryQueryError("literary sidecar failed verification: " + ",".join(verification.reason_codes))
    database = root / "literary.sqlite"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        metadata = _literary._metadata(connection)
        endpoint = intent.object if intent.intent_type == "directional_defeats_subject" else intent.subject
        endpoint_entities = _literary._resolve_entity(connection, endpoint) if endpoint else []
        if len(endpoint_entities) > 1:
            return _literary._refuse(metadata, database, question, intent, "ambiguous_entity", ("AMBIGUOUS_DIRECTIONAL_ENDPOINT",), "该名称对应多个实体，无法唯一确定胜负关系端点。")
        params: list[object] = []
        clauses = ["a.predicate='defeats'", "a.tier='A'", "a.status='active'"]
        field = "a.object_entity_id" if intent.intent_type == "directional_defeats_subject" else "a.subject_entity_id"
        text_field = "a.object_text" if intent.intent_type == "directional_defeats_subject" else "a.subject_text"
        if endpoint_entities:
            clauses.append(f"{field}=?")
            params.append(str(endpoint_entities[0]["entity_id"]))
        else:
            clauses.append(f"replace(lower({text_field}),' ','')=?")
            params.append(_literary._normalized(endpoint))
        rows = list(connection.execute(
            "SELECT a.* FROM assertions a WHERE " + " AND ".join(clauses) + " ORDER BY a.assertion_id LIMIT ?",
            (*params, max_items),
        ).fetchall())
        if not rows:
            return _literary._refuse(metadata, database, question, intent, "insufficient_directional_fact_evidence", ("NO_ACTIVE_TIER_A_DEFEAT_ASSERTION",), "当前知识库没有可作为原文事实发布的定向胜负记录。")
        evidence_rows = _literary._assertion_evidence(connection, [str(row["assertion_id"]) for row in rows])
        citations = []
        citation_ids_by_assertion: dict[str, list[str]] = {}
        for evidence_row in evidence_rows[:max_citations]:
            citation = _literary._citation(evidence_row, len(citations) + 1)
            citations.append(citation)
            citation_ids_by_assertion.setdefault(str(evidence_row["assertion_id"]), []).append(citation.citation_id)
        items = _literary._items_from_assertions(connection, rows, {key: tuple(value) for key, value in citation_ids_by_assertion.items()})
        answer_text = "；".join(f"{item.subject}击败了{item.object}" for item in items)
        return _literary._make_packet(
            metadata=metadata, database=database, question=question, intent=intent,
            decision="answered", refusal_kind=None,
            reasons=("ACTIVE_TIER_A_DIRECTIONAL_DEFEAT_MATCH", "EXACT_EVIDENCE_ATTACHED"),
            answer_text=answer_text, items=items, citations=citations,
        )
    finally:
        connection.close()


def apply_stage8_r5_query_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _hybrid.QUERY_PARSER_VERSION = "tkr-predicate-query-v2"
    _hybrid.parse_predicate_query = _parse_predicate_query
    _literary.LITERARY_QUERY_PARSER_VERSION = "tkr-literary-query-parser-v2"
    _literary.parse_literary_query = _parse_literary_query
    _literary.query_literary_engine = _query_literary_engine
    _APPLIED = True


__all__ = ["apply_stage8_r5_query_patch"]
