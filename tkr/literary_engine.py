"""Build and verify a chapter-addressable literary knowledge sidecar.

Stage 7 does not replace the frozen v5 typed-fact index.  It consumes a fully
verified immutable knowledge project and projects it into a richer literary
model with chapter addresses, exact evidence anchors, epistemic tiers,
time-bounded relationships, event components, and revision history.

The sidecar is deterministic and fail-closed.  Existing accepted typed facts are
imported as tier-A assertions.  Optional annotation JSONL may add evidence-bound
A facts, multi-evidence B syntheses, or explicitly attributed C interpretations.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from typing import Iterable, Mapping, Sequence

from .hashing import sha256_file
from .literary_models import (
    ASSERTION_SCHEMA_VERSION,
    CHAPTER_SCHEMA_VERSION,
    ENTITY_SCHEMA_VERSION,
    EVIDENCE_ANCHOR_SCHEMA_VERSION,
    EVENT_SCHEMA_VERSION,
    LITERARY_SYSTEM_VERSION,
    RELATIONSHIP_SCHEMA_VERSION,
    REVISION_SCHEMA_VERSION,
    ChapterRecord,
    EvidenceAnchor,
    KnowledgeAssertion,
    LiteraryEntity,
    LiteraryEvent,
    LiteraryModelError,
    RelationshipInterval,
    RevisionRecord,
    assertion_id,
    chapter_id,
    evidence_anchor_id,
    record_from_dict,
)
from .project_security import verify_secure_knowledge_project

LITERARY_INDEX_SCHEMA_VERSION = "tkr-literary-index-v1"
LITERARY_REPORT_SCHEMA_VERSION = "tkr-literary-report-v1"
LITERARY_MANIFEST_SCHEMA_VERSION = "tkr-literary-manifest-v1"

_DATASETS = (
    "chapters.jsonl",
    "evidence-anchors.jsonl",
    "entities.jsonl",
    "assertions.jsonl",
    "relationships.jsonl",
    "events.jsonl",
    "revisions.jsonl",
)
_ALLOWED_FILES = set(_DATASETS) | {
    "literary.sqlite",
    "literary-report.json",
    "artifact-manifest.json",
}


class LiteraryEngineError(ValueError):
    """Raised when a source project or literary sidecar is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class LiteraryBuildResult:
    status: str
    literary_system_version: str
    literary_index_schema_version: str
    project_id: str
    source_id: str
    source_sha256: str
    output_directory: str
    chapter_count: int
    addressable_chapter_count: int
    evidence_anchor_count: int
    entity_count: int
    assertion_count: int
    tier_a_count: int
    tier_b_count: int
    tier_c_count: int
    relationship_count: int
    event_count: int
    revision_count: int
    evidence_traceability_rate: float
    chapter_address_coverage: float
    logical_sha256: str
    database_sha256: str
    annotation_sha256: str | None
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_freeze: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "literary_system_version": self.literary_system_version,
            "literary_index_schema_version": self.literary_index_schema_version,
            "project_id": self.project_id,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "output_directory": self.output_directory,
            "chapter_count": self.chapter_count,
            "addressable_chapter_count": self.addressable_chapter_count,
            "evidence_anchor_count": self.evidence_anchor_count,
            "entity_count": self.entity_count,
            "assertion_count": self.assertion_count,
            "tier_a_count": self.tier_a_count,
            "tier_b_count": self.tier_b_count,
            "tier_c_count": self.tier_c_count,
            "relationship_count": self.relationship_count,
            "event_count": self.event_count,
            "revision_count": self.revision_count,
            "evidence_traceability_rate": self.evidence_traceability_rate,
            "chapter_address_coverage": self.chapter_address_coverage,
            "logical_sha256": self.logical_sha256,
            "database_sha256": self.database_sha256,
            "annotation_sha256": self.annotation_sha256,
            "project_acceptance_performed": self.project_acceptance_performed,
            "may_accept_project": self.may_accept_project,
            "may_freeze": self.may_freeze,
        }


