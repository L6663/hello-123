"""Focused Character Engine contracts for Stage 4.

The engine deliberately models fewer characters at greater reliability. Core
and important characters may receive evidence-bound temporal records;
placeholders remain minimal; mention-only surfaces stay outside the canonical
Character Project.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Final, Iterable, Mapping, Sequence

CHARACTER_ENGINE_VERSION: Final = "tkr-character-engine-v1"
CHARACTER_SCHEMA_VERSION: Final = "tkr-focused-character-v1"
CHARACTER_ATTRIBUTE_SCHEMA_VERSION: Final = "tkr-character-attribute-v1"
CHARACTER_STATE_SCHEMA_VERSION: Final = "tkr-character-state-v1"
CHARACTER_RELATIONSHIP_SCHEMA_VERSION: Final = "tkr-character-relationship-v1"
CHARACTER_EVENT_LINK_SCHEMA_VERSION: Final = "tkr-character-event-link-v1"
CHARACTER_FINDING_SCHEMA_VERSION: Final = "tkr-character-finding-v1"
CHARACTER_REPORT_SCHEMA_VERSION: Final = "tkr-character-graph-report-v1"

_SCOPES: Final = frozenset({"core", "important", "placeholder"})
_SELECTION_REASONS: Final = frozenset(
    {
        "main_plot_driver",
        "core_character_transformation",
        "major_event_cause_or_resolution",
        "major_faction_authority_or_collapse",
        "world_state_or_central_artifact_impact",
    }
)
_ATTRIBUTE_TYPES: Final = frozenset(
    {"identity", "role", "goal", "ability", "limitation", "choice", "arc"}
)
_PLACEHOLDER_ATTRIBUTE_TYPES: Final = frozenset({"identity", "role"})
_EVENT_ROLES: Final = frozenset(
    {
        "participant",
        "causes",
        "enables",
        "chooses",
        "transformed_by",
        "suffers_consequence",
        "resolves",
    }
)
_ACTIVE = frozenset({"active", "contested"})


class CharacterEngineError(ValueError):
    """Raised when a focused character record violates scope or evidence rules."""


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\0".join(
        json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if isinstance(part, (dict, list, tuple))
        else str(part)
        for part in parts
    )
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:32]


def _text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CharacterEngineError(f"{name} must be a string")
    if not allow_empty and not value:
        raise CharacterEngineError(f"{name} must be non-empty")
    return value


def _position(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CharacterEngineError(f"{name} must be a non-negative integer")
    return value


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CharacterEngineError("confidence must be numeric")
    cooked = float(value)
    if not 0.0 <= cooked <= 1.0:
        raise CharacterEngineError("confidence must be between zero and one")
    return cooked


def _unique(values: Sequence[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise CharacterEngineError(f"{name} must be unique")
    for value in values:
        _text(value, name)


def _interval(start: int, end: int) -> None:
    if end < start:
        raise CharacterEngineError("temporal interval ends before it starts")


def _tier_contract(
    tier: str,
    assertion_ids: Sequence[str],
    evidence_anchor_ids: Sequence[str],
    supporting_ids: Sequence[str],
    limitations: Sequence[str],
    attribution: str,
) -> None:
    if tier not in {"A", "B", "C"}:
        raise CharacterEngineError("tier must be A, B, or C")
    if tier == "A":
        if not assertion_ids or not evidence_anchor_ids:
            raise CharacterEngineError("tier A record requires assertions and exact evidence")
        if attribution not in {
            "source_explicit",
            "source_direct_event",
            "source_direct_dialogue",
        }:
            raise CharacterEngineError("tier A attribution is invalid")
    elif tier == "B":
        if len(assertion_ids) < 2 and len(supporting_ids) < 2:
            raise CharacterEngineError("tier B record requires multiple independent supports")
        if attribution != "cross_evidence_synthesis":
            raise CharacterEngineError("tier B record must be synthesis")
    else:
        if not (assertion_ids or supporting_ids):
            raise CharacterEngineError("tier C record requires supporting material")
        if not limitations:
            raise CharacterEngineError("tier C record requires limitations")
        if attribution != "model_interpretation":
            raise CharacterEngineError("tier C record must be model interpretation")


@dataclass(frozen=True, slots=True)
class FocusedCharacter:
    schema_version: str
    character_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    scope: str
    selection_reasons: tuple[str, ...]
    first_chapter_id: str
    last_chapter_id: str
    first_position: int
    last_position: int
    evidence_anchor_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    review_status: str

    def __post_init__(self) -> None:
        if self.schema_version != CHARACTER_SCHEMA_VERSION:
            raise CharacterEngineError("character schema version mismatch")
        for name in (
            "character_id",
            "canonical_name",
            "first_chapter_id",
            "last_chapter_id",
            "review_status",
        ):
            _text(getattr(self, name), name)
        if self.scope not in _SCOPES:
            raise CharacterEngineError("unsupported character scope")
        for name in ("aliases", "selection_reasons", "evidence_anchor_ids", "limitations"):
            _unique(getattr(self, name), name)
        if self.canonical_name not in self.aliases:
            raise CharacterEngineError("canonical name must be included in aliases")
        if any(value not in _SELECTION_REASONS for value in self.selection_reasons):
            raise CharacterEngineError("unsupported character selection reason")
        first = _position(self.first_position, "first_position")
        last = _position(self.last_position, "last_position")
        _interval(first, last)
        if self.review_status not in {"active", "contested", "review_only", "superseded"}:
            raise CharacterEngineError("unsupported character review status")
        if self.review_status in _ACTIVE:
            if not self.evidence_anchor_ids:
                raise CharacterEngineError("active character requires exact evidence")
            if self.scope in {"core", "important"} and not self.selection_reasons:
                raise CharacterEngineError("core/important character requires material-impact selection reason")
            if self.scope == "placeholder" and self.selection_reasons:
                raise CharacterEngineError("placeholder cannot claim major-impact selection reasons")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("aliases", "selection_reasons", "evidence_anchor_ids", "limitations"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class CharacterAttribute:
    schema_version: str
    attribute_id: str
    character_id: str
    character_scope: str
    attribute_type: str
    tier: str
    value: str
    start_chapter_id: str
    end_chapter_id: str
    start_position: int
    end_position: int
    assertion_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    supporting_attribute_ids: tuple[str, ...]
    confidence: float
    limitations: tuple[str, ...]
    attribution: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != CHARACTER_ATTRIBUTE_SCHEMA_VERSION:
            raise CharacterEngineError("character attribute schema version mismatch")
        for name in (
            "attribute_id",
            "character_id",
            "value",
            "start_chapter_id",
            "end_chapter_id",
            "attribution",
            "status",
        ):
            _text(getattr(self, name), name)
        if self.character_scope not in _SCOPES:
            raise CharacterEngineError("unsupported character scope")
        if self.attribute_type not in _ATTRIBUTE_TYPES:
            raise CharacterEngineError("unsupported character attribute type")
        if self.character_scope == "placeholder" and self.attribute_type not in _PLACEHOLDER_ATTRIBUTE_TYPES:
            raise CharacterEngineError("placeholder cannot receive deep character attributes")
        if self.character_scope == "placeholder" and self.tier != "A":
            raise CharacterEngineError("placeholder attributes must remain explicit A-grade records")
        if self.attribute_type == "arc" and self.character_scope != "core":
            raise CharacterEngineError("character arc records are limited to core characters")
        for name in (
            "assertion_ids",
            "evidence_anchor_ids",
            "supporting_attribute_ids",
            "limitations",
        ):
            _unique(getattr(self, name), name)
        start = _position(self.start_position, "start_position")
        end = _position(self.end_position, "end_position")
        _interval(start, end)
        _confidence(self.confidence)
        _tier_contract(
            self.tier,
            self.assertion_ids,
            self.evidence_anchor_ids,
            self.supporting_attribute_ids,
            self.limitations,
            self.attribution,
        )
        if self.status not in {"active", "contested", "review_only", "superseded"}:
            raise CharacterEngineError("unsupported character attribute status")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in (
            "assertion_ids",
            "evidence_anchor_ids",
            "supporting_attribute_ids",
            "limitations",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class CharacterState:
    schema_version: str
    state_id: str
    character_id: str
    state_type: str
    state_value: str
    start_chapter_id: str
    end_chapter_id: str
    start_position: int
    end_position: int
    tier: str
    assertion_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    confidence: float
    limitations: tuple[str, ...]
    attribution: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != CHARACTER_STATE_SCHEMA_VERSION:
            raise CharacterEngineError("character state schema version mismatch")
        for name in (
            "state_id",
            "character_id",
            "state_type",
            "state_value",
            "start_chapter_id",
            "end_chapter_id",
            "attribution",
            "status",
        ):
            _text(getattr(self, name), name)
        if self.tier not in {"A", "B"}:
            raise CharacterEngineError("character states cannot be C-grade interpretation")
        for name in ("assertion_ids", "evidence_anchor_ids", "limitations"):
            _unique(getattr(self, name), name)
        start = _position(self.start_position, "start_position")
        end = _position(self.end_position, "end_position")
        _interval(start, end)
        _confidence(self.confidence)
        _tier_contract(
            self.tier,
            self.assertion_ids,
            self.evidence_anchor_ids,
            (),
            self.limitations,
            self.attribution,
        )
        if self.status not in {"active", "contested", "review_only", "superseded"}:
            raise CharacterEngineError("unsupported character state status")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["assertion_ids"] = list(self.assertion_ids)
        payload["evidence_anchor_ids"] = list(self.evidence_anchor_ids)
        payload["limitations"] = list(self.limitations)
        return payload


@dataclass(frozen=True, slots=True)
class CharacterRelationship:
    schema_version: str
    relationship_id: str
    subject_character_id: str
    object_character_id: str
    relation_type: str
    tier: str
    start_chapter_id: str
    end_chapter_id: str
    start_position: int
    end_position: int
    change_event_ids: tuple[str, ...]
    assertion_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    supporting_relationship_ids: tuple[str, ...]
    confidence: float
    limitations: tuple[str, ...]
    attribution: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != CHARACTER_RELATIONSHIP_SCHEMA_VERSION:
            raise CharacterEngineError("character relationship schema version mismatch")
        for name in (
            "relationship_id",
            "subject_character_id",
            "object_character_id",
            "relation_type",
            "start_chapter_id",
            "end_chapter_id",
            "attribution",
            "status",
        ):
            _text(getattr(self, name), name)
        if self.subject_character_id == self.object_character_id:
            raise CharacterEngineError("character relationship cannot be self-referential")
        for name in (
            "change_event_ids",
            "assertion_ids",
            "evidence_anchor_ids",
            "supporting_relationship_ids",
            "limitations",
        ):
            _unique(getattr(self, name), name)
        start = _position(self.start_position, "start_position")
        end = _position(self.end_position, "end_position")
        _interval(start, end)
        _confidence(self.confidence)
        _tier_contract(
            self.tier,
            self.assertion_ids,
            self.evidence_anchor_ids,
            self.supporting_relationship_ids,
            self.limitations,
            self.attribution,
        )
        if self.status not in {"active", "contested", "review_only", "superseded"}:
            raise CharacterEngineError("unsupported character relationship status")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in (
            "change_event_ids",
            "assertion_ids",
            "evidence_anchor_ids",
            "supporting_relationship_ids",
            "limitations",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class CharacterEventLink:
    schema_version: str
    link_id: str
    character_id: str
    event_id: str
    role: str
    tier: str
    assertion_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    confidence: float
    limitations: tuple[str, ...]
    attribution: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != CHARACTER_EVENT_LINK_SCHEMA_VERSION:
            raise CharacterEngineError("character event link schema version mismatch")
        for name in ("link_id", "character_id", "event_id", "attribution", "status"):
            _text(getattr(self, name), name)
        if self.role not in _EVENT_ROLES:
            raise CharacterEngineError("unsupported character event role")
        for name in ("assertion_ids", "evidence_anchor_ids", "limitations"):
            _unique(getattr(self, name), name)
        _confidence(self.confidence)
        _tier_contract(
            self.tier,
            self.assertion_ids,
            self.evidence_anchor_ids,
            (),
            self.limitations,
            self.attribution,
        )
        if self.status not in {"active", "contested", "review_only", "superseded"}:
            raise CharacterEngineError("unsupported character event link status")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["assertion_ids"] = list(self.assertion_ids)
        payload["evidence_anchor_ids"] = list(self.evidence_anchor_ids)
        payload["limitations"] = list(self.limitations)
        return payload


@dataclass(frozen=True, slots=True)
class CharacterFinding:
    schema_version: str
    finding_id: str
    rule_id: str
    severity: str
    character_ids: tuple[str, ...]
    record_ids: tuple[str, ...]
    signals: tuple[str, ...]
    recommended_action: str

    def __post_init__(self) -> None:
        if self.schema_version != CHARACTER_FINDING_SCHEMA_VERSION:
            raise CharacterEngineError("character finding schema version mismatch")
        for name in ("finding_id", "rule_id", "severity", "recommended_action"):
            _text(getattr(self, name), name)
        if self.severity not in {"low", "medium", "high"}:
            raise CharacterEngineError("unsupported character finding severity")
        for name in ("character_ids", "record_ids", "signals"):
            _unique(getattr(self, name), name)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["character_ids"] = list(self.character_ids)
        payload["record_ids"] = list(self.record_ids)
        payload["signals"] = list(self.signals)
        return payload


@dataclass(frozen=True, slots=True)
class CharacterGraphReport:
    schema_version: str
    character_engine_version: str
    character_count: int
    core_count: int
    important_count: int
    placeholder_count: int
    attribute_count: int
    state_count: int
    relationship_count: int
    event_link_count: int
    finding_count: int
    unsupported_reference_count: int
    temporal_conflict_count: int
    graph_valid: bool
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != CHARACTER_REPORT_SCHEMA_VERSION:
            raise CharacterEngineError("character report schema mismatch")
        if self.character_engine_version != CHARACTER_ENGINE_VERSION:
            raise CharacterEngineError("character engine version mismatch")
        for name in (
            "character_count", "core_count", "important_count", "placeholder_count",
            "attribute_count", "state_count", "relationship_count", "event_link_count",
            "finding_count", "unsupported_reference_count", "temporal_conflict_count",
        ):
            _position(getattr(self, name), name)
        if any((self.project_acceptance_performed, self.may_accept_project, self.may_release, self.may_freeze)):
            raise CharacterEngineError("character report cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CharacterGraph:
    characters: tuple[FocusedCharacter, ...]
    attributes: tuple[CharacterAttribute, ...]
    states: tuple[CharacterState, ...]
    relationships: tuple[CharacterRelationship, ...]
    event_links: tuple[CharacterEventLink, ...]
    findings: tuple[CharacterFinding, ...]
    report: CharacterGraphReport


def character_id(canonical_name: str, first_chapter_id: str) -> str:
    return _stable_id("fch_", CHARACTER_SCHEMA_VERSION, canonical_name, first_chapter_id)


def _finding(
    rule_id: str,
    severity: str,
    character_ids: Iterable[str],
    record_ids: Iterable[str],
    signals: Iterable[str],
    action: str,
) -> CharacterFinding:
    characters = tuple(sorted(set(character_ids)))
    records = tuple(sorted(set(record_ids)))
    signal_tuple = tuple(signals)
    return CharacterFinding(
        CHARACTER_FINDING_SCHEMA_VERSION,
        _stable_id("cff_", CHARACTER_FINDING_SCHEMA_VERSION, rule_id, characters, records, signal_tuple),
        rule_id,
        severity,
        characters,
        records,
        signal_tuple,
        action,
    )


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and b_start <= a_end


def build_character_graph(
    characters: Sequence[FocusedCharacter],
    attributes: Sequence[CharacterAttribute],
    states: Sequence[CharacterState],
    relationships: Sequence[CharacterRelationship],
    event_links: Sequence[CharacterEventLink],
    *,
    known_assertion_ids: Iterable[str],
    known_evidence_anchor_ids: Iterable[str],
    known_event_ids: Iterable[str],
    event_graph_valid: bool,
) -> CharacterGraph:
    character_by_id = {item.character_id: item for item in characters}
    attribute_by_id = {item.attribute_id: item for item in attributes}
    state_by_id = {item.state_id: item for item in states}
    relationship_by_id = {item.relationship_id: item for item in relationships}
    link_by_id = {item.link_id: item for item in event_links}
    for label, records, mapping in (
        ("character", characters, character_by_id),
        ("attribute", attributes, attribute_by_id),
        ("state", states, state_by_id),
        ("relationship", relationships, relationship_by_id),
        ("event link", event_links, link_by_id),
    ):
        if len(records) != len(mapping):
            raise CharacterEngineError(f"duplicate {label} identifiers")
    assertion_ids = set(known_assertion_ids)
    evidence_ids = set(known_evidence_anchor_ids)
    event_ids = set(known_event_ids)
    findings: list[CharacterFinding] = []
    unsupported = 0
    temporal_conflicts = 0

    alias_map: dict[str, list[str]] = {}
    for character in characters:
        for alias in character.aliases:
            alias_map.setdefault(alias, []).append(character.character_id)
        unknown_evidence = sorted(set(character.evidence_anchor_ids) - evidence_ids)
        if unknown_evidence:
            unsupported += 1
            findings.append(_finding(
                "CHARACTER_UNKNOWN_EVIDENCE", "high", (character.character_id,), (),
                tuple(f"unknown_evidence={value}" for value in unknown_evidence),
                "reject_character_until_evidence_is_verified",
            ))
    for alias, ids in alias_map.items():
        if len(ids) > 1:
            findings.append(_finding(
                "CHARACTER_ALIAS_COLLISION", "high", ids, (), (f"alias={alias}",),
                "review_identity_merge_or_keep_characters_separate",
            ))

    def validate_support(
        character_id_value: str,
        record_id: str,
        assertions: Sequence[str],
        evidence: Sequence[str],
        support_records: Sequence[str] = (),
    ) -> None:
        nonlocal unsupported
        unknown_assertions = sorted(set(assertions) - assertion_ids)
        unknown_evidence = sorted(set(evidence) - evidence_ids)
        unknown_supports = sorted(set(support_records) - set(attribute_by_id) - set(relationship_by_id))
        if unknown_assertions or unknown_evidence or unknown_supports:
            unsupported += 1
            findings.append(_finding(
                "CHARACTER_RECORD_UNKNOWN_SUPPORT", "high", (character_id_value,), (record_id,),
                (
                    *tuple(f"unknown_assertion={value}" for value in unknown_assertions),
                    *tuple(f"unknown_evidence={value}" for value in unknown_evidence),
                    *tuple(f"unknown_record={value}" for value in unknown_supports),
                ),
                "reject_record_until_support_is_verified",
            ))

    for item in attributes:
        character = character_by_id.get(item.character_id)
        if character is None:
            unsupported += 1
            findings.append(_finding(
                "ATTRIBUTE_UNKNOWN_CHARACTER", "high", (item.character_id,), (item.attribute_id,), (),
                "reject_attribute_until_character_exists",
            ))
            continue
        if item.character_scope != character.scope:
            findings.append(_finding(
                "ATTRIBUTE_SCOPE_BINDING_MISMATCH", "high", (character.character_id,), (item.attribute_id,),
                (f"stored_scope={item.character_scope}", f"actual_scope={character.scope}"),
                "rebind_attribute_to_character_scope",
            ))
        validate_support(
            item.character_id, item.attribute_id, item.assertion_ids,
            item.evidence_anchor_ids, item.supporting_attribute_ids,
        )
        if item.tier == "B":
            tiers = {
                attribute_by_id[value].tier
                for value in item.supporting_attribute_ids if value in attribute_by_id
            }
            if tiers and tiers != {"A"}:
                findings.append(_finding(
                    "B_ATTRIBUTE_SUPPORT_TIER_INVALID", "high", (item.character_id,), (item.attribute_id,),
                    tuple(f"support_tier={value}" for value in sorted(tiers)),
                    "bind_B_attribute_to_independent_A_attributes",
                ))
        if item.tier == "C" and any(
            attribute_by_id[value].tier == "C"
            for value in item.supporting_attribute_ids if value in attribute_by_id
        ):
            findings.append(_finding(
                "C_ATTRIBUTE_SELF_REINFORCING_INTERPRETATION", "high", (item.character_id,),
                (item.attribute_id,), (), "bind_interpretation_to_A_or_B_support",
            ))

    for item in states:
        if item.character_id not in character_by_id:
            unsupported += 1
            findings.append(_finding(
                "STATE_UNKNOWN_CHARACTER", "high", (item.character_id,), (item.state_id,), (),
                "reject_state_until_character_exists",
            ))
        validate_support(item.character_id, item.state_id, item.assertion_ids, item.evidence_anchor_ids)
    by_character_state: dict[tuple[str, str], list[CharacterState]] = {}
    for item in states:
        if item.status in _ACTIVE:
            by_character_state.setdefault((item.character_id, item.state_type), []).append(item)
    for (character_id_value, state_type), rows in by_character_state.items():
        ordered = sorted(rows, key=lambda item: (item.start_position, item.end_position, item.state_id))
        for index, first in enumerate(ordered):
            for second in ordered[index + 1:]:
                if second.start_position > first.end_position:
                    break
                if first.state_value != second.state_value and _overlaps(
                    first.start_position, first.end_position, second.start_position, second.end_position
                ):
                    temporal_conflicts += 1
                    findings.append(_finding(
                        "OVERLAPPING_CONTRADICTORY_CHARACTER_STATES", "high",
                        (character_id_value,), (first.state_id, second.state_id),
                        (f"state_type={state_type}", f"first={first.state_value}", f"second={second.state_value}"),
                        "review_state_boundaries_or_mark_contested",
                    ))

    for item in relationships:
        subject = character_by_id.get(item.subject_character_id)
        object_character = character_by_id.get(item.object_character_id)
        if subject is None or object_character is None:
            unsupported += 1
            findings.append(_finding(
                "RELATIONSHIP_UNKNOWN_CHARACTER", "high",
                (item.subject_character_id, item.object_character_id), (item.relationship_id,), (),
                "reject_relationship_until_both_characters_exist",
            ))
        elif "placeholder" in {subject.scope, object_character.scope}:
            findings.append(_finding(
                "PLACEHOLDER_DEEP_RELATIONSHIP", "high",
                (subject.character_id, object_character.character_id), (item.relationship_id,), (),
                "remove_deep_relationship_or_promote_with_material_impact_evidence",
            ))
        unknown_events = sorted(set(item.change_event_ids) - event_ids)
        if unknown_events:
            unsupported += 1
            findings.append(_finding(
                "RELATIONSHIP_UNKNOWN_CHANGE_EVENT", "high",
                (item.subject_character_id, item.object_character_id), (item.relationship_id,),
                tuple(f"unknown_event={value}" for value in unknown_events),
                "reject_relationship_change_until_event_exists",
            ))
        validate_support(
            item.subject_character_id, item.relationship_id, item.assertion_ids,
            item.evidence_anchor_ids, item.supporting_relationship_ids,
        )

    for item in event_links:
        character = character_by_id.get(item.character_id)
        if character is None:
            unsupported += 1
            findings.append(_finding(
                "EVENT_LINK_UNKNOWN_CHARACTER", "high", (item.character_id,), (item.link_id,), (),
                "reject_event_link_until_character_exists",
            ))
        if item.event_id not in event_ids:
            unsupported += 1
            findings.append(_finding(
                "EVENT_LINK_UNKNOWN_EVENT", "high", (item.character_id,), (item.link_id,),
                (f"unknown_event={item.event_id}",), "reject_event_link_until_event_exists",
            ))
        if not event_graph_valid and item.status in _ACTIVE:
            findings.append(_finding(
                "ACTIVE_LINK_TO_REVIEW_REQUIRED_EVENT_GRAPH", "high", (item.character_id,),
                (item.link_id,), (f"event_id={item.event_id}",),
                "mark_link_review_only_until_Event_Project_is_valid",
            ))
        if character is not None and character.scope == "placeholder" and item.role != "participant":
            findings.append(_finding(
                "PLACEHOLDER_DEEP_EVENT_ROLE", "high", (item.character_id,), (item.link_id,),
                (f"role={item.role}",), "limit_placeholder_to_minimal_participation_record",
            ))
        validate_support(item.character_id, item.link_id, item.assertion_ids, item.evidence_anchor_ids)

    findings = sorted(
        {item.finding_id: item for item in findings}.values(),
        key=lambda item: (item.rule_id, item.finding_id),
    )
    report = CharacterGraphReport(
        CHARACTER_REPORT_SCHEMA_VERSION,
        CHARACTER_ENGINE_VERSION,
        len(characters),
        sum(item.scope == "core" for item in characters),
        sum(item.scope == "important" for item in characters),
        sum(item.scope == "placeholder" for item in characters),
        len(attributes),
        len(states),
        len(relationships),
        len(event_links),
        len(findings),
        unsupported,
        temporal_conflicts,
        not any(item.severity == "high" for item in findings),
    )
    return CharacterGraph(
        tuple(sorted(characters, key=lambda item: (item.first_position, item.character_id))),
        tuple(sorted(attributes, key=lambda item: (item.character_id, item.start_position, item.attribute_id))),
        tuple(sorted(states, key=lambda item: (item.character_id, item.start_position, item.state_id))),
        tuple(sorted(relationships, key=lambda item: (item.start_position, item.relationship_id))),
        tuple(sorted(event_links, key=lambda item: (item.character_id, item.event_id, item.link_id))),
        tuple(findings),
        report,
    )


__all__ = [
    "CHARACTER_ATTRIBUTE_SCHEMA_VERSION",
    "CHARACTER_ENGINE_VERSION",
    "CHARACTER_EVENT_LINK_SCHEMA_VERSION",
    "CHARACTER_FINDING_SCHEMA_VERSION",
    "CHARACTER_RELATIONSHIP_SCHEMA_VERSION",
    "CHARACTER_REPORT_SCHEMA_VERSION",
    "CHARACTER_SCHEMA_VERSION",
    "CHARACTER_STATE_SCHEMA_VERSION",
    "CharacterAttribute",
    "CharacterEngineError",
    "CharacterEventLink",
    "CharacterFinding",
    "CharacterGraph",
    "CharacterGraphReport",
    "CharacterRelationship",
    "CharacterState",
    "FocusedCharacter",
    "build_character_graph",
    "character_id",
]
