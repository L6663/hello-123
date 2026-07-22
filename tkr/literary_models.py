"""Typed contracts for the Stage 7 literary knowledge engine.

The literary layer is deliberately stricter than a prose summary.  Every item is
classified as one of three epistemic tiers:

* A -- explicit source fact, supported by exact source evidence;
* B -- cross-evidence synthesis, supported by multiple A facts/evidence anchors;
* C -- literary interpretation, explicitly attributed to the model and supported
  by A/B material without being presented as authorial fact.

No tier may silently upgrade itself.  Identifiers are deterministic so that
incremental rebuilds and regression checks can compare exact artifacts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Final, Iterable, Mapping, Sequence

LITERARY_SYSTEM_VERSION: Final = "tkr-literary-v1"
EVIDENCE_ANCHOR_SCHEMA_VERSION: Final = "tkr-literary-evidence-anchor-v1"
CHAPTER_SCHEMA_VERSION: Final = "tkr-literary-chapter-v1"
ENTITY_SCHEMA_VERSION: Final = "tkr-literary-entity-v1"
ASSERTION_SCHEMA_VERSION: Final = "tkr-literary-assertion-v1"
RELATIONSHIP_SCHEMA_VERSION: Final = "tkr-literary-relationship-v1"
EVENT_SCHEMA_VERSION: Final = "tkr-literary-event-v1"
REVISION_SCHEMA_VERSION: Final = "tkr-literary-revision-v1"

EPISTEMIC_TIERS: Final = frozenset({"A", "B", "C"})
ENTITY_TYPES: Final = frozenset(
    {
        "person",
        "faction",
        "ability",
        "place",
        "item",
        "event",
        "concept",
        "species",
        "unknown",
    }
)
ASSERTION_KINDS: Final = frozenset(
    {
        "fact",
        "synthesis",
        "interpretation",
        "relationship",
        "event_component",
        "ability_property",
        "place_property",
        "identity",
    }
)
ASSERTION_STATUSES: Final = frozenset(
    {"active", "superseded", "contested", "retracted", "needs_review"}
)
RELATIONSHIP_STATUSES: Final = frozenset(
    {"active", "ended", "contested", "needs_review"}
)


class LiteraryModelError(ValueError):
    """Raised when a literary knowledge record violates its evidence contract."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, *parts: object, length: int = 32) -> str:
    payload = "\0".join(_canonical_json(part) for part in parts)
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:length]


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise LiteraryModelError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise LiteraryModelError(f"{name} must be non-empty")
    return cleaned


def _require_non_negative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LiteraryModelError(f"{name} must be a non-negative integer")
    return value