@dataclass(frozen=True, slots=True)
class LiteraryVerification:
    status: str
    valid: bool
    reason_codes: tuple[str, ...]
    checked_file_count: int
    project_id: str
    source_id: str
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_freeze: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "valid": self.valid,
            "reason_codes": list(self.reason_codes),
            "checked_file_count": self.checked_file_count,
            "project_id": self.project_id,
            "source_id": self.source_id,
            "logical_sha256": self.logical_sha256,
            "database_sha256": self.database_sha256,
            "project_acceptance_performed": self.project_acceptance_performed,
            "may_accept_project": self.may_accept_project,
            "may_freeze": self.may_freeze,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _jsonl_bytes(rows: Iterable[object]) -> bytes:
    lines: list[str] = []
    for row in rows:
        payload = row.to_dict() if hasattr(row, "to_dict") else row
        lines.append(_canonical_json(payload))
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _load_object(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise LiteraryEngineError(f"{label} is not a safe regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiteraryEngineError(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LiteraryEngineError(f"{label} must be a JSON object")
    return payload


def _load_jsonl(path: Path, label: str, *, allow_empty: bool = True) -> list[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise LiteraryEngineError(f"{label} is not a safe regular file")
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise LiteraryEngineError(f"blank {label} record at line {line_number}")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LiteraryEngineError(f"invalid {label} JSON at line {line_number}: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise LiteraryEngineError(f"{label} record at line {line_number} must be an object")
            rows.append(payload)
    if not allow_empty and not rows:
        raise LiteraryEngineError(f"{label} must not be empty")
    return rows


def _text(row: Mapping[str, object], key: str, label: str, *, allow_empty: bool = False) -> str:
    value = row.get(key)
    if not isinstance(value, str) or (not value and not allow_empty):
        raise LiteraryEngineError(f"{label}.{key} must be a string")
    return value


def _integer(row: Mapping[str, object], key: str, label: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LiteraryEngineError(f"{label}.{key} must be an integer")
    return value


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        return None
    return value


def _volume_from_heading(heading: Mapping[str, object] | None) -> int | None:
    if not heading:
        return None
    signals = heading.get("signals", [])
    if not isinstance(signals, list):
        return None
    for signal in signals:
        if isinstance(signal, str) and signal.startswith("container_ordinal="):
            try:
                value = int(signal.split("=", 1)[1])
            except ValueError:
                return None
            return value if value > 0 else None
    return None


def _overlaps(start: int, end: int, finding: Mapping[str, object]) -> bool:
    other_start = finding.get("start_char")
    other_end = finding.get("end_char")
    return (
        isinstance(other_start, int)
        and not isinstance(other_start, bool)
        and isinstance(other_end, int)
        and not isinstance(other_end, bool)
        and start < other_end
        and other_start < end
    )


def _contamination_status(start: int, end: int, findings: Sequence[Mapping[str, object]]) -> str:
    overlapping = [item for item in findings if _overlaps(start, end, item)]
    if any(item.get("category") == "contamination_candidate" for item in overlapping):
        return "contaminated"
    if any(item.get("category") == "paratext_candidate" for item in overlapping):
        return "non_body"
    if any(item.get("severity") == "high" for item in overlapping):
        return "needs_review"
    return "clean"


def _project_inputs(root: Path) -> tuple[dict[str, object], str, list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    verification = verify_secure_knowledge_project(root)
    if not verification.valid:
        raise LiteraryEngineError(
            "source project failed security verification: " + ",".join(verification.reason_codes)
        )
    report = _load_object(root / "project-report.json", "project report")
    source_path = root / "source" / "normalized-source.txt"
    if source_path.is_symlink() or not source_path.is_file():
        raise LiteraryEngineError("normalized source is not a safe regular file")
    try:
        # Preserve the exact decoded newline sequence because source-project
        # offsets and normalized_source_sha256 are bound to the stored text.
        # Path.read_text() uses universal-newline translation and silently
        # rewrites CRLF to LF, invalidating both the hash and every character
        # offset for Windows-origin corpora.
        with source_path.open("r", encoding="utf-8", newline="") as handle:
            source_text = handle.read()
    except (OSError, UnicodeError) as exc:
        raise LiteraryEngineError(f"normalized source cannot be read strictly: {exc}") from exc
    units = _load_jsonl(root / "stage2-structure" / "unit-index.jsonl", "unit index", allow_empty=False)
    headings = _load_jsonl(root / "stage2-structure" / "heading-candidates.jsonl", "heading candidates")
    anomalies = _load_jsonl(root / "stage1-anomaly" / "anomaly-candidates.jsonl", "anomaly candidates")
    mentions = _load_jsonl(root / "bridge" / "entity" / "mentions.jsonl", "mentions")
    entities = _load_jsonl(root / "bridge" / "entity" / "entities.jsonl", "entities")
    facts = _load_jsonl(root / "bridge" / "entity" / "facts.jsonl", "facts", allow_empty=False)
    return report, source_text, units, headings, anomalies, mentions, entities, facts


def _chapters(
    source_text: str,
    units: Sequence[Mapping[str, object]],
    headings: Sequence[Mapping[str, object]],
    anomalies: Sequence[Mapping[str, object]],
) -> tuple[list[ChapterRecord], dict[str, ChapterRecord]]:
    heading_by_id = {
        str(item["heading_id"]): item
        for item in headings
        if isinstance(item.get("heading_id"), str)
    }
    result: list[ChapterRecord] = []
    lookup: dict[str, ChapterRecord] = {}
    for source_order, row in enumerate(
        sorted(units, key=lambda item: (_integer(item, "start_char", "unit"), _text(item, "unit_id", "unit")))
    ):
        unit_id_value = _text(row, "unit_id", "unit")
        source_id = _text(row, "source_id", "unit")
        source_sha = _text(row, "source_sha256", "unit")
        start = _integer(row, "start_char", "unit")
        end = _integer(row, "end_char", "unit")
        body_start = _integer(row, "body_start_char", "unit")
        body_end = _integer(row, "body_end_char", "unit")
        if not 0 <= start < end <= len(source_text) or not start <= body_start <= body_end <= end:
            raise LiteraryEngineError(f"unit span is outside normalized source: {unit_id_value}")
        content_sha = _text(row, "content_sha256", "unit")
        if sha256(source_text[start:end].encode("utf-8")).hexdigest() != content_sha:
            raise LiteraryEngineError(f"unit content hash mismatch: {unit_id_value}")
        heading_id_value = row.get("heading_id")
        heading = heading_by_id.get(str(heading_id_value)) if heading_id_value else None
        original_heading = ""
        if heading:
            heading_start = heading.get("start_char")
            heading_end = heading.get("heading_end_char")
            if isinstance(heading_start, int) and isinstance(heading_end, int) and 0 <= heading_start < heading_end <= len(source_text):
                original_heading = source_text[heading_start:heading_end].strip()
        title = str(row.get("title", ""))
        normalized_heading = " ".join(original_heading.split()) or title
        ordinal = row.get("ordinal")
        chapter_ordinal = ordinal if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0 else None
        record = ChapterRecord(
            CHAPTER_SCHEMA_VERSION,
            chapter_id(source_sha, unit_id_value, source_order, content_sha),
            source_id,
            source_sha,
            unit_id_value,
            _text(row, "unit_type", "unit"),
            source_order,
            _volume_from_heading(heading),
            chapter_ordinal,
            original_heading,
            normalized_heading,
            title,
            start,
            end,
            body_start,
            body_end,
            content_sha,
            str(row.get("structure_confidence", "unknown")),
            str(row.get("review_status", "needs_review")),
            _contamination_status(start, end, anomalies),
        )
        result.append(record)
        lookup[unit_id_value] = record
    return result, lookup


def _anchor(
    source_text: str,
    row: Mapping[str, object],
    chapter: ChapterRecord,
    *,
    role: str,
    supplied_hash_key: str | None = None,
) -> EvidenceAnchor:
    start = _integer(row, "evidence_start", role)
    end = _integer(row, "evidence_end", role)
    if not chapter.start_char <= start < end <= chapter.end_char:
        raise LiteraryEngineError(f"{role} evidence span is outside chapter {chapter.chapter_id}")
    evidence = source_text[start:end]
    evidence_hash = sha256(evidence.encode("utf-8")).hexdigest()
    if supplied_hash_key is not None:
        supplied = row.get(supplied_hash_key)
        if supplied != evidence_hash:
            raise LiteraryEngineError(f"{role} evidence hash mismatch")
    return EvidenceAnchor(
        EVIDENCE_ANCHOR_SCHEMA_VERSION,
        evidence_anchor_id(chapter.source_sha256, chapter.unit_id, start, end, evidence_hash),
        chapter.source_id,
        chapter.source_sha256,
        chapter.unit_id,
        chapter.chapter_id,
        chapter.volume_ordinal,
        chapter.chapter_ordinal,
        chapter.original_heading,
        chapter.normalized_heading,
        start,
        end,
        evidence,
        evidence_hash,
        chapter.content_sha256,
        role,
        chapter.contamination_status,
    )


def _import_base_records(
    source_text: str,
    chapter_lookup: Mapping[str, ChapterRecord],
    mention_rows: Sequence[Mapping[str, object]],
    entity_rows: Sequence[Mapping[str, object]],
    fact_rows: Sequence[Mapping[str, object]],
) -> tuple[list[EvidenceAnchor], list[LiteraryEntity], list[KnowledgeAssertion], dict[str, str]]:
    anchors: dict[str, EvidenceAnchor] = {}
    mention_anchor_by_id: dict[str, str] = {}
    for row in mention_rows:
        unit_id_value = _text(row, "unit_id", "mention")
        chapter = chapter_lookup.get(unit_id_value)
        if chapter is None:
            raise LiteraryEngineError("mention references an unknown chapter Unit")
        anchor = _anchor(source_text, row, chapter, role="entity_mention")
        anchors.setdefault(anchor.anchor_id, anchor)
        mention_anchor_by_id[_text(row, "mention_id", "mention")] = anchor.anchor_id

    assertions: list[KnowledgeAssertion] = []
    fact_anchor_by_id: dict[str, str] = {}
    for row in fact_rows:
        unit_id_value = _text(row, "unit_id", "fact")
        chapter = chapter_lookup.get(unit_id_value)
        if chapter is None:
            raise LiteraryEngineError("fact references an unknown chapter Unit")
        anchor = _anchor(source_text, row, chapter, role="direct_fact", supplied_hash_key="evidence_sha256")
        if anchor.source_status != "clean":
            raise LiteraryEngineError("accepted fact overlaps non-clean source material")
        anchors.setdefault(anchor.anchor_id, anchor)
        fact_id = _text(row, "fact_id", "fact")
        fact_anchor_by_id[fact_id] = anchor.anchor_id
        subject = str(row.get("subject", "")).strip()
        predicate = _text(row, "claim_type", "fact")
        object_text = str(row.get("object", "")).strip()
        value = row.get("value")
        polarity = bool(row.get("polarity", True))
        identifier = assertion_id(
            "A",
            "identity" if predicate == "alias" else "fact",
            subject,
            predicate,
            object_text,
            value,
            polarity,
            (anchor.anchor_id,),
            (),
        )
        assertions.append(
            KnowledgeAssertion(
                ASSERTION_SCHEMA_VERSION,
                identifier,
                "A",
                "identity" if predicate == "alias" else "fact",
                row.get("subject_entity_id") if isinstance(row.get("subject_entity_id"), str) else None,
                subject,
                predicate,
                row.get("object_entity_id") if isinstance(row.get("object_entity_id"), str) else None,
                object_text,
                value,
                polarity,
                chapter.chapter_id,
                chapter.chapter_id,
                1.0,
                (anchor.anchor_id,),
                (),
                (),
                "source_explicit",
                "active" if row.get("canonical_status") != "contested" else "contested",
                1,
            )
        )

    entities: list[LiteraryEntity] = []
    for row in entity_rows:
        entity_identifier = _text(row, "entity_id", "entity")
        mention_ids = row.get("mention_ids", [])
        if not isinstance(mention_ids, list):
            raise LiteraryEngineError("entity.mention_ids must be a list")
        anchor_ids = tuple(
            sorted(
                {
                    mention_anchor_by_id[item]
                    for item in mention_ids
                    if isinstance(item, str) and item in mention_anchor_by_id
                }
            )
        )
        chapter_ids = sorted(
            {anchors[item].chapter_id for item in anchor_ids},
            key=lambda item: next(
                chapter.source_order for chapter in chapter_lookup.values() if chapter.chapter_id == item
            ),
        )
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list):
            raise LiteraryEngineError("entity.aliases must be a list")
        canonical_name = _text(row, "canonical_name", "entity")
        alias_values = tuple(dict.fromkeys([canonical_name, *(str(item) for item in aliases if isinstance(item, str) and item.strip())]))
        source_ids = row.get("source_ids", [])
        if not isinstance(source_ids, list):
            raise LiteraryEngineError("entity.source_ids must be a list")
        entities.append(
            LiteraryEntity(
                ENTITY_SCHEMA_VERSION,
                entity_identifier,
                canonical_name,
                alias_values,
                str(row.get("entity_type", "unknown")) if str(row.get("entity_type", "unknown")) in {
                    "person", "faction", "ability", "place", "item", "event", "concept", "species", "unknown"
                } else "unknown",
                chapter_ids[0] if chapter_ids else None,
                chapter_ids[-1] if chapter_ids else None,
                tuple(str(item) for item in source_ids if isinstance(item, str)),
                anchor_ids,
                tuple(
                    item.assertion_id
                    for item in assertions
                    if item.predicate == "alias"
                    and entity_identifier in {item.subject_entity_id, item.object_entity_id}
                ),
                "accepted",
            )
        )
    return sorted(anchors.values(), key=lambda item: (item.evidence_start, item.anchor_id)), entities, assertions, fact_anchor_by_id


def _load_annotations(path: Path | None) -> tuple[list[object], str | None]:
    if path is None:
        return [], None
    if path.is_symlink() or not path.is_file():
        raise LiteraryEngineError("annotation file must be a safe regular file")
    rows = _load_jsonl(path, "literary annotation")
    records: list[object] = []
    for line_number, row in enumerate(rows, start=1):
        record_type = row.get("record_type")
        payload = row.get("record")
        if not isinstance(record_type, str) or not isinstance(payload, dict):
            raise LiteraryEngineError(
                f"literary annotation line {line_number} requires record_type and record object"
            )
        try:
            records.append(record_from_dict(record_type, payload))
        except LiteraryModelError as exc:
            raise LiteraryEngineError(f"invalid annotation line {line_number}: {exc}") from exc
    return records, sha256_file(path)


def _merge_annotations(
    source_text: str,
    chapters: list[ChapterRecord],
    anchors: list[EvidenceAnchor],
    entities: list[LiteraryEntity],
    assertions: list[KnowledgeAssertion],
    annotations: Sequence[object],
) -> tuple[list[ChapterRecord], list[EvidenceAnchor], list[LiteraryEntity], list[KnowledgeAssertion], list[RelationshipInterval], list[LiteraryEvent], list[RevisionRecord]]:
    relationships: list[RelationshipInterval] = []
    events: list[LiteraryEvent] = []
    revisions: list[RevisionRecord] = []
    collections: dict[type, list[object]] = {
        ChapterRecord: chapters,
        EvidenceAnchor: anchors,
        LiteraryEntity: entities,
        KnowledgeAssertion: assertions,
        RelationshipInterval: relationships,
        LiteraryEvent: events,
        RevisionRecord: revisions,
    }
    for record in annotations:
        collection = collections.get(type(record))
        if collection is None:
            raise LiteraryEngineError(f"unsupported annotation class: {type(record).__name__}")
        collection.append(record)

    def unique(records: Sequence[object], key: str, label: str) -> dict[str, object]:
        result: dict[str, object] = {}
        for record in records:
            identifier = getattr(record, key)
            if identifier in result:
                raise LiteraryEngineError(f"duplicate {label} identifier: {identifier}")
            result[identifier] = record
        return result

    chapter_map = unique(chapters, "chapter_id", "chapter")
    anchor_map = unique(anchors, "anchor_id", "evidence anchor")
    entity_map = unique(entities, "entity_id", "entity")
    assertion_map = unique(assertions, "assertion_id", "assertion")
    unique(relationships, "relationship_id", "relationship")
    unique(events, "event_id", "event")
    unique(revisions, "revision_id", "revision")

    for anchor in anchors:
        if anchor.chapter_id not in chapter_map:
            raise LiteraryEngineError("evidence anchor references an unknown chapter")
        chapter = chapter_map[anchor.chapter_id]
        if not isinstance(chapter, ChapterRecord):
            raise LiteraryEngineError("chapter registry contains an invalid record")
        if not chapter.start_char <= anchor.evidence_start < anchor.evidence_end <= chapter.end_char:
            raise LiteraryEngineError("evidence anchor span is outside its chapter")
        if anchor.source_sha256 != chapter.source_sha256 or anchor.unit_content_sha256 != chapter.content_sha256:
            raise LiteraryEngineError("evidence anchor hash binding differs from chapter")
        if source_text[anchor.evidence_start:anchor.evidence_end] != anchor.evidence_text:
            raise LiteraryEngineError("evidence anchor text differs from the bound source span")
        if anchor.source_status != "clean" and anchor.evidence_role in {"direct_fact", "direct_dialogue"}:
            raise LiteraryEngineError("direct evidence cannot come from contaminated or review-only material")

    for entity in entities:
        for anchor_id in entity.mention_anchor_ids:
            if anchor_id not in anchor_map:
                raise LiteraryEngineError("entity references an unknown mention anchor")
        for assertion_identifier in entity.identity_basis_assertion_ids:
            if assertion_identifier not in assertion_map:
                raise LiteraryEngineError("entity references an unknown identity assertion")

    for assertion in assertions:
        for anchor_id in assertion.evidence_anchor_ids:
            if anchor_id not in anchor_map:
                raise LiteraryEngineError("assertion references an unknown evidence anchor")
        supports: list[KnowledgeAssertion] = []
        for identifier in assertion.supporting_assertion_ids:
            item = assertion_map.get(identifier)
            if not isinstance(item, KnowledgeAssertion):
                raise LiteraryEngineError("assertion references an unknown supporting assertion")
            if item.assertion_id == assertion.assertion_id:
                raise LiteraryEngineError("assertion cannot support itself")
            supports.append(item)
        if assertion.tier == "B" and any(item.tier != "A" for item in supports):
            raise LiteraryEngineError("tier B synthesis may cite only tier A assertions")
        if assertion.tier == "C" and any(item.tier == "C" for item in supports):
            raise LiteraryEngineError("tier C interpretation cannot be recursively supported by tier C")
        for entity_identifier in (assertion.subject_entity_id, assertion.object_entity_id):
            if entity_identifier is not None and entity_identifier not in entity_map:
                raise LiteraryEngineError("assertion references an unknown entity")
        for chapter_identifier in (assertion.temporal_start_chapter_id, assertion.temporal_end_chapter_id):
            if chapter_identifier is not None and chapter_identifier not in chapter_map:
                raise LiteraryEngineError("assertion references an unknown temporal chapter")

    for relationship in relationships:
        if relationship.subject_entity_id not in entity_map or relationship.object_entity_id not in entity_map:
            raise LiteraryEngineError("relationship references an unknown entity")
        for chapter_identifier in (relationship.start_chapter_id, relationship.end_chapter_id):
            if chapter_identifier is not None and chapter_identifier not in chapter_map:
                raise LiteraryEngineError("relationship references an unknown chapter")
        for anchor_id in relationship.evidence_anchor_ids:
            if anchor_id not in anchor_map:
                raise LiteraryEngineError("relationship references an unknown evidence anchor")
        for assertion_identifier in relationship.change_reason_assertion_ids:
            if assertion_identifier not in assertion_map:
                raise LiteraryEngineError("relationship references an unknown change assertion")

    for event in events:
        for chapter_identifier in (event.start_chapter_id, event.end_chapter_id):
            if chapter_identifier not in chapter_map:
                raise LiteraryEngineError("event references an unknown chapter")
        for entity_identifier in (*event.place_entity_ids, *event.participant_entity_ids):
            if entity_identifier not in entity_map:
                raise LiteraryEngineError("event references an unknown entity")
        for assertion_identifier in (
            *event.cause_assertion_ids,
            *event.process_assertion_ids,
            *event.outcome_assertion_ids,
            *event.consequence_assertion_ids,
            *event.foreshadowing_assertion_ids,
        ):
            if assertion_identifier not in assertion_map:
                raise LiteraryEngineError("event references an unknown assertion")
        for anchor_id in event.evidence_anchor_ids:
            if anchor_id not in anchor_map:
                raise LiteraryEngineError("event references an unknown evidence anchor")

    for revision in revisions:
        if revision.record_type == "assertion" and revision.record_id not in assertion_map:
            raise LiteraryEngineError("revision references an unknown assertion")
        for anchor_id in revision.evidence_anchor_ids:
            if anchor_id not in anchor_map:
                raise LiteraryEngineError("revision references an unknown evidence anchor")

    return (
        sorted(chapters, key=lambda item: (item.source_order, item.chapter_id)),
        sorted(anchors, key=lambda item: (item.evidence_start, item.evidence_end, item.anchor_id)),
        sorted(entities, key=lambda item: item.entity_id),
        sorted(assertions, key=lambda item: item.assertion_id),
        sorted(relationships, key=lambda item: item.relationship_id),
        sorted(events, key=lambda item: item.event_id),
        sorted(revisions, key=lambda item: item.revision_id),
    )


def _create_schema(connection: sqlite3.Connection) -> dict[str, bool]:
    connection.executescript(
        """
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE chapters(
            chapter_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            source_order INTEGER NOT NULL,
            volume_ordinal INTEGER,
            chapter_ordinal INTEGER,
            original_heading TEXT NOT NULL,
            normalized_heading TEXT NOT NULL,
            title TEXT NOT NULL,
            unit_id TEXT NOT NULL UNIQUE,
            start_char INTEGER NOT NULL,
            end_char INTEGER NOT NULL,
            body_start_char INTEGER NOT NULL,
            body_end_char INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            review_status TEXT NOT NULL,
            contamination_status TEXT NOT NULL
        );
        CREATE INDEX chapter_address ON chapters(volume_ordinal, chapter_ordinal, source_order);
        CREATE TABLE evidence_anchors(
            anchor_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            chapter_id TEXT NOT NULL REFERENCES chapters(chapter_id),
            unit_id TEXT NOT NULL,
            volume_ordinal INTEGER,
            chapter_ordinal INTEGER,
            original_heading TEXT NOT NULL,
            normalized_heading TEXT NOT NULL,
            evidence_start INTEGER NOT NULL,
            evidence_end INTEGER NOT NULL,
            evidence_text TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            unit_content_sha256 TEXT NOT NULL,
            evidence_role TEXT NOT NULL,
            source_status TEXT NOT NULL
        );
        CREATE INDEX evidence_span ON evidence_anchors(source_id, evidence_start, evidence_end);
        CREATE TABLE entities(
            entity_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            first_chapter_id TEXT,
            last_chapter_id TEXT,
            review_status TEXT NOT NULL
        );
        CREATE TABLE aliases(
            entity_id TEXT NOT NULL REFERENCES entities(entity_id),
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            is_canonical INTEGER NOT NULL,
            PRIMARY KEY(entity_id, normalized_alias)
        );
        CREATE INDEX alias_lookup ON aliases(normalized_alias);
        CREATE TABLE entity_mentions(
            entity_id TEXT NOT NULL REFERENCES entities(entity_id),
            anchor_id TEXT NOT NULL REFERENCES evidence_anchors(anchor_id),
            PRIMARY KEY(entity_id, anchor_id)
        );
        CREATE TABLE assertions(
            assertion_id TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            assertion_kind TEXT NOT NULL,
            subject_entity_id TEXT,
            subject_text TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_entity_id TEXT,
            object_text TEXT NOT NULL,
            value_json TEXT NOT NULL,
            polarity INTEGER NOT NULL,
            temporal_start_chapter_id TEXT,
            temporal_end_chapter_id TEXT,
            confidence REAL NOT NULL,
            limitations_json TEXT NOT NULL,
            attribution TEXT NOT NULL,
            status TEXT NOT NULL,
            revision INTEGER NOT NULL
        );
        CREATE INDEX assertion_subject ON assertions(subject_entity_id, predicate, tier, status);
        CREATE INDEX assertion_object ON assertions(object_entity_id, predicate, tier, status);
        CREATE TABLE assertion_evidence(
            assertion_id TEXT NOT NULL REFERENCES assertions(assertion_id),
            anchor_id TEXT NOT NULL REFERENCES evidence_anchors(anchor_id),
            PRIMARY KEY(assertion_id, anchor_id)
        );
        CREATE TABLE assertion_support(
            assertion_id TEXT NOT NULL REFERENCES assertions(assertion_id),
            supporting_assertion_id TEXT NOT NULL REFERENCES assertions(assertion_id),
            PRIMARY KEY(assertion_id, supporting_assertion_id)
        );
        CREATE TABLE relationships(
            relationship_id TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            subject_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
            relation_type TEXT NOT NULL,
            object_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
            start_chapter_id TEXT,
            end_chapter_id TEXT,
            start_source_order INTEGER,
            end_source_order INTEGER,
            status TEXT NOT NULL
        );
        CREATE INDEX relationship_time ON relationships(subject_entity_id, object_entity_id, relation_type, start_source_order, end_source_order);
        CREATE TABLE relationship_evidence(
            relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id),
            anchor_id TEXT NOT NULL REFERENCES evidence_anchors(anchor_id),
            PRIMARY KEY(relationship_id, anchor_id)
        );
        CREATE TABLE relationship_reasons(
            relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id),
            assertion_id TEXT NOT NULL REFERENCES assertions(assertion_id),
            PRIMARY KEY(relationship_id, assertion_id)
        );
        CREATE TABLE events(
            event_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            start_chapter_id TEXT NOT NULL REFERENCES chapters(chapter_id),
            end_chapter_id TEXT NOT NULL REFERENCES chapters(chapter_id),
            start_source_order INTEGER NOT NULL,
            end_source_order INTEGER NOT NULL,
            review_status TEXT NOT NULL
        );
        CREATE TABLE event_entities(
            event_id TEXT NOT NULL REFERENCES events(event_id),
            entity_id TEXT NOT NULL REFERENCES entities(entity_id),
            role TEXT NOT NULL,
            PRIMARY KEY(event_id, entity_id, role)
        );
        CREATE TABLE event_assertions(
            event_id TEXT NOT NULL REFERENCES events(event_id),
            assertion_id TEXT NOT NULL REFERENCES assertions(assertion_id),
            component TEXT NOT NULL,
            PRIMARY KEY(event_id, assertion_id, component)
        );
        CREATE TABLE event_evidence(
            event_id TEXT NOT NULL REFERENCES events(event_id),
            anchor_id TEXT NOT NULL REFERENCES evidence_anchors(anchor_id),
            PRIMARY KEY(event_id, anchor_id)
        );
        CREATE TABLE revisions(
            revision_id TEXT PRIMARY KEY,
            record_type TEXT NOT NULL,
            record_id TEXT NOT NULL,
            previous_revision INTEGER,
            new_revision INTEGER NOT NULL,
            reason TEXT NOT NULL,
            superseded_by_record_id TEXT
        );
        CREATE TABLE revision_evidence(
            revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
            anchor_id TEXT NOT NULL REFERENCES evidence_anchors(anchor_id),
            PRIMARY KEY(revision_id, anchor_id)
        );
        """
    )
    capabilities = {"fts5": False, "trigram": False}
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE literary_fts USING fts5(record_type UNINDEXED, record_id UNINDEXED, text, tokenize='trigram')"
        )
        capabilities.update({"fts5": True, "trigram": True})
    except sqlite3.OperationalError:
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE literary_fts USING fts5(record_type UNINDEXED, record_id UNINDEXED, text)"
            )
            capabilities["fts5"] = True
        except sqlite3.OperationalError:
            pass
    return capabilities


def _normalized(value: str) -> str:
    return "".join(value.casefold().split())


def _insert_records(
    connection: sqlite3.Connection,
    chapters: Sequence[ChapterRecord],
    anchors: Sequence[EvidenceAnchor],
    entities: Sequence[LiteraryEntity],
    assertions: Sequence[KnowledgeAssertion],
    relationships: Sequence[RelationshipInterval],
    events: Sequence[LiteraryEvent],
    revisions: Sequence[RevisionRecord],
    *,
    fts5: bool,
) -> None:
    for item in chapters:
        connection.execute(
            "INSERT INTO chapters VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item.chapter_id, item.source_id, item.source_order, item.volume_ordinal,
                item.chapter_ordinal, item.original_heading, item.normalized_heading, item.title,
                item.unit_id, item.start_char, item.end_char, item.body_start_char,
                item.body_end_char, item.content_sha256, item.review_status,
                item.contamination_status,
            ),
        )
        if fts5:
            connection.execute(
                "INSERT INTO literary_fts VALUES(?,?,?)",
                ("chapter", item.chapter_id, " ".join(filter(None, (item.original_heading, item.normalized_heading, item.title)))),
            )
    for item in anchors:
        connection.execute(
            "INSERT INTO evidence_anchors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item.anchor_id, item.source_id, item.chapter_id, item.unit_id,
                item.volume_ordinal, item.chapter_ordinal, item.original_heading,
                item.normalized_heading, item.evidence_start, item.evidence_end,
                item.evidence_text, item.evidence_sha256, item.unit_content_sha256,
                item.evidence_role, item.source_status,
            ),
        )
        if fts5:
            connection.execute("INSERT INTO literary_fts VALUES(?,?,?)", ("evidence", item.anchor_id, item.evidence_text))
    for item in entities:
        connection.execute(
            "INSERT INTO entities VALUES(?,?,?,?,?,?)",
            (
                item.entity_id, item.canonical_name, item.entity_type,
                item.first_chapter_id, item.last_chapter_id, item.review_status,
            ),
        )
        for alias in item.aliases:
            connection.execute(
                "INSERT INTO aliases VALUES(?,?,?,?)",
                (item.entity_id, alias, _normalized(alias), int(alias == item.canonical_name)),
            )
        for anchor_id in item.mention_anchor_ids:
            connection.execute("INSERT INTO entity_mentions VALUES(?,?)", (item.entity_id, anchor_id))
        if fts5:
            connection.execute(
                "INSERT INTO literary_fts VALUES(?,?,?)",
                ("entity", item.entity_id, " ".join(item.aliases)),
            )
    for item in assertions:
        connection.execute(
            "INSERT INTO assertions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item.assertion_id, item.tier, item.assertion_kind,
                item.subject_entity_id, item.subject_text, item.predicate,
                item.object_entity_id, item.object_text, _canonical_json(item.value),
                int(item.polarity), item.temporal_start_chapter_id,
                item.temporal_end_chapter_id, float(item.confidence),
                _canonical_json(list(item.limitations)), item.attribution,
                item.status, item.revision,
            ),
        )
        if fts5:
            text = " ".join(
                filter(
                    None,
                    (
                        item.subject_text,
                        item.predicate,
                        item.object_text,
                        "" if item.value is None else str(item.value),
                        " ".join(item.limitations),
                    ),
                )
            )
            connection.execute("INSERT INTO literary_fts VALUES(?,?,?)", ("assertion", item.assertion_id, text))
    # Insert assertion relations only after every assertion row exists. Derived
    # B/C identifiers are deterministic hashes and do not sort after their A/B
    # supports, so a single-pass insert can violate foreign-key ordering.
    for item in assertions:
        for anchor_id in item.evidence_anchor_ids:
            connection.execute("INSERT INTO assertion_evidence VALUES(?,?)", (item.assertion_id, anchor_id))
        for support_id in item.supporting_assertion_ids:
            connection.execute("INSERT INTO assertion_support VALUES(?,?)", (item.assertion_id, support_id))
    for item in relationships:
        connection.execute(
            "INSERT INTO relationships VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                item.relationship_id, item.tier, item.subject_entity_id,
                item.relation_type, item.object_entity_id, item.start_chapter_id,
                item.end_chapter_id, item.start_source_order, item.end_source_order,
                item.status,
            ),
        )
        for anchor_id in item.evidence_anchor_ids:
            connection.execute("INSERT INTO relationship_evidence VALUES(?,?)", (item.relationship_id, anchor_id))
        for assertion_identifier in item.change_reason_assertion_ids:
            connection.execute("INSERT INTO relationship_reasons VALUES(?,?)", (item.relationship_id, assertion_identifier))
    for item in events:
        connection.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?)",
            (
                item.event_id, item.canonical_name, item.event_type,
                item.start_chapter_id, item.end_chapter_id,
                item.start_source_order, item.end_source_order,
                item.review_status,
            ),
        )
        for entity_identifier in item.place_entity_ids:
            connection.execute("INSERT INTO event_entities VALUES(?,?,?)", (item.event_id, entity_identifier, "place"))
        for entity_identifier in item.participant_entity_ids:
            connection.execute("INSERT INTO event_entities VALUES(?,?,?)", (item.event_id, entity_identifier, "participant"))
        component_sets = (
            ("cause", item.cause_assertion_ids),
            ("process", item.process_assertion_ids),
            ("outcome", item.outcome_assertion_ids),
            ("consequence", item.consequence_assertion_ids),
            ("foreshadowing", item.foreshadowing_assertion_ids),
        )
        for component, identifiers in component_sets:
            for assertion_identifier in identifiers:
                connection.execute(
                    "INSERT INTO event_assertions VALUES(?,?,?)",
                    (item.event_id, assertion_identifier, component),
                )
        for anchor_id in item.evidence_anchor_ids:
            connection.execute("INSERT INTO event_evidence VALUES(?,?)", (item.event_id, anchor_id))
        if fts5:
            connection.execute("INSERT INTO literary_fts VALUES(?,?,?)", ("event", item.event_id, item.canonical_name))
    for item in revisions:
        connection.execute(
            "INSERT INTO revisions VALUES(?,?,?,?,?,?,?)",
            (
                item.revision_id, item.record_type, item.record_id,
                item.previous_revision, item.new_revision, item.reason,
                item.superseded_by_record_id,
            ),
        )
        for anchor_id in item.evidence_anchor_ids:
            connection.execute("INSERT INTO revision_evidence VALUES(?,?)", (item.revision_id, anchor_id))


