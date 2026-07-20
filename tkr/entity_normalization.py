"""Evidence-bound entity, alias, homonym, timeline, and conflict normalization.

This phase consumes only Phase 3 accepted Claim records and re-validates every
record against the normalized source and Unit index. It intentionally favors
precision over recall: identical surface forms in different Units are not merged
without an explicit, evidence-bound identity link.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
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

NORMALIZER_VERSION = "tkr-entity-normalizer-v1"

_EARLIER_RE = re.compile(
    r"(?:原先|原本|最初|起初|此前|之前|曾经|昔日|当初|formerly|initially|previously)",
    re.IGNORECASE,
)
_LATER_RE = re.compile(
    r"(?:后来|随后|之后|此后|最终|如今|现在|现已|改为|变为|later|afterwards|now|eventually)",
    re.IGNORECASE,
)
_SAME_IDENTITY_RE = re.compile(
    r"(?:同一人|同一个人|同一实体|正是|就是|即为|其实是|本名|真名|same person|same entity)",
    re.IGNORECASE,
)
_DIFFERENT_IDENTITY_RE = re.compile(
    r"(?:同名不同人|并非同一人|不是同一个人|并非同一实体|另一个|不同的人|different person|different entity|unrelated)",
    re.IGNORECASE,
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
        payload["entity_ids"] = list(self.entity_ids)
        payload["fact_ids"] = list(self.fact_ids)
        payload["mention_ids"] = list(self.mention_ids)
        return payload


@dataclass(frozen=True, slots=True)
class AmbiguityGroup:
    ambiguity_id: str
    normalized_surface: str
    surfaces: tuple[str, ...]
    entity_ids: tuple[str, ...]
    mention_ids: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["surfaces"] = list(self.surfaces)
        payload["entity_ids"] = list(self.entity_ids)
        payload["mention_ids"] = list(self.mention_ids)
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
    def __init__(self, mention_ids: Iterable[str], mentions: Mapping[str, Mention]) -> None:
        self.parent = {item: item for item in mention_ids}
        self.members = {item: {item} for item in mention_ids}
        self.types = {
            item: ({mentions[item].inferred_type} - {"unknown", "entity"}) for item in mention_ids
        }
        self.basis = {item: set() for item in mention_ids}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def roots_conflict(self, left: str, right: str) -> bool:
        left_types = self.types[self.find(left)]
        right_types = self.types[self.find(right)]
        return bool(left_types and right_types and left_types != right_types)

    def union(
        self,
        left: str,
        right: str,
        *,
        basis: str,
        forbidden_pairs: set[frozenset[str]],
    ) -> tuple[bool, str | None]:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            self.basis[left_root].add(basis)
            return True, None
        if self.roots_conflict(left_root, right_root):
            return False, "ENTITY_TYPE_CONFLICT"
        for left_member in self.members[left_root]:
            for right_member in self.members[right_root]:
                if frozenset((left_member, right_member)) in forbidden_pairs:
                    return False, "EXPLICIT_DIFFERENT_FROM_CONSTRAINT"
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.members[left_root].update(self.members.pop(right_root))
        self.types[left_root].update(self.types.pop(right_root))
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


def _stable_id(prefix: str, *parts: object, length: int = 24) -> str:
    payload = "\0".join(str(part) for part in parts)
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:length]


def _result_from_dict(payload: Mapping[str, object]) -> ClaimValidationResult:
    def text(name: str) -> str:
        return _required_text(payload, name)

    status = text("status")
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
        status=status,
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
    """Re-run Phase 3 and reject stale, forged, or non-accepted artifacts."""

    if not records:
        raise EntityNormalizationError("accepted Claim records are empty")
    unit_lookup = {(unit.source_id, unit.unit_id): unit for unit in units}
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
            normalized = _normalize_surface(surface)
            mention_id = _stable_id(
                "men_",
                NORMALIZER_VERSION,
                accepted.validation.result_id,
                role,
                normalized,
                candidate.source_id,
                candidate.unit_id,
                candidate.evidence_start,
                candidate.evidence_end,
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
                    evidence_start=candidate.evidence_start,
                    evidence_end=candidate.evidence_end,
                )
            )
    return tuple(sorted(mentions, key=lambda item: (item.source_id, item.evidence_start, item.role, item.mention_id)))


def _validate_identity_links(
    links: Sequence[IdentityLink],
    source_text: str,
    units: Sequence[UnitSpan],
    mention_by_key: Mapping[tuple[str, str], Mention],
) -> tuple[list[tuple[IdentityLink, Mention, Mention]], set[frozenset[str]]]:
    unit_lookup = {(unit.source_id, unit.unit_id): unit for unit in units}
    validated: list[tuple[IdentityLink, Mention, Mention]] = []
    forbidden: set[frozenset[str]] = set()
    for index, link in enumerate(links, start=1):
        left = mention_by_key.get((link.left_result_id, link.left_role))
        right = mention_by_key.get((link.right_result_id, link.right_role))
        if left is None or right is None:
            raise EntityNormalizationError(f"identity link {index} references an unknown mention")
        if left.mention_id == right.mention_id:
            raise EntityNormalizationError(f"identity link {index} references the same mention twice")
        if link.evidence_start < 0 or link.evidence_end <= link.evidence_start or link.evidence_end > len(source_text):
            raise EntityNormalizationError(f"identity link {index} evidence span is invalid")
        evidence = source_text[link.evidence_start : link.evidence_end]
        if evidence != link.evidence_text:
            raise EntityNormalizationError(f"identity link {index} evidence text mismatch")
        unit = unit_lookup.get((link.source_id, link.unit_id))
        if unit is None or not unit.start <= link.evidence_start < link.evidence_end <= unit.end:
            raise EntityNormalizationError(f"identity link {index} evidence is outside its Unit")
        same = bool(_SAME_IDENTITY_RE.search(evidence))
        different = bool(_DIFFERENT_IDENTITY_RE.search(evidence))
        if link.relation == "same_as" and (not same or different):
            raise EntityNormalizationError(f"identity link {index} lacks unambiguous same-identity evidence")
        if link.relation == "different_from" and (not different or same):
            raise EntityNormalizationError(f"identity link {index} lacks unambiguous different-identity evidence")
        surfaces = [left.normalized_surface, right.normalized_surface]
        normalized_evidence = _normalize_surface(evidence)
        if surfaces[0] == surfaces[1]:
            if normalized_evidence.count(surfaces[0]) < 2:
                raise EntityNormalizationError(
                    f"identity link {index} must mention the homonymous surface at least twice"
                )
        elif any(surface not in normalized_evidence for surface in surfaces):
            raise EntityNormalizationError(f"identity link {index} evidence does not mention both entities")
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


def _temporal_marker(evidence: str) -> str:
    earlier = bool(_EARLIER_RE.search(evidence))
    later = bool(_LATER_RE.search(evidence))
    if earlier and later:
        return "mixed"
    if earlier:
        return "earlier"
    if later:
        return "later"
    return "unspecified"


def _entity_type(types: set[str]) -> str:
    concrete = types - {"unknown", "entity"}
    if len(concrete) == 1:
        return next(iter(concrete))
    if not concrete:
        return "entity"
    return "mixed"


def normalize_entities(
    accepted_records: Sequence[Mapping[str, object]],
    source_text: str,
    units: Sequence[UnitSpan],
    *,
    identity_links: Sequence[IdentityLink] = (),
) -> NormalizationBundle:
    """Build deterministic entities/facts while retaining ambiguity and conflict evidence."""

    accepted = revalidate_accepted_records(accepted_records, source_text, units)
    mentions = _make_mentions(accepted)
    mention_map = {mention.mention_id: mention for mention in mentions}
    mention_by_key = {(mention.claim_result_id, mention.role): mention for mention in mentions}
    if len(mention_by_key) != len(mentions):
        raise EntityNormalizationError("duplicate Claim role mention key")

    validated_links, forbidden_pairs = _validate_identity_links(
        identity_links, source_text, units, mention_by_key
    )
    union = _UnionFind(mention_map, mention_map)
    conflicts: list[Conflict] = []

    # Exact local surface continuity is intentionally scoped to one Unit. Cross-Unit
    # consolidation requires alias evidence or an explicit same_as identity link.
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
                forbidden_pairs=forbidden_pairs,
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

    accepted_by_result = {item.validation.result_id: item for item in accepted}
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
            forbidden_pairs=forbidden_pairs,
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
            forbidden_pairs=forbidden_pairs,
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
        counts = Counter(item.surface for item in ordered)
        canonical = min(counts, key=lambda name: (-counts[name], ordered[0].evidence_start if name == ordered[0].surface else min(item.evidence_start for item in ordered if item.surface == name), name))
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

    fact_rows: list[Fact] = []
    for item in accepted:
        candidate = item.candidate
        validation = item.validation
        subject_mention = mention_by_key.get((validation.result_id, "subject"))
        object_mention = mention_by_key.get((validation.result_id, "object"))
        normalized = validation.normalized_claim
        fact_id = _stable_id(
            "fac_", NORMALIZER_VERSION, validation.result_id, json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        )
        fact_rows.append(
            Fact(
                fact_id=fact_id,
                claim_result_id=validation.result_id,
                claim_type=candidate.claim_type,
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
                temporal_marker=_temporal_marker(item.evidence),
            )
        )

    fact_rows.sort(key=lambda item: (item.source_id, item.evidence_start, item.fact_id))
    factual_conflicts = _detect_fact_conflicts(fact_rows)
    conflicts.extend(factual_conflicts)

    conflict_by_fact: dict[str, list[Conflict]] = defaultdict(list)
    for conflict in conflicts:
        for fact_id in conflict.fact_ids:
            conflict_by_fact[fact_id].append(conflict)
    normalized_facts: list[Fact] = []
    for fact in fact_rows:
        related = conflict_by_fact.get(fact.fact_id, [])
        statuses = {item.status for item in related}
        canonical_status = "contested" if "unresolved" in statuses else (
            "temporal_variant" if related else "canonical"
        )
        normalized_facts.append(
            Fact(
                **{
                    **asdict(fact),
                    "canonical_status": canonical_status,
                    "conflict_ids": tuple(sorted(item.conflict_id for item in related)),
                }
            )
        )

    timeline = tuple(
        TimelineEvent(
            event_id=_stable_id("evt_", NORMALIZER_VERSION, fact.fact_id, order),
            fact_id=fact.fact_id,
            source_id=fact.source_id,
            unit_id=fact.unit_id,
            source_order=order,
            evidence_start=fact.evidence_start,
            evidence_end=fact.evidence_end,
            event_type=fact.claim_type,
            normalized_date=(str(fact.value) if fact.claim_type == "date" else None),
            temporal_marker=fact.temporal_marker,
            subject_entity_id=fact.subject_entity_id,
            object_entity_id=fact.object_entity_id,
        )
        for order, fact in enumerate(normalized_facts, start=1)
    )

    entity_by_id = {entity.entity_id: entity for entity in entities}
    surface_to_entities: dict[str, set[str]] = defaultdict(set)
    surface_to_mentions: dict[str, set[str]] = defaultdict(set)
    surface_forms: dict[str, set[str]] = defaultdict(set)
    for mention in mentions:
        entity_id = mention_to_entity[mention.mention_id]
        surface_to_entities[mention.normalized_surface].add(entity_id)
        surface_to_mentions[mention.normalized_surface].add(mention.mention_id)
        surface_forms[mention.normalized_surface].add(mention.surface)
    ambiguities: list[AmbiguityGroup] = []
    for surface, entity_ids in sorted(surface_to_entities.items()):
        if len(entity_ids) <= 1:
            continue
        ambiguity_id = _stable_id("amb_", NORMALIZER_VERSION, surface, tuple(sorted(entity_ids)))
        ambiguities.append(
            AmbiguityGroup(
                ambiguity_id=ambiguity_id,
                normalized_surface=surface,
                surfaces=tuple(sorted(surface_forms[surface])),
                entity_ids=tuple(sorted(entity_ids)),
                mention_ids=tuple(sorted(surface_to_mentions[surface])),
                reason="SAME_SURFACE_MULTIPLE_ENTITIES",
            )
        )

    conflicts = sorted({item.conflict_id: item for item in conflicts}.values(), key=lambda item: item.conflict_id)
    blocker_count = sum(item.severity == "blocker" for item in conflicts)
    contested_count = sum(fact.canonical_status == "contested" for fact in normalized_facts)
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
        "ambiguity_group_count": len(ambiguities),
        "conflict_count": len(conflicts),
        "blocker_conflict_count": blocker_count,
        "contested_fact_count": contested_count,
        "canonical_fact_count": sum(fact.canonical_status == "canonical" for fact in normalized_facts),
        "temporal_variant_count": sum(
            fact.canonical_status == "temporal_variant" for fact in normalized_facts
        ),
        "may_build_index": blocker_count == 0,
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


def _has_temporal_transition(facts: Sequence[Fact]) -> bool:
    markers = {fact.temporal_marker for fact in facts}
    return "later" in markers or ("earlier" in markers and len(facts) > 1)


def _detect_fact_conflicts(facts: Sequence[Fact]) -> list[Conflict]:
    conflicts: list[Conflict] = []

    permissions: dict[tuple[str | None, str], list[Fact]] = defaultdict(list)
    counts: dict[tuple[str | None, str], list[Fact]] = defaultdict(list)
    locations: dict[str | None, list[Fact]] = defaultdict(list)
    dates: dict[str | None, list[Fact]] = defaultdict(list)
    defeats: dict[frozenset[str | None], list[Fact]] = defaultdict(list)

    for fact in facts:
        if fact.claim_type == "permission":
            permissions[(fact.subject_entity_id, _normalize_surface(fact.object))].append(fact)
        elif fact.claim_type == "count":
            counts[(fact.subject_entity_id, _normalize_surface(fact.unit))].append(fact)
        elif fact.claim_type == "located_in":
            locations[fact.subject_entity_id].append(fact)
        elif fact.claim_type == "date":
            dates[fact.subject_entity_id].append(fact)
        elif fact.claim_type == "defeats":
            defeats[frozenset((fact.subject_entity_id, fact.object_entity_id))].append(fact)

    for key, group in permissions.items():
        if len({fact.polarity for fact in group}) > 1:
            temporal = _has_temporal_transition(group)
            conflicts.append(
                _conflict(
                    "PERMISSION_POLARITY_TRANSITION" if temporal else "PERMISSION_POLARITY_CONFLICT",
                    severity="info" if temporal else "review",
                    status="resolved_temporal" if temporal else "unresolved",
                    entity_ids=[key[0]] if key[0] else (),
                    fact_ids=[fact.fact_id for fact in group],
                    details={"action": key[1]},
                )
            )

    for key, group in counts.items():
        values = {str(fact.value) for fact in group}
        if len(values) > 1:
            temporal = _has_temporal_transition(group)
            conflicts.append(
                _conflict(
                    "COUNT_TEMPORAL_TRANSITION" if temporal else "MULTIPLE_COUNT_VALUES",
                    severity="info" if temporal else "review",
                    status="resolved_temporal" if temporal else "unresolved",
                    entity_ids=[key[0]] if key[0] else (),
                    fact_ids=[fact.fact_id for fact in group],
                    details={"unit": key[1], "values": sorted(values)},
                )
            )

    for subject, group in locations.items():
        values = {fact.object_entity_id or fact.object for fact in group}
        if len(values) > 1:
            temporal = _has_temporal_transition(group)
            conflicts.append(
                _conflict(
                    "LOCATION_TEMPORAL_TRANSITION" if temporal else "MULTIPLE_LOCATIONS",
                    severity="info" if temporal else "review",
                    status="resolved_temporal" if temporal else "unresolved",
                    entity_ids=[item for item in [subject, *values] if isinstance(item, str)],
                    fact_ids=[fact.fact_id for fact in group],
                    details={"location_values": sorted(str(value) for value in values)},
                )
            )

    for subject, group in dates.items():
        values = {str(fact.value) for fact in group}
        if len(values) > 1:
            conflicts.append(
                _conflict(
                    "MULTIPLE_DATE_VALUES",
                    severity="review",
                    status="unresolved",
                    entity_ids=[subject] if subject else (),
                    fact_ids=[fact.fact_id for fact in group],
                    details={"values": sorted(values)},
                )
            )

    for pair, group in defeats.items():
        directions = {(fact.subject_entity_id, fact.object_entity_id) for fact in group}
        if len(directions) > 1:
            temporal = _has_temporal_transition(group)
            conflicts.append(
                _conflict(
                    "RECIPROCAL_DEFEATS_ACROSS_TIME" if temporal else "RECIPROCAL_DEFEATS_UNRESOLVED",
                    severity="info" if temporal else "review",
                    status="resolved_temporal" if temporal else "unresolved",
                    entity_ids=[item for item in pair if item],
                    fact_ids=[fact.fact_id for fact in group],
                )
            )
    return conflicts
