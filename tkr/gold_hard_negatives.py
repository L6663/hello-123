"""Database-grounded validation for Phase 7 hard-negative Gold categories."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Sequence

from .hybrid_retrieval import PredicateQuery, _normalize_surface
from .strict_qa import StrictQAPacket


_ACTIVE_STATUSES = ("canonical", "temporal_variant", "compatible_variant", "contested")


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
    if intent.predicate != "count" or not intent.subject:
        return False
    source_sql, source_params = _source_clause(source_id)
    rows = connection.execute(
        "SELECT normalized_subject,value_text,unit FROM facts "
        f"WHERE claim_type='count'{source_sql} ORDER BY fact_id",
        source_params,
    ).fetchall()
    subject = _normalize_surface(intent.subject)
    question = _normalize_surface(intent.raw_query)
    values: list[str] = []
    for normalized_subject, value_text, unit in rows:
        normalized_subject = str(normalized_subject)
        if normalized_subject != subject and normalized_subject not in question:
            continue
        if intent.unit and str(unit) != intent.unit:
            continue
        normalized_value = str(value_text).strip()
        if normalized_value and normalized_value not in values:
            values.append(normalized_value)
    return any(
        left != right and (left.startswith(right) or right.startswith(left))
        for index, left in enumerate(values)
        for right in values[index + 1 :]
    )


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
