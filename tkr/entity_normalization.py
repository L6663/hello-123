"""Evidence-bound entity, alias, homonym, timeline, and conflict normalization.

Phase 4 consumes only Phase 3 ``accepted`` Claim records. Every record is
revalidated against the normalized source and Unit index before it can influence
an entity cluster. The normalizer is deliberately conservative: a repeated name
inside one Unit is treated as local continuity, while cross-Unit identity requires
an accepted alias Claim or a separately cited ``same_as`` link.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import re
from typing import Iterable, Mapping, Sequence
import unicodedata

from .chunking import UnitSpan
from .claim_validation import (
    ClaimCandidate,
    ClaimValidationResult,
    VALIDATOR_VERSION,
    validate_claim,
)

NORMALIZER_VERSION = "tkr-entity-normalizer-v2"

_ASSERTION_BREAK_RE = re.compile(r"[\n。！？!?；;]+")
_EARLIER_RE = re.compile(
    r"(?:原先|原本|最初|起初|此前|之前|曾经|昔日|当初|formerly|initially|previously)",
    re.IGNORECASE,
)
_LATER_RE = re.compile(
    r"(?:后来|随后|之后|此后|最终|如今|现在|现已|改为|变为|later|afterwards|now|eventually)",
    re.IGNORECASE,
)
_IDENTITY_MODAL_RE = re.compile(
    r"(?:据说|传闻|听说|或许|可能|似乎|也许|假如|如果|倘若|若是|"
    r"声称|宣称|谎称|预计|将要|即将|[？?]|"
    r"\breportedly\b|\ballegedly\b|\bperhaps\b|\bmaybe\b|\bif\b|\bclaimed\b|\bwill\b)",
    re.IGNORECASE,
)
_IDENTITY_GAP = r"[^\n。！？!?；;，,:：]{0,32}?"
_IDENTITY_JOIN = r"(?:与|和|跟|及|、|\band\b)"
_SAME_MIDDLE_MARKERS = (
    "正是",
    "就是",
    "即为",
    "其实是",
    "本名是",
    "本名为",
    "真名是",
    "真名为",
    "is the same person as",
    "is the same entity as",
)
_SAME_TAIL_MARKERS = ("是同一人", "为同一人", "是同一个人", "是同一实体", "same person", "same entity")
_DIFFERENT_TAIL_MARKERS = (
    "同名不同人",
    "并非同一人",
    "不是同一人",
    "不是同一个人",
    "并非同一实体",
    "不是同一实体",
    "different people",
    "different persons",
    "different entities",
    "not the same person",
    "not the same entity",
)

_DATE_SCOPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("birth_date", re.compile(r"(?:出生于|生于|born on|date of birth)", re.IGNORECASE)),
    ("death_date", re.compile(r"(?:卒于|死于|逝世于|died on|date of death)", re.IGNORECASE)),
    ("start_date", re.compile(r"(?:始于|开始于|启用于|started on|began on)", re.IGNORECASE)),
    ("end_date", re.compile(r"(?:终于|结束于|截至|ended on|until)", re.IGNORECASE)),
    ("event_date", re.compile(r"(?:发生于|举行于|occurred on|happened on)", re.IGNORECASE)),
)


class EntityNormalizationError(ValueError):
    """Raised when an upstream artifact or identity link is malformed/tampered."""


@dataclass(frozen=True, slots=True)
class AcceptedClaim:
    candidate_line: int
    candidate: ClaimCandidate
    validation: ClaimValidationResult
    evidence: str


@dataclass(frozen=True, slots=True)
class Mention:
    mention_id: str
    claim_result_id: str
    role: str
    surface: str
    normalized_surface: str
    inferred_type: str
    source_id: str
    unit_id: str
    evidence_start: int
    evidence_end: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Entity:
    entity_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    entity_type: str
    mention_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    unit_ids: tuple[str, ...]
    merge_basis: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("aliases", "mention_ids", "source_ids", "unit_ids", "merge_basis"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class Fact:
    fact_id: str
    claim_result_id: str
    claim_type: str
    predicate_scope: str
    subject_entity_id: str | None
    subject: str
    object_entity_id: str | None
    object: str
    value: object
    unit: str
    polarity: bool
    source_id: str
    unit_id: str
    evidence_start: int
    evidence_end: int
    evidence_sha256: str
    temporal_marker: str
    canonical_status: str = "canonical"
    conflict_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["conflict_ids"] = list(self.conflict_ids)
        return payload


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    event_id: str
    fact_id: str
    source_id: str
    unit_id: str
    source_order: int
    evidence_start: int
    evidence_end: int
    event_type: str
    predicate_scope: str
    normalized_date: str | None
    temporal_marker: str
    subject_entity_id: str | None
    object_entity_id: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Conflict:
    conflict_id: str
    conflict_type: str
    severity: str
    status: str
    entity_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    mention_ids: tuple[str, ...]
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["entity_ids"] = list(payload["entity_ids"])
        payload["fact_ids"] = list(payload["fact_ids"])
        payload["mention_ids"] = list(payload["mention_ids"])
        return payload


@dataclass(frozen=True, slots=True)
class AmbiguityGroup:
    ambiguity_id: str
    source_id: str
    normalized_surface: str
    surfaces: tuple[str, ...]
    entity_ids: tuple[str, ...]
    mention_ids: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["surfaces"] = list(payload["surfaces"])
        payload["entity_ids"] = list(payload["entity_ids"])
        payload["mention_ids"] = list(payload["mention_ids"])
        return payload


@dataclass(frozen=True, slots=True)
class IdentityLink:
    relation: str
    left_result_id: str
    left_role: str
    right_result_id: str
    right_role: str
    source_id: str
    unit_id: str
    evidence_start: int
    evidence_end: int
    evidence_text: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "IdentityLink":
        relation = _required_text(payload, "relation").lower()
        if relation not in {"same_as", "different_from"}:
            raise EntityNormalizationError("identity relation must be same_as or different_from")
        left_role = _required_text(payload, "left_role").lower()
        right_role = _required_text(payload, "right_role").lower()
        if left_role not in {"subject", "object"} or right_role not in {"subject", "object"}:
            raise EntityNormalizationError("identity roles must be subject or object")
        return cls(
            relation=relation,
            left_result_id=_required_text(payload, "left_result_id"),
            left_role=left_role,
            right_result_id=_required_text(payload, "right_result_id"),
            right_role=right_role,
            source_id=_required_text(payload, "source_id"),
            unit_id=_required_text(payload, "unit_id"),
            evidence_start=_required_int(payload, "evidence_start"),
            evidence_end=_required_int(payload, "evidence_end"),
            evidence_text=_required_text(payload, "evidence_text"),
        )


@dataclass(frozen=True, slots=True)
class NormalizationBundle:
    mentions: tuple[Mention, ...]
    entities: tuple[Entity, ...]
    facts: tuple[Fact, ...]
    timeline: tuple[TimelineEvent, ...]
    conflicts: tuple[Conflict, ...]
    ambiguity_groups: tuple[AmbiguityGroup, ...]
    report: dict[str, object]


class _UnionFind:
    def __init__(self, mentions: Mapping[str, Mention]) -> None:
        self.parent = {item: item for item in mentions}
        self.members = {item: {item} for item in mentions}
        self.types = {
            item: ({mentions[item].inferred_type} - {"unknown", "entity"}) for item in mentions
        }
        self.sources = {item: {mentions[item].source_id} for item in mentions}
        self.basis = {item: set() for item in mentions}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(
        self,
        left: str,
        right: str,
        *,
        basis: str,
        forbidden_neighbors: Mapping[str, set[str]],
    ) -> tuple[bool, str | None]:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            self.basis[left_root].add(basis)
            return True, None
        if self.sources[left_root] != self.sources[right_root]:
            return False, "CROSS_SOURCE_IDENTITY_MERGE"
        left_types = self.types[left_root]
        right_types = self.types[right_root]
        if left_types and right_types and left_types != right_types:
            return False, "ENTITY_TYPE_CONFLICT"
        left_members = self.members[left_root]
        right_members = self.members[right_root]
        smaller, other = (left_members, right_members) if len(left_members) <= len(right_members) else (right_members, left_members)
        for member in smaller:
            if forbidden_neighbors.get(member, set()).intersection(other):
                return False, "EXPLICIT_DIFFERENT_FROM_CONSTRAINT"
        left_size = len(self.members[left_root])
        right_size = len(self.members[right_root])
        if left_size < right_size or (left_size == right_size and right_root < left_root):
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.members[left_root].update(self.members.pop(right_root))
        self.types[left_root].update(self.types.pop(right_root))
        self.sources[left_root].update(self.sources.pop(right_root))
        self.basis[left_root].update(self.basis.pop(right_root))
        self.basis[left_root].add(basis)
        return True, None


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EntityNormalizationError(f"{key} must be a non-empty string")
    return value.strip()


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise EntityNormalizationError(f"{key} must be an integer")
    return value


def _normalize_surface(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _literal_pattern(value: str) -> str:
    pieces = re.split(r"\s+", unicodedata.normalize("NFKC", value).strip())
    return r"\s*".join(re.escape(piece) for piece in pieces if piece)


def _marker_pattern(markers: Sequence[str]) -> str:
    patterns: list[str] = []
    for marker in markers:
        escaped = re.escape(marker.strip()).replace(r"\ ", r"\s+")
        patterns.append(escaped)
    return "(?:" + "|".join(patterns) + ")"


def _stable_id(prefix: str, *parts: object, length: int = 24) -> str:
    payload = "\0".join(str(part) for part in parts)
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:length]


def _validated_unit_lookup(source_text: str, units: Sequence[UnitSpan]) -> dict[tuple[str, str], UnitSpan]:
    if not units:
        raise EntityNormalizationError("Unit index is empty")
    lookup: dict[tuple[str, str], UnitSpan] = {}
    by_source: dict[str, list[UnitSpan]] = defaultdict(list)
    for unit in units:
        key = (unit.source_id, unit.unit_id)
        if not unit.source_id or not unit.unit_id:
            raise EntityNormalizationError("Unit source_id and unit_id must be non-empty")
        if key in lookup:
            raise EntityNormalizationError(f"duplicate Unit identity: {key}")
        if unit.start < 0 or unit.end <= unit.start or unit.end > len(source_text):
            raise EntityNormalizationError(f"invalid Unit span: {key}")
        lookup[key] = unit
        by_source[unit.source_id].append(unit)
    for source_id, group in by_source.items():
        previous_end = -1
        for unit in sorted(group, key=lambda item: (item.start, item.end, item.unit_id)):
            if unit.start < previous_end:
                raise EntityNormalizationError(f"overlapping Unit spans for source {source_id!r}")
            previous_end = unit.end
    return lookup


def _result_from_dict(payload: Mapping[str, object]) -> ClaimValidationResult:
    def text(name: str) -> str:
        return _required_text(payload, name)

    reasons = payload.get("reason_codes")
    spans = payload.get("matched_spans")
    normalized = payload.get("normalized_claim")
    if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
        raise EntityNormalizationError("validation reason_codes must be a string array")
    if not isinstance(spans, list) or not all(
        isinstance(item, list)
        and len(item) == 2
        and all(isinstance(number, int) and not isinstance(number, bool) for number in item)
        for item in spans
    ):
        raise EntityNormalizationError("validation matched_spans must be integer pairs")
    if not isinstance(normalized, dict):
        raise EntityNormalizationError("validation normalized_claim must be an object")
    may_index = payload.get("may_index")
    may_freeze = payload.get("may_freeze")
    if not isinstance(may_index, bool) or not isinstance(may_freeze, bool):
        raise EntityNormalizationError("validation permissions must be booleans")
    return ClaimValidationResult(
        result_id=text("result_id"),
        claim_fingerprint=text("claim_fingerprint"),
        validator_version=text("validator_version"),
        status=text("status"),
        reason_codes=tuple(reasons),
        may_index=may_index,
        may_freeze=may_freeze,
        source_id=text("source_id"),
        unit_id=text("unit_id"),
        evidence_start=_required_int(payload, "evidence_start"),
        evidence_end=_required_int(payload, "evidence_end"),
        evidence_sha256=text("evidence_sha256"),
        matched_spans=tuple((item[0], item[1]) for item in spans),
        normalized_claim=dict(normalized),
    )


def revalidate_accepted_records(
    records: Sequence[Mapping[str, object]],
    source_text: str,
    units: Sequence[UnitSpan],
) -> tuple[AcceptedClaim, ...]:
    """Re-run Phase 3 and reject stale, forged, duplicate, or non-accepted artifacts."""

    if not isinstance(source_text, str) or not source_text:
        raise EntityNormalizationError("source text must be a non-empty string")
    if not records:
        raise EntityNormalizationError("accepted Claim records are empty")
    unit_lookup = _validated_unit_lookup(source_text, units)
    accepted: list[AcceptedClaim] = []
    seen_results: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, Mapping):
            raise EntityNormalizationError(f"accepted record {index} must be an object")
        candidate_payload = record.get("candidate")
        validation_payload = record.get("validation")
        if not isinstance(candidate_payload, Mapping) or not isinstance(validation_payload, Mapping):
            raise EntityNormalizationError(f"accepted record {index} lacks candidate/validation objects")
        candidate = ClaimCandidate.from_dict(candidate_payload)
        stored = _result_from_dict(validation_payload)
        unit = unit_lookup.get((candidate.source_id, candidate.unit_id))
        recomputed = validate_claim(candidate, source_text, unit_span=unit, require_unit=True)
        if recomputed.status != "accepted" or not recomputed.may_index:
            raise EntityNormalizationError(
                f"record {index} is not accepted after fresh Claim validation: {recomputed.reason_codes}"
            )
        if stored.status != "accepted" or not stored.may_index or stored.may_freeze:
            raise EntityNormalizationError(f"record {index} has invalid stored acceptance permissions")
        if stored.validator_version != VALIDATOR_VERSION:
            raise EntityNormalizationError(f"record {index} uses a stale Claim validator version")
        if stored.to_dict() != recomputed.to_dict():
            raise EntityNormalizationError(f"record {index} Claim validation artifact was modified")
        if recomputed.result_id in seen_results:
            raise EntityNormalizationError(f"duplicate accepted Claim result: {recomputed.result_id}")
        seen_results.add(recomputed.result_id)
        evidence = source_text[candidate.evidence_start : candidate.evidence_end]
        line = record.get("candidate_line", index)
        if isinstance(line, bool) or not isinstance(line, int):
            raise EntityNormalizationError("candidate_line must be an integer")
        accepted.append(AcceptedClaim(line, candidate, recomputed, evidence))
    return tuple(accepted)


def _role_type(claim_type: str, role: str) -> str:
    if claim_type == "defeats":
        return "actor"
    if claim_type == "located_in":
        return "place" if role == "object" else "entity"
    if claim_type == "permission":
        return "actor" if role == "subject" else "unknown"
    return "entity" if role == "subject" else "unknown"


def _occurrences(text: str, surface: str) -> list[tuple[int, int]]:
    pattern = re.compile(_literal_pattern(surface), re.IGNORECASE)
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def _mention_span(accepted: AcceptedClaim, surface: str) -> tuple[int, int]:
    occurrences = _occurrences(accepted.evidence, surface)
    if not occurrences:
        raise EntityNormalizationError(
            f"accepted Claim {accepted.validation.result_id} does not contain its entity surface {surface!r}"
        )
    matched = accepted.validation.matched_spans
    if matched:
        overlapping = [
            span
            for span in occurrences
            if any(span[0] < relation_end and relation_start < span[1] for relation_start, relation_end in matched)
        ]
        choices = overlapping or occurrences
        anchor = matched[0][0]
        local_start, local_end = min(choices, key=lambda span: (abs(span[0] - anchor), span[0], span[1]))
    else:
        local_start, local_end = occurrences[0]
    return accepted.candidate.evidence_start + local_start, accepted.candidate.evidence_start + local_end


def _make_mentions(claims: Sequence[AcceptedClaim]) -> tuple[Mention, ...]:
    mentions: list[Mention] = []
    for accepted in claims:
        candidate = accepted.candidate
        roles = [("subject", candidate.subject)]
        if candidate.claim_type in {"alias", "defeats", "located_in"}:
            roles.append(("object", candidate.object))
        for role, surface in roles:
            if not surface:
                continue
            start, end = _mention_span(accepted, surface)
            normalized = _normalize_surface(surface)
            mention_id = _stable_id(
                "men_",
                NORMALIZER_VERSION,
                accepted.validation.result_id,
                role,
                normalized,
                candidate.source_id,
                candidate.unit_id,
                start,
                end,
            )
            mentions.append(
                Mention(
                    mention_id=mention_id,
                    claim_result_id=accepted.validation.result_id,
                    role=role,
                    surface=surface.strip(),
                    normalized_surface=normalized,
                    inferred_type=_role_type(candidate.claim_type, role),
                    source_id=candidate.source_id,
                    unit_id=candidate.unit_id,
                    evidence_start=start,
                    evidence_end=end,
                )
            )
    return tuple(
        sorted(mentions, key=lambda item: (item.source_id, item.evidence_start, item.role, item.mention_id))
    )


def _identity_relation_pattern(left: str, right: str, relation: str) -> re.Pattern[str]:
    left_pattern = _literal_pattern(left)
    right_pattern = _literal_pattern(right)
    if relation == "same_as":
        middle = _marker_pattern(_SAME_MIDDLE_MARKERS)
        tail = _marker_pattern(_SAME_TAIL_MARKERS)
        expression = (
            rf"(?:{left_pattern}{_IDENTITY_GAP}{middle}{_IDENTITY_GAP}{right_pattern}"
            rf"|{right_pattern}{_IDENTITY_GAP}{middle}{_IDENTITY_GAP}{left_pattern}"
            rf"|{left_pattern}{_IDENTITY_GAP}{_IDENTITY_JOIN}{_IDENTITY_GAP}{right_pattern}{_IDENTITY_GAP}{tail}"
            rf"|{right_pattern}{_IDENTITY_GAP}{_IDENTITY_JOIN}{_IDENTITY_GAP}{left_pattern}{_IDENTITY_GAP}{tail})"
        )
    else:
        tail = _marker_pattern(_DIFFERENT_TAIL_MARKERS)
        expression = (
            rf"(?:{left_pattern}{_IDENTITY_GAP}{_IDENTITY_JOIN}{_IDENTITY_GAP}{right_pattern}{_IDENTITY_GAP}{tail}"
            rf"|{right_pattern}{_IDENTITY_GAP}{_IDENTITY_JOIN}{_IDENTITY_GAP}{left_pattern}{_IDENTITY_GAP}{tail})"
        )
    return re.compile(expression, re.IGNORECASE)


def _validate_identity_links(
    links: Sequence[IdentityLink],
    source_text: str,
    units: Sequence[UnitSpan],
    mention_by_key: Mapping[tuple[str, str], Mention],
) -> tuple[list[tuple[IdentityLink, Mention, Mention]], set[frozenset[str]]]:
    unit_lookup = _validated_unit_lookup(source_text, units)
    validated: list[tuple[IdentityLink, Mention, Mention]] = []
    forbidden: set[frozenset[str]] = set()
    seen_links: set[tuple[object, ...]] = set()
    for index, link in enumerate(links, start=1):
        signature = (
            link.relation,
            link.left_result_id,
            link.left_role,
            link.right_result_id,
            link.right_role,
            link.source_id,
            link.unit_id,
            link.evidence_start,
            link.evidence_end,
        )
        if signature in seen_links:
            raise EntityNormalizationError(f"duplicate identity link at item {index}")
        seen_links.add(signature)
        left = mention_by_key.get((link.left_result_id, link.left_role))
        right = mention_by_key.get((link.right_result_id, link.right_role))
        if left is None or right is None:
            raise EntityNormalizationError(f"identity link {index} references an unknown mention")
        if left.mention_id == right.mention_id:
            raise EntityNormalizationError(f"identity link {index} references the same mention twice")
        if left.source_id != right.source_id or link.source_id != left.source_id:
            raise EntityNormalizationError(f"identity link {index} cannot cross source boundaries")
        if link.evidence_start < 0 or link.evidence_end <= link.evidence_start or link.evidence_end > len(source_text):
            raise EntityNormalizationError(f"identity link {index} evidence span is invalid")
        evidence = source_text[link.evidence_start : link.evidence_end]
        if evidence != link.evidence_text:
            raise EntityNormalizationError(f"identity link {index} evidence text mismatch")
        unit = unit_lookup.get((link.source_id, link.unit_id))
        if unit is None or not unit.start <= link.evidence_start < link.evidence_end <= unit.end:
            raise EntityNormalizationError(f"identity link {index} evidence is outside its Unit")
        if _IDENTITY_MODAL_RE.search(evidence):
            raise EntityNormalizationError(f"identity link {index} is modal, reported, hypothetical, or a question")
        relation_pattern = _identity_relation_pattern(left.surface, right.surface, link.relation)
        if not relation_pattern.search(evidence):
            raise EntityNormalizationError(
                f"identity link {index} lacks an exact {link.relation} relation between both referenced surfaces"
            )
        validated.append((link, left, right))
        if link.relation == "different_from":
            forbidden.add(frozenset((left.mention_id, right.mention_id)))
    return validated, forbidden


def _conflict(
    conflict_type: str,
    *,
    severity: str,
    status: str,
    entity_ids: Iterable[str] = (),
    fact_ids: Iterable[str] = (),
    mention_ids: Iterable[str] = (),
    details: Mapping[str, object] | None = None,
) -> Conflict:
    entities = tuple(sorted(set(entity_ids)))
    facts = tuple(sorted(set(fact_ids)))
    mentions = tuple(sorted(set(mention_ids)))
    detail_dict = dict(details or {})
    payload = json.dumps(detail_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    conflict_id = _stable_id(
        "cnf_", NORMALIZER_VERSION, conflict_type, severity, status, entities, facts, mentions, payload
    )
    return Conflict(conflict_id, conflict_type, severity, status, entities, facts, mentions, detail_dict)


def _assertion_context(accepted: AcceptedClaim) -> str:
    if not accepted.validation.matched_spans:
        return accepted.evidence
    anchor_start, anchor_end = accepted.validation.matched_spans[0]
    left = 0
    right = len(accepted.evidence)
    for match in _ASSERTION_BREAK_RE.finditer(accepted.evidence):
        if match.end() <= anchor_start:
            left = match.end()
        elif match.start() >= anchor_end:
            right = match.start()
            break
    return accepted.evidence[left:right]


def _temporal_marker(accepted: AcceptedClaim) -> str:
    context = _assertion_context(accepted)
    earlier = bool(_EARLIER_RE.search(context))
    later = bool(_LATER_RE.search(context))
    if earlier and later:
        return "mixed"
    if earlier:
        return "earlier"
    if later:
        return "later"
    return "unspecified"


def _predicate_scope(accepted: AcceptedClaim) -> str:
    candidate = accepted.candidate
    context = _assertion_context(accepted)
    if candidate.claim_type == "date":
        for scope, pattern in _DATE_SCOPE_PATTERNS:
            if pattern.search(context):
                return scope
        return "generic_date"
    if candidate.claim_type == "count":
        return "count:" + _normalize_surface(candidate.unit or "unspecified")
    if candidate.claim_type == "permission":
        return "permission:" + _normalize_surface(candidate.object)
    if candidate.claim_type == "located_in":
        return "location"
    if candidate.claim_type == "defeats":
        return "defeats"
    if candidate.claim_type == "alias":
        return "identity"
    return candidate.claim_type


def _entity_type(types: set[str]) -> str:
    concrete = types - {"unknown", "entity"}
    if len(concrete) == 1:
        return next(iter(concrete))
    if not concrete:
        return "entity"
    return "mixed"


def _canonical_name(component: Sequence[Mention]) -> str:
    counts = Counter(item.surface for item in component)
    first_position = {
        name: min(item.evidence_start for item in component if item.surface == name) for name in counts
    }
    return min(counts, key=lambda name: (-counts[name], first_position[name], name))


def _attach_claim_conflicts(conflicts: Sequence[Conflict], facts: Sequence[Fact]) -> list[Conflict]:
    by_result = {fact.claim_result_id: fact.fact_id for fact in facts}
    attached: list[Conflict] = []
    for conflict in conflicts:
        result_id = conflict.details.get("claim_result_id")
        if isinstance(result_id, str) and result_id in by_result and by_result[result_id] not in conflict.fact_ids:
            attached.append(
                _conflict(
                    conflict.conflict_type,
                    severity=conflict.severity,
                    status=conflict.status,
                    entity_ids=conflict.entity_ids,
                    fact_ids=(*conflict.fact_ids, by_result[result_id]),
                    mention_ids=conflict.mention_ids,
                    details=conflict.details,
                )
            )
        else:
            attached.append(conflict)
    return attached


def normalize_entities(
    accepted_records: Sequence[Mapping[str, object]],
    source_text: str,
    units: Sequence[UnitSpan],
    *,
    identity_links: Sequence[IdentityLink] = (),
) -> NormalizationBundle:
    """Build deterministic entities/facts while retaining ambiguity and conflicts."""

    accepted = revalidate_accepted_records(accepted_records, source_text, units)
    mentions = _make_mentions(accepted)
    mention_map = {mention.mention_id: mention for mention in mentions}
    mention_by_key = {(mention.claim_result_id, mention.role): mention for mention in mentions}
    if len(mention_by_key) != len(mentions):
        raise EntityNormalizationError("duplicate Claim role mention key")

    validated_links, forbidden_pairs = _validate_identity_links(
        identity_links, source_text, units, mention_by_key
    )
    forbidden_neighbors: dict[str, set[str]] = defaultdict(set)
    for pair in forbidden_pairs:
        left_id, right_id = tuple(pair)
        forbidden_neighbors[left_id].add(right_id)
        forbidden_neighbors[right_id].add(left_id)
    union = _UnionFind(mention_map)
    conflicts: list[Conflict] = []

    # Local continuity is a documented heuristic: only exact surface matches inside
    # one Unit are merged automatically. Cross-Unit identity remains explicit.
    local_groups: dict[tuple[str, str, str], list[Mention]] = defaultdict(list)
    for mention in mentions:
        local_groups[(mention.source_id, mention.unit_id, mention.normalized_surface)].append(mention)
    for group in local_groups.values():
        anchor = group[0]
        for other in group[1:]:
            merged, reason = union.union(
                anchor.mention_id,
                other.mention_id,
                basis="same_surface_same_unit",
                forbidden_neighbors=forbidden_neighbors,
            )
            if not merged:
                conflicts.append(
                    _conflict(
                        reason or "LOCAL_IDENTITY_MERGE_BLOCKED",
                        severity="review",
                        status="unresolved",
                        mention_ids=(anchor.mention_id, other.mention_id),
                    )
                )

    for item in accepted:
        if item.candidate.claim_type != "alias":
            continue
        left = mention_by_key.get((item.validation.result_id, "subject"))
        right = mention_by_key.get((item.validation.result_id, "object"))
        if left is None or right is None:
            raise EntityNormalizationError("accepted alias Claim lacks both mentions")
        merged, reason = union.union(
            left.mention_id,
            right.mention_id,
            basis="accepted_alias_claim",
            forbidden_neighbors=forbidden_neighbors,
        )
        if not merged:
            conflicts.append(
                _conflict(
                    reason or "ALIAS_MERGE_BLOCKED",
                    severity="blocker",
                    status="unresolved",
                    mention_ids=(left.mention_id, right.mention_id),
                    details={"claim_result_id": item.validation.result_id},
                )
            )

    for link, left, right in validated_links:
        if link.relation == "different_from":
            if union.find(left.mention_id) == union.find(right.mention_id):
                conflicts.append(
                    _conflict(
                        "IDENTITY_CONSTRAINT_CONTRADICTION",
                        severity="blocker",
                        status="unresolved",
                        mention_ids=(left.mention_id, right.mention_id),
                        details={"relation": link.relation},
                    )
                )
            continue
        merged, reason = union.union(
            left.mention_id,
            right.mention_id,
            basis="evidence_bound_same_as",
            forbidden_neighbors=forbidden_neighbors,
        )
        if not merged:
            conflicts.append(
                _conflict(
                    reason or "IDENTITY_LINK_MERGE_BLOCKED",
                    severity="blocker",
                    status="unresolved",
                    mention_ids=(left.mention_id, right.mention_id),
                    details={"relation": link.relation},
                )
            )

    components: dict[str, list[Mention]] = defaultdict(list)
    for mention in mentions:
        components[union.find(mention.mention_id)].append(mention)

    entities: list[Entity] = []
    mention_to_entity: dict[str, str] = {}
    for root, component in sorted(components.items()):
        ordered = sorted(component, key=lambda item: (item.evidence_start, item.surface, item.mention_id))
        canonical = _canonical_name(ordered)
        aliases = tuple(sorted(set(item.surface for item in ordered)))
        types = {item.inferred_type for item in ordered}
        mention_ids = tuple(item.mention_id for item in ordered)
        entity_id = _stable_id(
            "ent_", NORMALIZER_VERSION, tuple(sorted(mention_ids)), canonical, aliases, _entity_type(types)
        )
        entity = Entity(
            entity_id=entity_id,
            canonical_name=canonical,
            aliases=aliases,
            entity_type=_entity_type(types),
            mention_ids=mention_ids,
            source_ids=tuple(sorted(set(item.source_id for item in ordered))),
            unit_ids=tuple(sorted(set(item.unit_id for item in ordered))),
            merge_basis=tuple(sorted(union.basis[union.find(root)])),
        )
        entities.append(entity)
        for mention_id in mention_ids:
            mention_to_entity[mention_id] = entity_id

    facts: list[Fact] = []
    for item in accepted:
        candidate = item.candidate
        validation = item.validation
        subject_mention = mention_by_key.get((validation.result_id, "subject"))
        object_mention = mention_by_key.get((validation.result_id, "object"))
        normalized = validation.normalized_claim
        scope = _predicate_scope(item)
        fact_id = _stable_id(
            "fac_",
            NORMALIZER_VERSION,
            validation.result_id,
            scope,
            json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        facts.append(
            Fact(
                fact_id=fact_id,
                claim_result_id=validation.result_id,
                claim_type=candidate.claim_type,
                predicate_scope=scope,
                subject_entity_id=(
                    mention_to_entity[subject_mention.mention_id] if subject_mention is not None else None
                ),
                subject=str(normalized.get("subject", "")),
                object_entity_id=(
                    mention_to_entity[object_mention.mention_id] if object_mention is not None else None
                ),
                object=str(normalized.get("object", "")),
                value=normalized.get("value"),
                unit=str(normalized.get("unit", "")),
                polarity=bool(normalized.get("polarity", True)),
                source_id=candidate.source_id,
                unit_id=candidate.unit_id,
                evidence_start=candidate.evidence_start,
                evidence_end=candidate.evidence_end,
                evidence_sha256=validation.evidence_sha256,
                temporal_marker=_temporal_marker(item),
            )
        )

    facts.sort(key=lambda item: (item.source_id, item.evidence_start, item.fact_id))
    conflicts = _attach_claim_conflicts(conflicts, facts)
    conflicts.extend(_detect_fact_conflicts(facts))
    conflicts = sorted({item.conflict_id: item for item in conflicts}.values(), key=lambda item: item.conflict_id)

    conflict_by_fact: dict[str, list[Conflict]] = defaultdict(list)
    for conflict in conflicts:
        for fact_id in conflict.fact_ids:
            conflict_by_fact[fact_id].append(conflict)
    normalized_facts: list[Fact] = []
    for fact in facts:
        related = conflict_by_fact.get(fact.fact_id, [])
        statuses = {item.status for item in related}
        if "unresolved" in statuses:
            canonical_status = "contested"
        elif "resolved_temporal" in statuses:
            canonical_status = "temporal_variant"
        elif "resolved_precision" in statuses:
            canonical_status = "compatible_variant"
        else:
            canonical_status = "canonical"
        normalized_facts.append(
            replace(
                fact,
                canonical_status=canonical_status,
                conflict_ids=tuple(sorted(item.conflict_id for item in related)),
            )
        )

    source_orders: Counter[str] = Counter()
    timeline_rows: list[TimelineEvent] = []
    for fact in normalized_facts:
        source_orders[fact.source_id] += 1
        timeline_rows.append(
            TimelineEvent(
                event_id=_stable_id("evt_", NORMALIZER_VERSION, fact.fact_id),
                fact_id=fact.fact_id,
                source_id=fact.source_id,
                unit_id=fact.unit_id,
                source_order=source_orders[fact.source_id],
                evidence_start=fact.evidence_start,
                evidence_end=fact.evidence_end,
                event_type=fact.claim_type,
                predicate_scope=fact.predicate_scope,
                normalized_date=(str(fact.value) if fact.claim_type == "date" else None),
                temporal_marker=fact.temporal_marker,
                subject_entity_id=fact.subject_entity_id,
                object_entity_id=fact.object_entity_id,
            )
        )
    timeline = tuple(timeline_rows)

    surface_to_entities: dict[tuple[str, str], set[str]] = defaultdict(set)
    surface_to_mentions: dict[tuple[str, str], set[str]] = defaultdict(set)
    surface_forms: dict[tuple[str, str], set[str]] = defaultdict(set)
    for mention in mentions:
        key = (mention.source_id, mention.normalized_surface)
        entity_id = mention_to_entity[mention.mention_id]
        surface_to_entities[key].add(entity_id)
        surface_to_mentions[key].add(mention.mention_id)
        surface_forms[key].add(mention.surface)
    ambiguities: list[AmbiguityGroup] = []
    for (source_id, surface), entity_ids in sorted(surface_to_entities.items()):
        if len(entity_ids) <= 1:
            continue
        ambiguity_id = _stable_id(
            "amb_", NORMALIZER_VERSION, source_id, surface, tuple(sorted(entity_ids))
        )
        ambiguities.append(
            AmbiguityGroup(
                ambiguity_id=ambiguity_id,
                source_id=source_id,
                normalized_surface=surface,
                surfaces=tuple(sorted(surface_forms[(source_id, surface)])),
                entity_ids=tuple(sorted(entity_ids)),
                mention_ids=tuple(sorted(surface_to_mentions[(source_id, surface)])),
                reason="SAME_SURFACE_MULTIPLE_ENTITIES",
            )
        )

    blocker_count = sum(item.severity == "blocker" for item in conflicts)
    contested_count = sum(fact.canonical_status == "contested" for fact in normalized_facts)
    ambiguity_count = len(ambiguities)
    report = {
        "normalizer_version": NORMALIZER_VERSION,
        "status": "completed",
        "source_sha256": sha256(source_text.encode("utf-8")).hexdigest(),
        "claim_validator_version": VALIDATOR_VERSION,
        "accepted_claim_count": len(accepted),
        "mention_count": len(mentions),
        "entity_count": len(entities),
        "fact_count": len(normalized_facts),
        "timeline_event_count": len(timeline),
        "identity_link_count": len(identity_links),
        "ambiguity_group_count": ambiguity_count,
        "unresolved_ambiguity_count": ambiguity_count,
        "conflict_count": len(conflicts),
        "blocker_conflict_count": blocker_count,
        "contested_fact_count": contested_count,
        "canonical_fact_count": sum(fact.canonical_status == "canonical" for fact in normalized_facts),
        "temporal_variant_count": sum(
            fact.canonical_status == "temporal_variant" for fact in normalized_facts
        ),
        "compatible_variant_count": sum(
            fact.canonical_status == "compatible_variant" for fact in normalized_facts
        ),
        "local_surface_merge_policy": "same_source_same_unit_exact_surface",
        "may_build_review_index": blocker_count == 0,
        "may_build_index": blocker_count == 0,
        "may_publish_canonical": blocker_count == 0 and contested_count == 0 and ambiguity_count == 0,
        "may_freeze": False,
    }
    return NormalizationBundle(
        mentions=mentions,
        entities=tuple(sorted(entities, key=lambda item: item.entity_id)),
        facts=tuple(normalized_facts),
        timeline=timeline,
        conflicts=tuple(conflicts),
        ambiguity_groups=tuple(ambiguities),
        report=report,
    )


def _subject_key(fact: Fact) -> str:
    return fact.subject_entity_id or "surface:" + _normalize_surface(fact.subject)


def _object_key(fact: Fact) -> str:
    return fact.object_entity_id or "surface:" + _normalize_surface(fact.object)


def _has_temporal_transition(
    facts: Sequence[Fact],
    *,
    state_key,
) -> bool:
    """Return true only when every adjacent state change has explicit support.

    A single ``later`` or ``earlier`` marker must not resolve an entire group with
    three or more conflicting values. Unchanged adjacent states need no marker,
    but each actual state change must be supported either by ``later`` on the new
    assertion or ``earlier`` on the preceding assertion.
    """

    ordered = sorted(facts, key=lambda item: (item.evidence_start, item.evidence_end, item.fact_id))
    if any(fact.temporal_marker == "mixed" for fact in ordered):
        return False

    changed = False
    for previous, current in zip(ordered, ordered[1:]):
        if state_key(previous) == state_key(current):
            continue
        changed = True
        if current.temporal_marker == "later" or previous.temporal_marker == "earlier":
            continue
        return False
    return changed


def _date_precision_compatible(values: set[str]) -> bool:
    if len(values) <= 1:
        return True
    ordered = sorted(values, key=len)
    shortest = ordered[0]
    return all(value == shortest or value.startswith(shortest + "-") for value in ordered[1:])


def _detect_fact_conflicts(facts: Sequence[Fact]) -> list[Conflict]:
    conflicts: list[Conflict] = []

    permissions: dict[tuple[str, str, str], list[Fact]] = defaultdict(list)
    counts: dict[tuple[str, str, str], list[Fact]] = defaultdict(list)
    locations: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    dates: dict[tuple[str, str, str], list[Fact]] = defaultdict(list)
    defeats: dict[tuple[str, frozenset[str]], list[Fact]] = defaultdict(list)

    for fact in facts:
        subject = _subject_key(fact)
        if fact.claim_type == "permission":
            permissions[(fact.source_id, subject, _normalize_surface(fact.object))].append(fact)
        elif fact.claim_type == "count":
            counts[(fact.source_id, subject, _normalize_surface(fact.unit))].append(fact)
        elif fact.claim_type == "located_in":
            locations[(fact.source_id, subject)].append(fact)
        elif fact.claim_type == "date":
            dates[(fact.source_id, subject, fact.predicate_scope)].append(fact)
        elif fact.claim_type == "defeats":
            defeats[(fact.source_id, frozenset((subject, _object_key(fact))))].append(fact)

    for (source_id, subject, action), group in permissions.items():
        if len({fact.polarity for fact in group}) > 1:
            temporal = _has_temporal_transition(group, state_key=lambda fact: fact.polarity)
            conflicts.append(
                _conflict(
                    "PERMISSION_POLARITY_TRANSITION" if temporal else "PERMISSION_POLARITY_CONFLICT",
                    severity="info" if temporal else "review",
                    status="resolved_temporal" if temporal else "unresolved",
                    entity_ids=[fact.subject_entity_id for fact in group if fact.subject_entity_id],
                    fact_ids=[fact.fact_id for fact in group],
                    details={"source_id": source_id, "subject": subject, "action": action},
                )
            )

    for (source_id, subject, unit), group in counts.items():
        values = {str(fact.value) for fact in group}
        if len(values) > 1:
            temporal = _has_temporal_transition(group, state_key=lambda fact: str(fact.value))
            conflicts.append(
                _conflict(
                    "COUNT_TEMPORAL_TRANSITION" if temporal else "MULTIPLE_COUNT_VALUES",
                    severity="info" if temporal else "review",
                    status="resolved_temporal" if temporal else "unresolved",
                    entity_ids=[fact.subject_entity_id for fact in group if fact.subject_entity_id],
                    fact_ids=[fact.fact_id for fact in group],
                    details={"source_id": source_id, "subject": subject, "unit": unit, "values": sorted(values)},
                )
            )

    for (source_id, subject), group in locations.items():
        values = {_object_key(fact) for fact in group}
        if len(values) > 1:
            temporal = _has_temporal_transition(group, state_key=_object_key)
            conflicts.append(
                _conflict(
                    "LOCATION_TEMPORAL_TRANSITION" if temporal else "MULTIPLE_LOCATIONS",
                    severity="info" if temporal else "review",
                    status="resolved_temporal" if temporal else "unresolved",
                    entity_ids=[
                        entity_id
                        for fact in group
                        for entity_id in (fact.subject_entity_id, fact.object_entity_id)
                        if entity_id
                    ],
                    fact_ids=[fact.fact_id for fact in group],
                    details={"source_id": source_id, "subject": subject, "location_values": sorted(values)},
                )
            )

    for (source_id, subject, predicate_scope), group in dates.items():
        values = {str(fact.value) for fact in group}
        if len(values) <= 1:
            continue
        if _date_precision_compatible(values):
            conflicts.append(
                _conflict(
                    "DATE_PRECISION_REFINEMENT",
                    severity="info",
                    status="resolved_precision",
                    entity_ids=[fact.subject_entity_id for fact in group if fact.subject_entity_id],
                    fact_ids=[fact.fact_id for fact in group],
                    details={
                        "source_id": source_id,
                        "subject": subject,
                        "predicate_scope": predicate_scope,
                        "values": sorted(values),
                    },
                )
            )
        else:
            conflicts.append(
                _conflict(
                    "MULTIPLE_DATE_VALUES",
                    severity="review",
                    status="unresolved",
                    entity_ids=[fact.subject_entity_id for fact in group if fact.subject_entity_id],
                    fact_ids=[fact.fact_id for fact in group],
                    details={
                        "source_id": source_id,
                        "subject": subject,
                        "predicate_scope": predicate_scope,
                        "values": sorted(values),
                    },
                )
            )

    for (source_id, pair), group in defeats.items():
        directions = {(_subject_key(fact), _object_key(fact)) for fact in group}
        if len(directions) > 1:
            temporal = _has_temporal_transition(
                group, state_key=lambda fact: (_subject_key(fact), _object_key(fact))
            )
            conflicts.append(
                _conflict(
                    "RECIPROCAL_DEFEATS_ACROSS_TIME" if temporal else "RECIPROCAL_DEFEATS_UNRESOLVED",
                    severity="info" if temporal else "review",
                    status="resolved_temporal" if temporal else "unresolved",
                    entity_ids=[
                        entity_id
                        for fact in group
                        for entity_id in (fact.subject_entity_id, fact.object_entity_id)
                        if entity_id
                    ],
                    fact_ids=[fact.fact_id for fact in group],
                    details={"source_id": source_id, "pair": sorted(pair)},
                )
            )
    return conflicts