def _logical_hash(payloads: Mapping[str, bytes], project_id: str, annotation_sha: str | None) -> str:
    logical = {
        "literary_system_version": LITERARY_SYSTEM_VERSION,
        "literary_index_schema_version": LITERARY_INDEX_SCHEMA_VERSION,
        "project_id": project_id,
        "annotation_sha256": annotation_sha,
        "datasets": {name: sha256(data).hexdigest() for name, data in sorted(payloads.items())},
    }
    return sha256(_canonical_json(logical).encode("utf-8")).hexdigest()


def _install(temporary: Path, output: Path, replace: bool) -> None:
    if not output.exists():
        temporary.replace(output)
        return
    if not replace:
        raise LiteraryEngineError(f"literary output already exists: {output}")
    if output.is_symlink() or not output.is_dir():
        raise LiteraryEngineError("existing literary output is unsafe")
    backup = output.with_name(f".{output.name}.backup")
    if backup.exists():
        shutil.rmtree(backup)
    output.replace(backup)
    try:
        temporary.replace(output)
    except Exception:
        if output.exists():
            shutil.rmtree(output, ignore_errors=True)
        backup.replace(output)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def build_literary_engine(
    project_directory: str | Path,
    output_directory: str | Path,
    *,
    annotations_path: str | Path | None = None,
    replace_existing: bool = False,
) -> LiteraryBuildResult:
    """Build a deterministic literary sidecar from one verified TKR project."""

    project_root = Path(project_directory)
    output = Path(output_directory)
    report, source_text, unit_rows, heading_rows, anomaly_rows, mention_rows, entity_rows, fact_rows = _project_inputs(project_root)
    project_id = _text(report, "project_id", "project report")
    source_id = _text(report, "source_id", "project report")
    source_sha = _text(report, "normalized_source_sha256", "project report")
    if sha256(source_text.encode("utf-8")).hexdigest() != source_sha:
        raise LiteraryEngineError("normalized source hash differs from project report")

    chapters, chapter_lookup = _chapters(source_text, unit_rows, heading_rows, anomaly_rows)
    anchors, entities, assertions, _ = _import_base_records(
        source_text, chapter_lookup, mention_rows, entity_rows, fact_rows
    )
    annotations, annotation_sha = _load_annotations(Path(annotations_path) if annotations_path is not None else None)
    chapters, anchors, entities, assertions, relationships, events, revisions = _merge_annotations(
        source_text, chapters, anchors, entities, assertions, annotations
    )

    payloads: dict[str, bytes] = {
        "chapters.jsonl": _jsonl_bytes(chapters),
        "evidence-anchors.jsonl": _jsonl_bytes(anchors),
        "entities.jsonl": _jsonl_bytes(entities),
        "assertions.jsonl": _jsonl_bytes(assertions),
        "relationships.jsonl": _jsonl_bytes(relationships),
        "events.jsonl": _jsonl_bytes(events),
        "revisions.jsonl": _jsonl_bytes(revisions),
    }
    logical_hash = _logical_hash(payloads, project_id, annotation_sha)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        for name, data in payloads.items():
            _write_atomic(temporary / name, data)

        database = temporary / "literary.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA page_size=4096")
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA foreign_keys=ON")
            capabilities = _create_schema(connection)
            _insert_records(
                connection,
                chapters,
                anchors,
                entities,
                assertions,
                relationships,
                events,
                revisions,
                fts5=capabilities["fts5"],
            )
            metadata = {
                "literary_system_version": LITERARY_SYSTEM_VERSION,
                "literary_index_schema_version": LITERARY_INDEX_SCHEMA_VERSION,
                "project_id": project_id,
                "source_id": source_id,
                "source_sha256": source_sha,
                "logical_sha256": logical_hash,
                "annotation_sha256": annotation_sha or "",
                "fts5": str(int(capabilities["fts5"])),
                "trigram": str(int(capabilities["trigram"])),
            }
            connection.executemany("INSERT INTO metadata VALUES(?,?)", sorted(metadata.items()))
            connection.commit()
            connection.execute("VACUUM")
            connection.commit()
        finally:
            connection.close()

        database_hash = sha256_file(database)
        tier_counts = {tier: sum(item.tier == tier for item in assertions) for tier in ("A", "B", "C")}
        addressable = sum(item.chapter_ordinal is not None for item in chapters)
        traced = sum(bool(item.evidence_anchor_ids) for item in assertions)
        traceability = traced / len(assertions) if assertions else 1.0
        address_coverage = addressable / len(chapters) if chapters else 1.0
        result = LiteraryBuildResult(
            "completed",
            LITERARY_SYSTEM_VERSION,
            LITERARY_INDEX_SCHEMA_VERSION,
            project_id,
            source_id,
            source_sha,
            output.as_posix(),
            len(chapters),
            addressable,
            len(anchors),
            len(entities),
            len(assertions),
            tier_counts["A"],
            tier_counts["B"],
            tier_counts["C"],
            len(relationships),
            len(events),
            len(revisions),
            traceability,
            address_coverage,
            logical_hash,
            database_hash,
            annotation_sha,
        )
        report_payload = {
            "schema_version": LITERARY_REPORT_SCHEMA_VERSION,
            **result.to_dict(),
            "fts5_available": capabilities["fts5"],
            "trigram_available": capabilities["trigram"],
            "tier_contract": {
                "A": "explicit source fact with exact evidence",
                "B": "cross-evidence synthesis with at least two A supports",
                "C": "model interpretation with explicit A/B support and attribution",
            },
            "interpretation_may_be_presented_as_source_fact": False,
            "author_intent_may_be_asserted_without_direct_evidence": False,
        }
        _write_atomic(temporary / "literary-report.json", _json_bytes(report_payload))
        manifest_entries = []
        for path in sorted(item for item in temporary.iterdir() if item.is_file()):
            if path.name == "artifact-manifest.json":
                continue
            manifest_entries.append(
                {
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        manifest = {
            "schema_version": LITERARY_MANIFEST_SCHEMA_VERSION,
            "literary_system_version": LITERARY_SYSTEM_VERSION,
            "literary_index_schema_version": LITERARY_INDEX_SCHEMA_VERSION,
            "project_id": project_id,
            "source_id": source_id,
            "source_sha256": source_sha,
            "logical_sha256": logical_hash,
            "database_sha256": database_hash,
            "files": manifest_entries,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_freeze": False,
        }
        _write_atomic(temporary / "artifact-manifest.json", _json_bytes(manifest))
        verification = verify_literary_engine(temporary)
        if not verification.valid:
            raise LiteraryEngineError(
                "new literary sidecar failed verification: " + ",".join(verification.reason_codes)
            )
        _install(temporary, output, replace_existing)
        return result
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _walk_files(root: Path) -> tuple[set[str], list[str]]:
    files: set[str] = set()
    reasons: list[str] = []
    for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        safe: list[str] = []
        for name in sorted(directories):
            path = base / name
            if path.is_symlink():
                reasons.append("SYMLINK_IN_LITERARY_INDEX")
            elif path.is_dir():
                safe.append(name)
            else:
                reasons.append("NON_DIRECTORY_LITERARY_ENTRY")
        directories[:] = safe
        for name in sorted(filenames):
            path = base / name
            if path.is_symlink():
                reasons.append("SYMLINK_IN_LITERARY_INDEX")
            elif not path.is_file():
                reasons.append("NON_REGULAR_LITERARY_FILE")
            else:
                files.add(path.relative_to(root).as_posix())
    return files, reasons


def verify_literary_engine(output_directory: str | Path) -> LiteraryVerification:
    root = Path(output_directory)
    reasons: list[str] = []
    checked = 0
    project_id = source_id = logical_hash = database_hash = ""
    try:
        if root.is_symlink() or not root.is_dir():
            raise LiteraryEngineError("literary sidecar root is unsafe")
        actual_files, walk_reasons = _walk_files(root)
        reasons.extend(walk_reasons)
        if actual_files != _ALLOWED_FILES:
            if actual_files - _ALLOWED_FILES:
                reasons.append("UNEXPECTED_LITERARY_FILE")
            if _ALLOWED_FILES - actual_files:
                reasons.append("LITERARY_FILE_MISSING")
        manifest = _load_object(root / "artifact-manifest.json", "literary manifest")
        report = _load_object(root / "literary-report.json", "literary report")
        project_id = str(manifest.get("project_id", ""))
        source_id = str(manifest.get("source_id", ""))
        logical_hash = str(manifest.get("logical_sha256", ""))
        database_hash = str(manifest.get("database_sha256", ""))
        if manifest.get("schema_version") != LITERARY_MANIFEST_SCHEMA_VERSION:
            reasons.append("LITERARY_MANIFEST_SCHEMA_MISMATCH")
        if report.get("schema_version") != LITERARY_REPORT_SCHEMA_VERSION:
            reasons.append("LITERARY_REPORT_SCHEMA_MISMATCH")
        if manifest.get("literary_system_version") != LITERARY_SYSTEM_VERSION or report.get("literary_system_version") != LITERARY_SYSTEM_VERSION:
            reasons.append("LITERARY_SYSTEM_VERSION_MISMATCH")
        if manifest.get("literary_index_schema_version") != LITERARY_INDEX_SCHEMA_VERSION or report.get("literary_index_schema_version") != LITERARY_INDEX_SCHEMA_VERSION:
            reasons.append("LITERARY_INDEX_SCHEMA_MISMATCH")
        if manifest.get("project_id") != report.get("project_id") or manifest.get("source_id") != report.get("source_id"):
            reasons.append("LITERARY_REPORT_BINDING_MISMATCH")
        for payload in (manifest, report):
            if payload.get("project_acceptance_performed") or payload.get("may_accept_project") or payload.get("may_freeze"):
                reasons.append("ILLEGAL_LITERARY_ACCEPTANCE_AUTHORITY")
        entries = manifest.get("files")
        if not isinstance(entries, list):
            reasons.append("LITERARY_MANIFEST_FILES_INVALID")
            entries = []
        expected_files: set[str] = {"artifact-manifest.json"}
        for entry in entries:
            if not isinstance(entry, dict):
                reasons.append("LITERARY_MANIFEST_RECORD_INVALID")
                continue
            relative = _safe_relative(entry.get("path"))
            if relative is None or relative in expected_files:
                reasons.append("LITERARY_MANIFEST_PATH_INVALID")
                continue
            expected_files.add(relative)
            path = root / relative
            if not path.is_file() or path.is_symlink():
                reasons.append("DECLARED_LITERARY_FILE_MISSING")
                continue
            checked += 1
            if entry.get("size_bytes") != path.stat().st_size:
                reasons.append("LITERARY_FILE_SIZE_MISMATCH")
            if entry.get("sha256") != sha256_file(path):
                reasons.append("LITERARY_FILE_HASH_MISMATCH")
        if expected_files != actual_files:
            reasons.append("LITERARY_MANIFEST_MEMBERSHIP_MISMATCH")

        dataset_payloads = {name: (root / name).read_bytes() for name in _DATASETS}
        annotation_sha = report.get("annotation_sha256")
        if annotation_sha is not None and not isinstance(annotation_sha, str):
            reasons.append("LITERARY_ANNOTATION_HASH_INVALID")
            annotation_sha = None
        expected_logical = _logical_hash(dataset_payloads, project_id, annotation_sha)
        if logical_hash != expected_logical or report.get("logical_sha256") != expected_logical:
            reasons.append("LITERARY_LOGICAL_HASH_MISMATCH")
        actual_database_hash = sha256_file(root / "literary.sqlite")
        if database_hash != actual_database_hash or report.get("database_sha256") != actual_database_hash:
            reasons.append("LITERARY_DATABASE_HASH_MISMATCH")

        # Parse every typed artifact before opening SQLite.  Verification must
        # compare the two stores, not merely prove that each store is internally
        # self-consistent in isolation.
        type_map = {
            "chapters.jsonl": ("chapter", "chapter_id", "chapters", "chapter_id"),
            "evidence-anchors.jsonl": ("evidence", "anchor_id", "evidence_anchors", "anchor_id"),
            "entities.jsonl": ("entity", "entity_id", "entities", "entity_id"),
            "assertions.jsonl": ("assertion", "assertion_id", "assertions", "assertion_id"),
            "relationships.jsonl": ("relationship", "relationship_id", "relationships", "relationship_id"),
            "events.jsonl": ("event", "event_id", "events", "event_id"),
            "revisions.jsonl": ("revision", "revision_id", "revisions", "revision_id"),
        }
        typed_rows: dict[str, list[dict[str, object]]] = {}
        for name, (record_type, _, _, _) in type_map.items():
            rows = _load_jsonl(root / name, name)
            typed_rows[name] = rows
            for row in rows:
                try:
                    record_from_dict(record_type, row)
                except LiteraryModelError as exc:
                    reasons.append(f"LITERARY_TYPED_RECORD_INVALID:{name}:{type(exc).__name__}")
                    break

        connection = sqlite3.connect(f"file:{root / 'literary.sqlite'}?mode=ro", uri=True)
        try:
            metadata = {str(key): str(value) for key, value in connection.execute("SELECT key,value FROM metadata")}
            if metadata.get("literary_system_version") != LITERARY_SYSTEM_VERSION:
                reasons.append("LITERARY_DATABASE_SYSTEM_MISMATCH")
            if metadata.get("literary_index_schema_version") != LITERARY_INDEX_SCHEMA_VERSION:
                reasons.append("LITERARY_DATABASE_SCHEMA_MISMATCH")
            if metadata.get("project_id") != project_id or metadata.get("source_id") != source_id:
                reasons.append("LITERARY_DATABASE_PROJECT_BINDING_MISMATCH")
            if metadata.get("logical_sha256") != expected_logical:
                reasons.append("LITERARY_DATABASE_LOGICAL_HASH_MISMATCH")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                reasons.append("LITERARY_SQLITE_INTEGRITY_FAILED")
            foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign:
                reasons.append("LITERARY_SQLITE_FOREIGN_KEY_FAILED")

            for name, (_, json_id_key, table, database_id_column) in type_map.items():
                json_ids = [row.get(json_id_key) for row in typed_rows[name]]
                if any(not isinstance(item, str) or not item for item in json_ids):
                    reasons.append(f"LITERARY_JSON_IDENTIFIER_INVALID:{name}")
                    continue
                if len(json_ids) != len(set(json_ids)):
                    reasons.append(f"LITERARY_JSON_IDENTIFIER_DUPLICATE:{name}")
                database_ids = [
                    str(row[0])
                    for row in connection.execute(
                        f"SELECT {database_id_column} FROM {table} ORDER BY {database_id_column}"
                    )
                ]
                if sorted(json_ids) != database_ids:
                    reasons.append(f"LITERARY_JSON_SQLITE_IDENTIFIER_MISMATCH:{name}")

            expected_counts = {
                "chapter_count": len(typed_rows["chapters.jsonl"]),
                "evidence_anchor_count": len(typed_rows["evidence-anchors.jsonl"]),
                "entity_count": len(typed_rows["entities.jsonl"]),
                "assertion_count": len(typed_rows["assertions.jsonl"]),
                "relationship_count": len(typed_rows["relationships.jsonl"]),
                "event_count": len(typed_rows["events.jsonl"]),
                "revision_count": len(typed_rows["revisions.jsonl"]),
                "tier_a_count": sum(row.get("tier") == "A" for row in typed_rows["assertions.jsonl"]),
                "tier_b_count": sum(row.get("tier") == "B" for row in typed_rows["assertions.jsonl"]),
                "tier_c_count": sum(row.get("tier") == "C" for row in typed_rows["assertions.jsonl"]),
            }
            for key, expected in expected_counts.items():
                if report.get(key) != expected:
                    reasons.append(f"LITERARY_REPORT_COUNT_MISMATCH:{key}")

            addressable = sum(
                isinstance(row.get("chapter_ordinal"), int)
                and not isinstance(row.get("chapter_ordinal"), bool)
                for row in typed_rows["chapters.jsonl"]
            )
            if report.get("addressable_chapter_count") != addressable:
                reasons.append("LITERARY_REPORT_COUNT_MISMATCH:addressable_chapter_count")
            expected_coverage = addressable / expected_counts["chapter_count"] if expected_counts["chapter_count"] else 1.0
            if report.get("chapter_address_coverage") != expected_coverage:
                reasons.append("LITERARY_REPORT_CHAPTER_COVERAGE_MISMATCH")
            traced = sum(bool(row.get("evidence_anchor_ids")) for row in typed_rows["assertions.jsonl"])
            expected_traceability = traced / expected_counts["assertion_count"] if expected_counts["assertion_count"] else 1.0
            if report.get("evidence_traceability_rate") != expected_traceability:
                reasons.append("LITERARY_REPORT_TRACEABILITY_MISMATCH")
        finally:
            connection.close()
    except Exception as exc:
        reasons.extend(("LITERARY_VERIFICATION_EXCEPTION", type(exc).__name__))

    unique = tuple(dict.fromkeys(reasons))
    return LiteraryVerification(
        "verified" if not unique else "rejected",
        not unique,
        unique if unique else (
            "LITERARY_FILE_HASH_CHAIN_VERIFIED",
            "LITERARY_SQLITE_INTEGRITY_VERIFIED",
            "LITERARY_TYPED_RECORDS_VERIFIED",
            "EPISTEMIC_TIER_CONTRACT_VERIFIED",
        ),
        checked,
        project_id,
        source_id,
        logical_hash,
        database_hash,
    )


__all__ = [
    "LITERARY_INDEX_SCHEMA_VERSION",
    "LITERARY_MANIFEST_SCHEMA_VERSION",
    "LITERARY_REPORT_SCHEMA_VERSION",
    "LiteraryBuildResult",
    "LiteraryEngineError",
    "LiteraryVerification",
    "build_literary_engine",
    "verify_literary_engine",
]