def _tuple_text(values: Iterable[object], name: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        text = _require_text(value, name)
        if text not in result:
            result.append(text)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ChapterRecord:
    schema_version: str
    chapter_id: str
    source_id: str
    source_sha256: str
    unit_id: str
    unit_type: str
    source_order: int
    volume_ordinal: int | None
    chapter_ordinal: int | None
    original_heading: str
    normalized_heading: str
    title: str
    start_char: int
    end_char: int
    body_start_char: int
    body_end_char: int
    content_sha256: str
    structure_confidence: str
    review_status: str
    contamination_status: str

    def __post_init__(self) -> None:
        if self.schema_version != CHAPTER_SCHEMA_VERSION:
            raise LiteraryModelError("chapter schema version mismatch")
        for name in ("chapter_id", "source_id", "source_sha256", "unit_id", "unit_type", "content_sha256"):
            _require_text(getattr(self, name), name)
        _require_non_negative(self.source_order, "source_order")
        start = _require_non_negative(self.start_char, "start_char")
        end = _require_non_negative(self.end_char, "end_char")
        body_start = _require_non_negative(self.body_start_char, "body_start_char")
        body_end = _require_non_negative(self.body_end_char, "body_end_char")
        if not start < end or not start <= body_start <= body_end <= end:
            raise LiteraryModelError("chapter spans are inconsistent")
        for name in ("volume_ordinal", "chapter_ordinal"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
                raise LiteraryModelError(f"{name} must be a positive integer or null")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceAnchor:
    schema_version: str
    anchor_id: str
    source_id: str
    source_sha256: str
    unit_id: str
    chapter_id: str
    volume_ordinal: int | None
    chapter_ordinal: int | None
    original_heading: str
    normalized_heading: str
    evidence_start: int
    evidence_end: int
    evidence_text: str
    evidence_sha256: str
    unit_content_sha256: str
    evidence_role: str
    source_status: str

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_ANCHOR_SCHEMA_VERSION:
            raise LiteraryModelError("evidence anchor schema version mismatch")
        for name in (
            "anchor_id",
            "source_id",
            "source_sha256",
            "unit_id",
            "chapter_id",
            "evidence_text",
            "evidence_sha256",
            "unit_content_sha256",
            "evidence_role",
            "source_status",
        ):
            _require_text(getattr(self, name), name)
        start = _require_non_negative(self.evidence_start, "evidence_start")
        end = _require_non_negative(self.evidence_end, "evidence_end")
        if end <= start:
            raise LiteraryModelError("evidence_end must be greater than evidence_start")
        if sha256(self.evidence_text.encode("utf-8")).hexdigest() != self.evidence_sha256:
            raise LiteraryModelError("evidence text SHA-256 mismatch")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LiteraryEntity:
    schema_version: str
    entity_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    entity_type: str
    first_chapter_id: str | None
    last_chapter_id: str | None
    source_ids: tuple[str, ...]
    mention_anchor_ids: tuple[str, ...]
    identity_basis_assertion_ids: tuple[str, ...]
    review_status: str = "accepted"

    def __post_init__(self) -> None:
        if self.schema_version != ENTITY_SCHEMA_VERSION:
            raise LiteraryModelError("entity schema version mismatch")
        _require_text(self.entity_id, "entity_id")
        canonical = _require_text(self.canonical_name, "canonical_name")
        if self.entity_type not in ENTITY_TYPES:
            raise LiteraryModelError(f"unsupported entity_type: {self.entity_type}")
        aliases = _tuple_text(self.aliases, "alias")
        if canonical not in aliases:
            raise LiteraryModelError("canonical_name must be present in aliases")
        if len(aliases) != len(self.aliases):
            raise LiteraryModelError("entity aliases must be unique")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("aliases", "source_ids", "mention_anchor_ids", "identity_basis_assertion_ids"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class KnowledgeAssertion:
    schema_version: str
    assertion_id: str
    tier: str
    assertion_kind: str
    subject_entity_id: str | None
    subject_text: str
    predicate: str
    object_entity_id: str | None
    object_text: str
    value: object
    polarity: bool
    temporal_start_chapter_id: str | None
    temporal_end_chapter_id: str | None
    confidence: float
    evidence_anchor_ids: tuple[str, ...]
    supporting_assertion_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    attribution: str
    status: str
    revision: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != ASSERTION_SCHEMA_VERSION:
            raise LiteraryModelError("assertion schema version mismatch")
        _require_text(self.assertion_id, "assertion_id")
        if self.tier not in EPISTEMIC_TIERS:
            raise LiteraryModelError(f"unsupported epistemic tier: {self.tier}")
        if self.assertion_kind not in ASSERTION_KINDS:
            raise LiteraryModelError(f"unsupported assertion_kind: {self.assertion_kind}")
        _require_text(self.subject_text, "subject_text")
        _require_text(self.predicate, "predicate")
        if not isinstance(self.polarity, bool):
            raise LiteraryModelError("polarity must be boolean")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise LiteraryModelError("confidence must be numeric")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise LiteraryModelError("confidence must be between 0 and 1")
        if self.status not in ASSERTION_STATUSES:
            raise LiteraryModelError(f"unsupported assertion status: {self.status}")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision <= 0:
            raise LiteraryModelError("revision must be a positive integer")
        anchors = _tuple_text(self.evidence_anchor_ids, "evidence_anchor_id")
        supports = _tuple_text(self.supporting_assertion_ids, "supporting_assertion_id")
        if len(anchors) != len(self.evidence_anchor_ids) or len(supports) != len(self.supporting_assertion_ids):
            raise LiteraryModelError("assertion evidence/support identifiers must be unique")

        if self.tier == "A":
            if not anchors:
                raise LiteraryModelError("tier A assertions require exact evidence")
            if self.assertion_kind in {"synthesis", "interpretation"}:
                raise LiteraryModelError("tier A assertions cannot be synthesis or interpretation")
            if self.attribution not in {"source_explicit", "source_direct_event", "source_direct_dialogue"}:
                raise LiteraryModelError("tier A attribution must identify direct source support")
        elif self.tier == "B":
            if self.assertion_kind == "interpretation":
                raise LiteraryModelError("tier B assertions cannot be literary interpretation")
            if len(anchors) < 2 and len(supports) < 2:
                raise LiteraryModelError("tier B assertions require at least two independent supports")
            if self.attribution != "cross_evidence_synthesis":
                raise LiteraryModelError("tier B attribution must be cross_evidence_synthesis")
        else:
            if self.assertion_kind != "interpretation":
                raise LiteraryModelError("tier C assertions must use assertion_kind=interpretation")
            if not anchors and not supports:
                raise LiteraryModelError("tier C interpretation requires explicit supporting material")
            if self.attribution != "model_interpretation":
                raise LiteraryModelError("tier C attribution must be model_interpretation")
            if self.predicate in {"author_intended", "author_definitively_meant"}:
                raise LiteraryModelError("model interpretation cannot assert definitive author intent")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("evidence_anchor_ids", "supporting_assertion_ids", "limitations"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class RelationshipInterval:
    schema_version: str
    relationship_id: str
    tier: str
    subject_entity_id: str
    relation_type: str
    object_entity_id: str
    start_chapter_id: str | None
    end_chapter_id: str | None
    start_source_order: int | None
    end_source_order: int | None
    change_reason_assertion_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != RELATIONSHIP_SCHEMA_VERSION:
            raise LiteraryModelError("relationship schema version mismatch")
        if self.tier not in EPISTEMIC_TIERS:
            raise LiteraryModelError("relationship tier must be A, B, or C")
        for name in ("relationship_id", "subject_entity_id", "relation_type", "object_entity_id"):
            _require_text(getattr(self, name), name)
        if self.subject_entity_id == self.object_entity_id:
            raise LiteraryModelError("relationship endpoints must be different entities")
        if self.status not in RELATIONSHIP_STATUSES:
            raise LiteraryModelError(f"unsupported relationship status: {self.status}")
        if self.start_source_order is not None:
            _require_non_negative(self.start_source_order, "start_source_order")
        if self.end_source_order is not None:
            _require_non_negative(self.end_source_order, "end_source_order")
        if (
            self.start_source_order is not None
            and self.end_source_order is not None
            and self.end_source_order < self.start_source_order
        ):
            raise LiteraryModelError("relationship end precedes start")
        if self.tier == "A" and not self.evidence_anchor_ids:
            raise LiteraryModelError("tier A relationships require exact evidence")
        if self.tier in {"B", "C"} and not (self.evidence_anchor_ids or self.change_reason_assertion_ids):
            raise LiteraryModelError("derived relationships require supporting material")

    def active_at(self, source_order: int) -> bool:
        _require_non_negative(source_order, "source_order")
        if self.start_source_order is not None and source_order < self.start_source_order:
            return False
        if self.end_source_order is not None and source_order > self.end_source_order:
            return False
        return self.status in {"active", "ended"}

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["change_reason_assertion_ids"] = list(self.change_reason_assertion_ids)
        payload["evidence_anchor_ids"] = list(self.evidence_anchor_ids)
        return payload


@dataclass(frozen=True, slots=True)
class LiteraryEvent:
    schema_version: str
    event_id: str
    canonical_name: str
    event_type: str
    start_chapter_id: str
    end_chapter_id: str
    start_source_order: int
    end_source_order: int
    place_entity_ids: tuple[str, ...]
    participant_entity_ids: tuple[str, ...]
    cause_assertion_ids: tuple[str, ...]
    process_assertion_ids: tuple[str, ...]
    outcome_assertion_ids: tuple[str, ...]
    consequence_assertion_ids: tuple[str, ...]
    foreshadowing_assertion_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    review_status: str

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_SCHEMA_VERSION:
            raise LiteraryModelError("event schema version mismatch")
        for name in ("event_id", "canonical_name", "event_type", "start_chapter_id", "end_chapter_id"):
            _require_text(getattr(self, name), name)
        start = _require_non_negative(self.start_source_order, "start_source_order")
        end = _require_non_negative(self.end_source_order, "end_source_order")
        if end < start:
            raise LiteraryModelError("event end precedes start")
        support_count = sum(
            len(getattr(self, name))
            for name in (
                "cause_assertion_ids",
                "process_assertion_ids",
                "outcome_assertion_ids",
                "consequence_assertion_ids",
                "foreshadowing_assertion_ids",
            )
        )
        if support_count == 0 or not self.evidence_anchor_ids:
            raise LiteraryModelError("event requires assertions and evidence")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in (
            "place_entity_ids",
            "participant_entity_ids",
            "cause_assertion_ids",
            "process_assertion_ids",
            "outcome_assertion_ids",
            "consequence_assertion_ids",
            "foreshadowing_assertion_ids",
            "evidence_anchor_ids",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    schema_version: str
    revision_id: str
    record_type: str
    record_id: str
    previous_revision: int | None
    new_revision: int
    reason: str
    superseded_by_record_id: str | None
    evidence_anchor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != REVISION_SCHEMA_VERSION:
            raise LiteraryModelError("revision schema version mismatch")
        for name in ("revision_id", "record_type", "record_id", "reason"):
            _require_text(getattr(self, name), name)
        if self.previous_revision is not None and (
            isinstance(self.previous_revision, bool)
            or not isinstance(self.previous_revision, int)
            or self.previous_revision <= 0
        ):
            raise LiteraryModelError("previous_revision must be a positive integer or null")
        if isinstance(self.new_revision, bool) or not isinstance(self.new_revision, int) or self.new_revision <= 0:
            raise LiteraryModelError("new_revision must be a positive integer")
        if self.previous_revision is not None and self.new_revision <= self.previous_revision:
            raise LiteraryModelError("new revision must exceed previous revision")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evidence_anchor_ids"] = list(self.evidence_anchor_ids)
        return payload


def assertion_id(
    tier: str,
    assertion_kind: str,
    subject_text: str,
    predicate: str,
    object_text: str,
    value: object,
    polarity: bool,
    evidence_anchor_ids: Sequence[str],
    supporting_assertion_ids: Sequence[str],
) -> str:
    return stable_id(
        "las_",
        ASSERTION_SCHEMA_VERSION,
        tier,
        assertion_kind,
        subject_text,
        predicate,
        object_text,
        value,
        polarity,
        sorted(evidence_anchor_ids),
        sorted(supporting_assertion_ids),
    )


def evidence_anchor_id(
    source_sha256: str,
    unit_id: str,
    start: int,
    end: int,
    evidence_sha256: str,
) -> str:
    return stable_id(
        "lea_",
        EVIDENCE_ANCHOR_SCHEMA_VERSION,
        source_sha256,
        unit_id,
        start,
        end,
        evidence_sha256,
    )


def chapter_id(source_sha256: str, unit_id: str, source_order: int, content_sha256: str) -> str:
    return stable_id(
        "lch_",
        CHAPTER_SCHEMA_VERSION,
        source_sha256,
        unit_id,
        source_order,
        content_sha256,
    )


def entity_id(entity_type: str, canonical_name: str, source_ids: Sequence[str]) -> str:
    return stable_id(
        "len_",
        ENTITY_SCHEMA_VERSION,
        entity_type,
        canonical_name,
        sorted(source_ids),
    )


def relationship_id(
    subject_entity_id: str,
    relation_type: str,
    object_entity_id: str,
    start_chapter_id: str | None,
    end_chapter_id: str | None,
    tier: str,
) -> str:
    return stable_id(
        "lre_",
        RELATIONSHIP_SCHEMA_VERSION,
        subject_entity_id,
        relation_type,
        object_entity_id,
        start_chapter_id,
        end_chapter_id,
        tier,
    )


def event_id(canonical_name: str, start_chapter_id: str, end_chapter_id: str) -> str:
    return stable_id("lev_", EVENT_SCHEMA_VERSION, canonical_name, start_chapter_id, end_chapter_id)


def record_from_dict(record_type: str, payload: Mapping[str, object]):
    """Load a typed Stage 7 record from a JSON mapping.

    The loader deliberately accepts only known fields through the dataclass
    constructor; unexpected keys therefore fail closed with ``TypeError``.
    """

    data = dict(payload)
    tuple_fields: dict[str, tuple[str, ...]] = {
        "entity": ("aliases", "source_ids", "mention_anchor_ids", "identity_basis_assertion_ids"),
        "assertion": ("evidence_anchor_ids", "supporting_assertion_ids", "limitations"),
        "relationship": ("change_reason_assertion_ids", "evidence_anchor_ids"),
        "event": (
            "place_entity_ids",
            "participant_entity_ids",
            "cause_assertion_ids",
            "process_assertion_ids",
            "outcome_assertion_ids",
            "consequence_assertion_ids",
            "foreshadowing_assertion_ids",
            "evidence_anchor_ids",
        ),
        "revision": ("evidence_anchor_ids",),
    }
    for field in tuple_fields.get(record_type, ()):
        value = data.get(field, [])
        if not isinstance(value, list):
            raise LiteraryModelError(f"{record_type}.{field} must be a JSON array")
        data[field] = tuple(value)
    classes = {
        "chapter": ChapterRecord,
        "evidence": EvidenceAnchor,
        "entity": LiteraryEntity,
        "assertion": KnowledgeAssertion,
        "relationship": RelationshipInterval,
        "event": LiteraryEvent,
        "revision": RevisionRecord,
    }
    cls = classes.get(record_type)
    if cls is None:
        raise LiteraryModelError(f"unknown literary record type: {record_type}")
    try:
        return cls(**data)
    except TypeError as exc:
        raise LiteraryModelError(f"invalid {record_type} record: {exc}") from exc


__all__ = [
    "ASSERTION_SCHEMA_VERSION",
    "CHAPTER_SCHEMA_VERSION",
    "ENTITY_SCHEMA_VERSION",
    "EPISTEMIC_TIERS",
    "EVIDENCE_ANCHOR_SCHEMA_VERSION",
    "EVENT_SCHEMA_VERSION",
    "LITERARY_SYSTEM_VERSION",
    "RELATIONSHIP_SCHEMA_VERSION",
    "REVISION_SCHEMA_VERSION",
    "ChapterRecord",
    "EvidenceAnchor",
    "KnowledgeAssertion",
    "LiteraryEntity",
    "LiteraryEvent",
    "LiteraryModelError",
    "RelationshipInterval",
    "RevisionRecord",
    "assertion_id",
    "chapter_id",
    "entity_id",
    "event_id",
    "evidence_anchor_id",
    "record_from_dict",
    "relationship_id",
    "stable_id",
]
