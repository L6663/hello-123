"""Database-grounded validation for Phase 7 hard-negative Gold categories."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
from typing import Sequence

from .hybrid_retrieval import PredicateQuery, _normalize_surface
from .strict_qa import StrictQAPacket


_ACTIVE_STATUSES = ("canonical", "temporal_variant", "compatible_variant", "contested")
_RELATION_PREDICATES = frozenset({"defeats", "located_in"})


def _source_clause(source_id: str | None) -> tuple[str, list[object]]:
    if source_id is None:
        return "", []
    return " AND source_id=?", [source_id]


def _active_clause() -> tuple[str, list[object]]:
    marks = ",".join("?" for _ in _ACTIVE_STATUSES)
    return f"canonical_status IN ({marks})", list(_ACTIVE_STATUSES)


def _relation_direction_exists(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    source_id: str | None,
) -> bool:
    """Return true only when the index contains the relation in the reverse role."""

    if intent.predicate not in _RELATION_PREDICATES:
        return False
    active_sql, active_params = _active_clause()
    source_sql, source_params = _source_clause(source_id)
    params: list[object] = [intent.predicate, *active_params]

    if intent.requested_role == "object" and intent.subject:
        reverse_sql = "normalized_object=?"
        params.append(_normalize_surface(intent.subject))
    elif intent.requested_role == "subject" and intent.object:
        reverse_sql = "normalized_subject=?"
        params.append(_normalize_surface(intent.object))
    elif intent.requested_role == "boolean" and intent.subject and intent.object:
        reverse_sql = "normalized_subject=? AND normalized_object=?"
        params.extend((_normalize_surface(intent.object), _normalize_surface(intent.subject)))
    else:
        return False

    params.extend(source_params)
    return connection.execute(
        f"SELECT 1 FROM facts WHERE claim_type=? AND {active_sql} "
        f"AND {reverse_sql}{source_sql} LIMIT 1",
        params,
    ).fetchone() is not None


def _decimal_key(value: object) -> str | None:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    normalized = number.normalize()
    return format(normalized, "f").lstrip("+") or "0"


def _numeric_prefix_collision_exists(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    source_id: str | None,
) -> bool:
    """Confirm exact count facts for one subject/unit have prefix-colliding values."""

    if intent.predicate != "count" or not intent.subject:
        return False
    active_sql, active_params = _active_clause()
    source_sql, source_params = _source_clause(source_id)
    params: list[object] = [
        *active_params,
        _normalize_surface(intent.subject),
        *source_params,
    ]
    rows = connection.execute(
        "SELECT normalized_subject,value_text,unit FROM facts "
        f"WHERE claim_type='count' AND {active_sql} AND normalized_subject=?"
        f"{source_sql} ORDER BY fact_id",
        params,
    ).fetchall()

    values_by_unit: dict[str, set[str]] = defaultdict(set)
    for _, value_text, unit in rows:
        value = _decimal_key(value_text)
        if value is not None:
            values_by_unit[str(unit)].add(value)

    for values in values_by_unit.values():
        ordered = sorted(values)
        if any(
            left != right and (left.startswith(right) or right.startswith(left))
            for index, left in enumerate(ordered)
            for right in ordered[index + 1 :]
        ):
            return True
    return False


def _matching_fact_rows(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    source_id: str | None,
) -> list[sqlite3.Row]:
    if not intent.supported or not intent.subject:
        return []
    source_sql, source_params = _source_clause(source_id)
    clauses = ["claim_type=?", "normalized_subject=?"]
    params: list[object] = [intent.predicate, _normalize_surface(intent.subject)]
    if intent.predicate in {"permission"} and intent.object:
        clauses.append("normalized_object=?")
        params.append(_normalize_surface(intent.object))
    if intent.predicate == "date" and intent.predicate_scope not in {"", "generic_date"}:
        clauses.append("predicate_scope=?")
        params.append(intent.predicate_scope)
    params.extend(source_params)
    connection.row_factory = sqlite3.Row
    return list(
        connection.execute(
            "SELECT * FROM facts WHERE " + " AND ".join(clauses) + source_sql
            + " ORDER BY evidence_start,fact_id",
            params,
        )
    )


def _answer_signature(row: sqlite3.Row) -> tuple[object, ...]:
    claim_type = str(row["claim_type"])
    if claim_type == "count":
        return (_decimal_key(row["value_text"]), str(row["unit"]))
    if claim_type == "date":
        return (str(row["predicate_scope"]), str(row["value_text"]))
    if claim_type == "permission":
        return (str(row["normalized_object"]), int(row["polarity"]))
    return (str(row["normalized_object"]), int(row["polarity"]))


def _temporal_scope_exists(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    source_id: str | None,
) -> bool:
    if intent.temporal_scope != "any":
        return False
    rows = _matching_fact_rows(connection, intent, source_id)
    temporal = [row for row in rows if row["canonical_status"] == "temporal_variant"]
    return len(temporal) >= 2 and len({_answer_signature(row) for row in temporal}) >= 2


def _contested_fact_exists(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    source_id: str | None,
) -> bool:
    return any(
        row["canonical_status"] == "contested"
        for row in _matching_fact_rows(connection, intent, source_id)
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


def _absence_not_negative_exists(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    source_id: str | None,
) -> bool:
    """Require a known permission subject but no fact for the requested action."""

    if intent.predicate != "permission" or not intent.subject or not intent.object:
        return False
    source_sql, source_params = _source_clause(source_id)
    active_sql, active_params = _active_clause()
    subject = _normalize_surface(intent.subject)
    action = _normalize_surface(intent.object)
    rows = connection.execute(
        "SELECT normalized_object FROM facts WHERE claim_type='permission' "
        f"AND {active_sql} AND normalized_subject=?{source_sql}",
        [*active_params, subject, *source_params],
    ).fetchall()
    return bool(rows) and all(str(row[0]) != action for row in rows)


def validate_hard_negative_outcome(
    database_path: str | Path,
    intent: PredicateQuery,
    packet: StrictQAPacket,
    tags: Sequence[str],
    *,
    source_id: str | None,
) -> tuple[str, ...]:
    """Return failure codes for labels not established by indexed facts/query evidence."""

    failures: list[str] = []
    connection = sqlite3.connect(f"file:{Path(database_path)}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        for tag in sorted(set(tags)):
            if tag == "relation_direction":
                established = _relation_direction_exists(connection, intent, source_id)
            elif tag == "numeric_prefix":
                established = _numeric_prefix_collision_exists(connection, intent, source_id)
            elif tag == "temporal_scope":
                established = (
                    "TEMPORAL_SCOPE_REQUIRED" in packet.reason_codes
                    and _temporal_scope_exists(connection, intent, source_id)
                )
            elif tag == "contested_fact":
                established = (
                    "CONTESTED_FACTS_PRESENT" in packet.reason_codes
                    and _contested_fact_exists(connection, intent, source_id)
                )
            elif tag == "lexical_distractor":
                established = (
                    packet.decision == "refused_insufficient_evidence"
                    and packet.lexical_evidence_count > 0
                    and not _matching_fact_rows(connection, intent, source_id)
                )
            elif tag in {"entity_only_no_predicate", "unsupported_open_predicate"}:
                established = (
                    packet.decision == "refused_unsupported"
                    and not intent.supported
                    and _entity_name_present(connection, intent, source_id)
                )
            elif tag == "absence_not_negative":
                established = (
                    packet.decision == "refused_insufficient_evidence"
                    and packet.answer_claim is None
                    and not packet.citations
                    and _absence_not_negative_exists(connection, intent, source_id)
                )
            else:
                continue
            if not established:
                failures.append(f"HARD_NEGATIVE_EVIDENCE_NOT_ESTABLISHED:{tag}")
    finally:
        connection.close()
    return tuple(failures)
