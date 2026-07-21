"""Database-grounded validation for Phase 7 hard-negative Gold categories."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from typing import Sequence

from .hybrid_retrieval import PredicateQuery, _normalize_surface
from .strict_qa import StrictQAPacket


_ACTIVE_STATUSES = ("canonical", "temporal_variant", "compatible_variant", "contested")
_DECIMAL_TEXT = re.compile(r"^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?$")


def _source_clause(source_id: str | None) -> tuple[str, list[object]]:
    if source_id is None:
        return "", []
    return " AND source_id=?", [source_id]


def _relation_direction_exists(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    source_id: str | None,
) -> bool:
    if intent.predicate not in {"defeats", "located_in"}:
        return False
    source_sql, source_params = _source_clause(source_id)
    status_marks = ",".join("?" for _ in _ACTIVE_STATUSES)
    params: list[object] = [intent.predicate, *_ACTIVE_STATUSES]
    if intent.requested_role == "object" and intent.subject:
        relation_sql = "normalized_object=?"
        params.append(_normalize_surface(intent.subject))
    elif intent.requested_role == "subject" and intent.object:
        relation_sql = "normalized_subject=?"
        params.append(_normalize_surface(intent.object))
    elif intent.requested_role == "boolean" and intent.subject and intent.object:
        relation_sql = "normalized_subject=? AND normalized_object=?"
        params.extend((_normalize_surface(intent.object), _normalize_surface(intent.subject)))
    else:
        return False
    params.extend(source_params)
    row = connection.execute(
        f"SELECT 1 FROM facts WHERE claim_type=? AND canonical_status IN ({status_marks}) "
        f"AND {relation_sql}{source_sql} LIMIT 1",
        params,
    ).fetchone()
    return row is not None


def _numeric_prefix_collision_exists(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    source_id: str | None,
) -> bool:
    """Confirm that the queried count subject has two decimal prefix-colliding values.

    The count query parser's optional unit capture is intentionally not used as an
    evidence filter here.  Unit parsing is a query-shape concern; the adversarial
    property being certified is the presence of exact values such as 100 and 1000
    for the same subject.  Requiring the parsed unit previously allowed harmless
    parser differences to erase a real numeric-prefix case.
    """

    if intent.predicate != "count":
        return False
    source_sql, source_params = _source_clause(source_id)
    rows = connection.execute(
        "SELECT normalized_subject,value_text FROM facts "
        f"WHERE claim_type='count'{source_sql} ORDER BY fact_id",
        source_params,
    ).fetchall()
    parsed_subject = _normalize_surface(intent.subject)
    question = _normalize_surface(intent.raw_query)
    values_by_subject: dict[str, set[str]] = {}
    for normalized_subject, value_text in rows:
        fact_subject = str(normalized_subject)
        if not fact_subject:
            continue
        if fact_subject != parsed_subject and fact_subject not in question:
            continue
        normalized_value = str(value_text).strip().lstrip("+")
        if not _DECIMAL_TEXT.fullmatch(normalized_value):
            continue
        values_by_subject.setdefault(fact_subject, set()).add(normalized_value)

    for values in values_by_subject.values():
        ordered = sorted(values)
        if any(
            left != right and (left.startswith(right) or right.startswith(left))
            for index, left in enumerate(ordered)
            for right in ordered[index + 1 :]
        ):
            return True
    return False


def _entity_name_present(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    source_id: str | None,
) -> bool:
    question = _normalize_surface(intent.raw_query)
    rows = connection.execute(
        "SELECT n.normalized_name,e.source_ids_json "
        "FROM entity_names AS n JOIN entities AS e ON e.entity_id=n.entity_id "
        "ORDER BY length(n.normalized_name) DESC,n.normalized_name"
    ).fetchall()
    for normalized_name, source_ids_json in rows:
        name = str(normalized_name)
        if len(name) < 2 or name not in question:
            continue
        if source_id is None:
            return True
        try:
            source_ids = json.loads(source_ids_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(source_ids, list) and source_id in source_ids:
            return True
    return False


def validate_hard_negative_outcome(
    database_path: str | Path,
    intent: PredicateQuery,
    packet: StrictQAPacket,
    tags: Sequence[str],
    *,
    source_id: str | None,
) -> tuple[str, ...]:
    """Return failure codes for hard-negative labels not established by evidence."""

    failures: list[str] = []
    tag_set = set(tags)
    connection = sqlite3.connect(f"file:{Path(database_path)}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        for tag in sorted(tag_set):
            established = True
            if tag == "relation_direction":
                established = _relation_direction_exists(connection, intent, source_id)
            elif tag == "numeric_prefix":
                established = _numeric_prefix_collision_exists(connection, intent, source_id)
            elif tag == "temporal_scope":
                established = "TEMPORAL_SCOPE_REQUIRED" in packet.reason_codes
            elif tag == "contested_fact":
                established = "CONTESTED_FACTS_PRESENT" in packet.reason_codes
            elif tag == "lexical_distractor":
                established = (
                    packet.decision == "refused_insufficient_evidence"
                    and packet.lexical_evidence_count > 0
                )
            elif tag == "entity_only_no_predicate":
                established = (
                    packet.decision == "refused_unsupported"
                    and _entity_name_present(connection, intent, source_id)
                )
            elif tag == "unsupported_open_predicate":
                established = packet.decision == "refused_unsupported"
            elif tag == "absence_not_negative":
                established = (
                    intent.predicate == "permission"
                    and packet.decision == "refused_insufficient_evidence"
                    and packet.answer_claim is None
                    and not packet.citations
                )
            if tag in {
                "relation_direction",
                "numeric_prefix",
                "temporal_scope",
                "contested_fact",
                "lexical_distractor",
                "entity_only_no_predicate",
                "unsupported_open_predicate",
                "absence_not_negative",
            } and not established:
                failures.append(f"HARD_NEGATIVE_EVIDENCE_NOT_ESTABLISHED:{tag}")
    finally:
        connection.close()
    return tuple(failures)
