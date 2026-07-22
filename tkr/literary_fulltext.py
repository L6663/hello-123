"""Full-text, dialogue, and review-only minor-entity indexing for Stage 7.2.

This module expands literary retrieval without weakening the epistemic contract:

* every trusted chapter body is segmented into exact, hash-bound passages;
* all aliases of already accepted entities are scanned across the full body;
* dialogue spans are recorded with conservative speaker resolution;
* unknown people, abilities, places, and factions become review candidates and
  source-bound model tasks only -- never automatic A-grade facts.

All identifiers are deterministic.  Contaminated or review-only chapters are not
used for canonical full-text indexing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import re
from typing import Final, Iterable, Mapping, Sequence

from .literary_models import (
    ChapterRecord,
    EvidenceAnchor,
    LiteraryEntity,
    evidence_anchor_id,
    stable_id,
)

FULLTEXT_SYSTEM_VERSION: Final = "tkr-literary-fulltext-v1"
DIALOGUE_SCHEMA_VERSION: Final = "tkr-literary-dialogue-v1"
MENTION_CANDIDATE_SCHEMA_VERSION: Final = "tkr-literary-mention-candidate-v1"
ENTITY_TASK_SCHEMA_VERSION: Final = "tkr-literary-entity-task-v1"

_MAX_PASSAGE_CHARS = 1200
_MAX_DIALOGUE_CHARS = 2000
_MAX_ALIAS_LENGTH = 32

_CJK = "\u3400-\u4dbf\u4e00-\u9fff"
_NAME_CHARS = rf"[{_CJK}A-Za-z0-9·•・]"

_STOP_SURFACES: Final = frozenset(
    {
        "众人",
        "有人",
        "此人",
        "那人",
        "一人",
        "两人",
        "三人",
        "男子",
        "女子",
        "少年",
        "少女",
        "老人",
        "老者",
        "对方",
        "自己",
        "他们",
        "她们",
        "我们",
        "你们",
        "这里",
        "那里",
        "此地",
        "此处",
        "前方",
        "后方",
        "声音",
        "此时",
        "这时",
        "忽然",
        "随后",
        "接着",
        "顿时",
        "原来",
        "只见",
    }
)

_SPEECH_VERBS = (
    "说道",
    "说",
    "问道",
    "问",
    "答道",
    "答",
    "喝道",
    "喝",
    "喊道",
    "喊",
    "叫道",
    "叫",
    "笑道",
    "叹道",
    "低声道",
    "沉声道",
    "冷声道",
    "朗声道",
    "厉声道",
    "缓缓道",
)

_DIALOGUE_PATTERNS: Final = (
    re.compile(r"“[^”\r\n]{1," + str(_MAX_DIALOGUE_CHARS) + r"}”"),
    re.compile(r"「[^」\r\n]{1," + str(_MAX_DIALOGUE_CHARS) + r"}」"),
    re.compile(r"『[^』\r\n]{1," + str(_MAX_DIALOGUE_CHARS) + r"}』"),
    re.compile(r"‘[^’\r\n]{1," + str(_MAX_DIALOGUE_CHARS) + r"}’"),
    re.compile(r'"[^"\r\n]{1,' + str(_MAX_DIALOGUE_CHARS) + r'}"'),
)

_ABILITY_QUOTED = re.compile(
    rf"(?:施展|使出|运起|催动|发动|祭出|施放|打出|运转|结出|施以)"
    rf"(?:了|出|起)?\s*[“「『《](?P<surface>{_NAME_CHARS}{{2,16}})[”」』》]"
)
_ABILITY_PLAIN = re.compile(
    rf"(?:施展|使出|运起|催动|发动|祭出|施放|打出|运转|结出|施以)"
    rf"(?:了|出|起)?\s*(?P<surface>[{_CJK}]{{2,8}})"
    rf"(?=[，。！？；、\s]|攻向|击向|迎向|轰向|斩向)"
)
_PLACE_PATTERN = re.compile(
    rf"(?:来到|前往|赶往|进入|抵达|返回|位于|坐落于|离开|逃往)"
    rf"(?P<surface>[{_CJK}]{{2,10}})(?=[，。！？；、\s])"
)
_FACTION_PATTERN = re.compile(
    rf"(?:加入|投奔|隶属|出身于|拜入|效忠于|归顺|脱离)"
    rf"(?P<surface>[{_CJK}]{{2,12}})(?=[，。！？；、\s])"
)
_SPEAKER_CANDIDATE = re.compile(
    rf"(?<![{_CJK}A-Za-z0-9])(?P<surface>{_NAME_CHARS}{{2,8}})"
    rf"(?:低声|沉声|冷声|朗声|厉声|大声|轻声|缓缓|笑着)?"
    rf"(?:说道|问道|答道|喝道|喊道|叫道|笑道|叹道)"
)


class LiteraryFullTextError(ValueError):
    """Raised when a full-text literary record violates its source contract."""


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise LiteraryFullTextError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise LiteraryFullTextError(f"{name} must be non-empty")
    return cleaned


def _require_span(start: object, end: object, name: str) -> tuple[int, int]:
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start < 0
        or end <= start
    ):
        raise LiteraryFullTextError(f"{name} span is invalid")
    return start, end


def _dedupe_text(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DialogueSpan:
    schema_version: str
    dialogue_id: str
    source_id: str
    source_sha256: str
    unit_id: str
    chapter_id: str
    volume_ordinal: int | None
    chapter_ordinal: int | None
    start_char: int
    end_char: int
    dialogue_text: str
    dialogue_sha256: str
    speaker_surface: str
    speaker_entity_id: str | None
    speaker_resolution: str
    review_status: str

    def __post_init__(self) -> None:
        if self.schema_version != DIALOGUE_SCHEMA_VERSION:
            raise LiteraryFullTextError("dialogue schema version mismatch")
        for name in (
            "dialogue_id",
            "source_id",
            "source_sha256",
            "unit_id",
            "chapter_id",
            "dialogue_text",
            "dialogue_sha256",
            "speaker_resolution",
            "review_status",
        ):
            _require_text(getattr(self, name), name)
        _require_span(self.start_char, self.end_char, "dialogue")
        if sha256(self.dialogue_text.encode("utf-8")).hexdigest() != self.dialogue_sha256:
            raise LiteraryFullTextError("dialogue text SHA-256 mismatch")
        if self.speaker_resolution not in {
            "resolved_unique_alias",
            "ambiguous_alias",
            "unresolved_candidate",
            "not_detected",
        }:
            raise LiteraryFullTextError("unsupported speaker resolution")
        if self.speaker_resolution == "resolved_unique_alias" and not self.speaker_entity_id:
            raise LiteraryFullTextError("resolved dialogue requires speaker_entity_id")
        if self.speaker_entity_id is not None:
            _require_text(self.speaker_entity_id, "speaker_entity_id")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MentionCandidate:
    schema_version: str
    candidate_id: str
    candidate_type: str
    surface: str
    normalized_surface: str
    source_id: str
    source_sha256: str
    unit_id: str
    chapter_id: str
    volume_ordinal: int | None
    chapter_ordinal: int | None
    start_char: int
    end_char: int
    evidence_text: str
    evidence_sha256: str
    rule_id: str
    confidence: float
    known_entity_ids: tuple[str, ...]
    review_status: str

    def __post_init__(self) -> None:
        if self.schema_version != MENTION_CANDIDATE_SCHEMA_VERSION:
            raise LiteraryFullTextError("mention candidate schema version mismatch")
        for name in (
            "candidate_id",
            "candidate_type",
            "surface",
            "normalized_surface",
            "source_id",
            "source_sha256",
            "unit_id",
            "chapter_id",
            "evidence_text",
            "evidence_sha256",
            "rule_id",
            "review_status",
        ):
            _require_text(getattr(self, name), name)
        if self.candidate_type not in {
            "person",
            "ability",
            "place",
            "faction",
            "ambiguous_known_alias",
        }:
            raise LiteraryFullTextError("unsupported candidate_type")
        _require_span(self.start_char, self.end_char, "candidate")
        if sha256(self.evidence_text.encode("utf-8")).hexdigest() != self.evidence_sha256:
            raise LiteraryFullTextError("candidate evidence SHA-256 mismatch")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise LiteraryFullTextError("candidate confidence must be numeric")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise LiteraryFullTextError("candidate confidence must be between 0 and 1")
        if len(self.known_entity_ids) != len(set(self.known_entity_ids)):
            raise LiteraryFullTextError("known_entity_ids must be unique")
        if self.review_status != "candidate_only":
            raise LiteraryFullTextError("mention candidates cannot be accepted automatically")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["known_entity_ids"] = list(self.known_entity_ids)
        return payload


@dataclass(frozen=True, slots=True)
class EntityReviewTask:
    schema_version: str
    task_id: str
    candidate_type: str
    surface: str
    normalized_surface: str
    candidate_ids: tuple[str, ...]
    chapter_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
    allowed_decisions: tuple[str, ...]
    forbidden_authority: tuple[str, ...]
    task_status: str

    def __post_init__(self) -> None:
        if self.schema_version != ENTITY_TASK_SCHEMA_VERSION:
            raise LiteraryFullTextError("entity task schema version mismatch")
        for name in (
            "task_id",
            "candidate_type",
            "surface",
            "normalized_surface",
            "task_status",
        ):
            _require_text(getattr(self, name), name)
        if not self.candidate_ids or not self.chapter_ids or not self.evidence_anchor_ids:
            raise LiteraryFullTextError("entity task requires candidates, chapters, and evidence")
        if set(self.allowed_decisions) != {"accept_new_entity", "link_existing_entity", "reject_candidate"}:
            raise LiteraryFullTextError("entity task decisions are not closed")
        required_forbidden = {
            "accept_fact",
            "promote_to_tier_A",
            "index_without_validation",
            "accept_project",
            "freeze_project",
        }
        if not required_forbidden.issubset(set(self.forbidden_authority)):
            raise LiteraryFullTextError("entity task omits required authority restrictions")
        if self.task_status != "pending_review":
            raise LiteraryFullTextError("entity task must remain pending review")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in (
            "candidate_ids",
            "chapter_ids",
            "evidence_anchor_ids",
            "allowed_decisions",
            "forbidden_authority",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class FullTextAugmentation:
    passage_anchors: tuple[EvidenceAnchor, ...]
    mention_anchors: tuple[EvidenceAnchor, ...]
    updated_entities: tuple[LiteraryEntity, ...]
    dialogues: tuple[DialogueSpan, ...]
    candidates: tuple[MentionCandidate, ...]
    review_tasks: tuple[EntityReviewTask, ...]
    trusted_chapter_count: int
    skipped_chapter_count: int
    indexed_character_count: int
    known_alias_occurrence_count: int
    ambiguous_alias_occurrence_count: int


class _AliasTrie:
    __slots__ = ("root", "max_length")

    def __init__(self, alias_to_entities: Mapping[str, tuple[str, ...]]) -> None:
        root: dict[str, object] = {}
        maximum = 0
        for alias in sorted(alias_to_entities, key=lambda item: (len(item), item)):
            if not alias or len(alias) > _MAX_ALIAS_LENGTH:
                continue
            maximum = max(maximum, len(alias))
            node = root
            for character in alias:
                child = node.setdefault(character, {})
                if not isinstance(child, dict):
                    raise LiteraryFullTextError("alias trie collision")
                node = child
            node[""] = (alias, alias_to_entities[alias])
        self.root = root
        self.max_length = maximum

    def find(self, text: str, absolute_start: int) -> Iterable[tuple[int, int, str, tuple[str, ...]]]:
        if not self.root:
            return
        for index, character in enumerate(text):
            node = self.root.get(character)
            if not isinstance(node, dict):
                continue
            cursor = index + 1
            terminal = node.get("")
            if isinstance(terminal, tuple):
                alias, entities = terminal
                yield absolute_start + index, absolute_start + cursor, alias, entities
            while cursor < len(text) and cursor - index < self.max_length:
                child = node.get(text[cursor])
                if not isinstance(child, dict):
                    break
                node = child
                cursor += 1
                terminal = node.get("")
                if isinstance(terminal, tuple):
                    alias, entities = terminal
                    yield absolute_start + index, absolute_start + cursor, alias, entities


def _anchor(
    source_text: str,
    chapter: ChapterRecord,
    start: int,
    end: int,
    role: str,
) -> EvidenceAnchor:
    if not chapter.start_char <= start < end <= chapter.end_char:
        raise LiteraryFullTextError("full-text anchor escaped chapter")
    text = source_text[start:end]
    digest = sha256(text.encode("utf-8")).hexdigest()
    return EvidenceAnchor(
        "tkr-literary-evidence-anchor-v1",
        evidence_anchor_id(chapter.source_sha256, chapter.unit_id, start, end, digest),
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
        text,
        digest,
        chapter.content_sha256,
        role,
        chapter.contamination_status,
    )


def _sentence_chunks(text: str, absolute_start: int) -> Iterable[tuple[int, int]]:
    """Yield exact non-whitespace chunks no larger than the passage ceiling."""

    cursor = 0
    length = len(text)
    while cursor < length:
        while cursor < length and text[cursor].isspace():
            cursor += 1
        if cursor >= length:
            break
        target = min(length, cursor + _MAX_PASSAGE_CHARS)
        if target < length:
            boundary = -1
            for index in range(target, max(cursor, target - 300), -1):
                if text[index - 1] in "。！？!?；;\n":
                    boundary = index
                    break
            if boundary > cursor:
                target = boundary
        end = target
        while end > cursor and text[end - 1].isspace():
            end -= 1
        if end > cursor:
            yield absolute_start + cursor, absolute_start + end
        cursor = target


def _passage_spans(source_text: str, chapter: ChapterRecord) -> Iterable[tuple[int, int]]:
    body = source_text[chapter.body_start_char:chapter.body_end_char]
    line_start = 0
    for match in re.finditer(r"\r\n|\n|\r", body):
        line_end = match.start()
        line = body[line_start:line_end]
        yield from _sentence_chunks(line, chapter.body_start_char + line_start)
        line_start = match.end()
    yield from _sentence_chunks(body[line_start:], chapter.body_start_char + line_start)


def _normalize_surface(surface: str) -> str:
    return "".join(surface.casefold().split())


def _candidate(
    source_text: str,
    chapter: ChapterRecord,
    candidate_type: str,
    surface: str,
    start: int,
    end: int,
    rule_id: str,
    confidence: float,
    known_entity_ids: Sequence[str] = (),
) -> MentionCandidate | None:
    surface = surface.strip()
    if not surface or surface in _STOP_SURFACES:
        return None
    if surface.isdigit() or len(surface) < 2:
        return None
    if source_text[start:end] != surface:
        raise LiteraryFullTextError("candidate surface differs from source span")
    digest = sha256(surface.encode("utf-8")).hexdigest()
    identifier = stable_id(
        "lmc_",
        MENTION_CANDIDATE_SCHEMA_VERSION,
        chapter.source_sha256,
        chapter.unit_id,
        candidate_type,
        start,
        end,
        digest,
        rule_id,
    )
    return MentionCandidate(
        MENTION_CANDIDATE_SCHEMA_VERSION,
        identifier,
        candidate_type,
        surface,
        _normalize_surface(surface),
        chapter.source_id,
        chapter.source_sha256,
        chapter.unit_id,
        chapter.chapter_id,
        chapter.volume_ordinal,
        chapter.chapter_ordinal,
        start,
        end,
        surface,
        digest,
        rule_id,
        confidence,
        tuple(sorted(set(known_entity_ids))),
        "candidate_only",
    )


def _speaker_before(source_text: str, start: int) -> tuple[str, int, int] | None:
    window_start = max(0, start - 48)
    window = source_text[window_start:start]
    verb_union = "|".join(re.escape(item) for item in sorted(_SPEECH_VERBS, key=len, reverse=True))
    pattern = re.compile(
        rf"(?P<surface>{_NAME_CHARS}{{2,8}})(?:低声|沉声|冷声|朗声|厉声|大声|轻声|缓缓|笑着)?(?:{verb_union})[：:，,\s]*$"
    )
    match = pattern.search(window)
    if not match:
        return None
    surface = match.group("surface")
    absolute = window_start + match.start("surface")
    return surface, absolute, absolute + len(surface)


def _speaker_after(source_text: str, end: int) -> tuple[str, int, int] | None:
    window = source_text[end:end + 48]
    verb_union = "|".join(re.escape(item) for item in sorted(_SPEECH_VERBS, key=len, reverse=True))
    pattern = re.compile(
        rf"^[，,。\s]*(?P<surface>{_NAME_CHARS}{{2,8}})(?:低声|沉声|冷声|朗声|厉声|大声|轻声|缓缓|笑着)?(?:{verb_union})"
    )
    match = pattern.search(window)
    if not match:
        return None
    surface = match.group("surface")
    absolute = end + match.start("surface")
    return surface, absolute, absolute + len(surface)


def _dialogues(
    source_text: str,
    chapter: ChapterRecord,
    alias_to_entities: Mapping[str, tuple[str, ...]],
) -> tuple[list[DialogueSpan], list[MentionCandidate]]:
    body = source_text[chapter.body_start_char:chapter.body_end_char]
    seen: set[tuple[int, int]] = set()
    dialogues: list[DialogueSpan] = []
    candidates: list[MentionCandidate] = []
    for pattern in _DIALOGUE_PATTERNS:
        for match in pattern.finditer(body):
            start = chapter.body_start_char + match.start()
            end = chapter.body_start_char + match.end()
            if (start, end) in seen:
                continue
            seen.add((start, end))
            text = source_text[start:end]
            speaker = _speaker_before(source_text, start) or _speaker_after(source_text, end)
            surface = ""
            entity_id: str | None = None
            resolution = "not_detected"
            if speaker is not None:
                surface, speaker_start, speaker_end = speaker
                entity_ids = alias_to_entities.get(surface, ())
                if len(entity_ids) == 1:
                    entity_id = entity_ids[0]
                    resolution = "resolved_unique_alias"
                elif len(entity_ids) > 1:
                    resolution = "ambiguous_alias"
                    candidate = _candidate(
                        source_text,
                        chapter,
                        "ambiguous_known_alias",
                        surface,
                        speaker_start,
                        speaker_end,
                        "DIALOGUE_SPEAKER_AMBIGUOUS_ALIAS",
                        1.0,
                        entity_ids,
                    )
                    if candidate is not None:
                        candidates.append(candidate)
                else:
                    resolution = "unresolved_candidate"
                    candidate = _candidate(
                        source_text,
                        chapter,
                        "person",
                        surface,
                        speaker_start,
                        speaker_end,
                        "DIALOGUE_SPEAKER_CANDIDATE",
                        0.92,
                    )
                    if candidate is not None:
                        candidates.append(candidate)
            digest = sha256(text.encode("utf-8")).hexdigest()
            dialogues.append(
                DialogueSpan(
                    DIALOGUE_SCHEMA_VERSION,
                    stable_id(
                        "ldg_",
                        DIALOGUE_SCHEMA_VERSION,
                        chapter.source_sha256,
                        chapter.unit_id,
                        start,
                        end,
                        digest,
                    ),
                    chapter.source_id,
                    chapter.source_sha256,
                    chapter.unit_id,
                    chapter.chapter_id,
                    chapter.volume_ordinal,
                    chapter.chapter_ordinal,
                    start,
                    end,
                    text,
                    digest,
                    surface,
                    entity_id,
                    resolution,
                    "accepted_span" if resolution in {"resolved_unique_alias", "not_detected"} else "speaker_needs_review",
                )
            )
    return dialogues, candidates


def _rule_candidates(source_text: str, chapter: ChapterRecord) -> list[MentionCandidate]:
    body = source_text[chapter.body_start_char:chapter.body_end_char]
    result: list[MentionCandidate] = []
    rules = (
        (_ABILITY_QUOTED, "ability", "ABILITY_QUOTED_CUE", 0.94),
        (_ABILITY_PLAIN, "ability", "ABILITY_PLAIN_CUE", 0.78),
        (_PLACE_PATTERN, "place", "PLACE_MOTION_OR_LOCATION_CUE", 0.82),
        (_FACTION_PATTERN, "faction", "FACTION_MEMBERSHIP_CUE", 0.86),
        (_SPEAKER_CANDIDATE, "person", "SPEECH_VERB_PERSON_CUE", 0.84),
    )
    for pattern, candidate_type, rule_id, confidence in rules:
        for match in pattern.finditer(body):
            surface = match.group("surface")
            start = chapter.body_start_char + match.start("surface")
            end = chapter.body_start_char + match.end("surface")
            candidate = _candidate(
                source_text,
                chapter,
                candidate_type,
                surface,
                start,
                end,
                rule_id,
                confidence,
            )
            if candidate is not None:
                result.append(candidate)
    return result


def _review_tasks(
    candidates: Sequence[MentionCandidate],
    candidate_anchor_ids: Mapping[str, str],
) -> list[EntityReviewTask]:
    grouped: dict[tuple[str, str], list[MentionCandidate]] = {}
    for candidate in candidates:
        if candidate.candidate_type == "ambiguous_known_alias":
            key = (candidate.candidate_type, candidate.normalized_surface)
        else:
            key = (candidate.candidate_type, candidate.normalized_surface)
        grouped.setdefault(key, []).append(candidate)
    tasks: list[EntityReviewTask] = []
    for (candidate_type, normalized), rows in sorted(grouped.items()):
        candidate_ids = tuple(sorted({row.candidate_id for row in rows}))
        chapter_ids = tuple(sorted({row.chapter_id for row in rows}))
        anchor_ids = tuple(sorted({candidate_anchor_ids[row.candidate_id] for row in rows}))
        surface = sorted({row.surface for row in rows}, key=lambda item: (len(item), item))[0]
        tasks.append(
            EntityReviewTask(
                ENTITY_TASK_SCHEMA_VERSION,
                stable_id(
                    "let_",
                    ENTITY_TASK_SCHEMA_VERSION,
                    candidate_type,
                    normalized,
                    candidate_ids,
                    anchor_ids,
                ),
                candidate_type,
                surface,
                normalized,
                candidate_ids,
                chapter_ids,
                anchor_ids,
                ("accept_new_entity", "link_existing_entity", "reject_candidate"),
                (
                    "accept_fact",
                    "promote_to_tier_A",
                    "index_without_validation",
                    "accept_project",
                    "freeze_project",
                ),
                "pending_review",
            )
        )
    return tasks


def build_fulltext_augmentation(
    source_text: str,
    chapters: Sequence[ChapterRecord],
    existing_anchors: Sequence[EvidenceAnchor],
    entities: Sequence[LiteraryEntity],
) -> FullTextAugmentation:
    """Build exact full-text indexes while keeping unknown entities review-only."""

    chapter_by_id = {item.chapter_id: item for item in chapters}
    if len(chapter_by_id) != len(chapters):
        raise LiteraryFullTextError("duplicate chapter identifiers")

    alias_to_entities_mutable: dict[str, set[str]] = {}
    for entity in entities:
        for alias in entity.aliases:
            cleaned = alias.strip()
            if cleaned and len(cleaned) <= _MAX_ALIAS_LENGTH:
                alias_to_entities_mutable.setdefault(cleaned, set()).add(entity.entity_id)
    alias_to_entities = {
        alias: tuple(sorted(entity_ids))
        for alias, entity_ids in alias_to_entities_mutable.items()
    }
    matcher = _AliasTrie(alias_to_entities)

    anchors_by_id: dict[str, EvidenceAnchor] = {item.anchor_id: item for item in existing_anchors}
    passage_anchors: dict[str, EvidenceAnchor] = {}
    mention_anchors: dict[str, EvidenceAnchor] = {}
    entity_mentions: dict[str, set[str]] = {
        entity.entity_id: set(entity.mention_anchor_ids) for entity in entities
    }
    dialogues: dict[str, DialogueSpan] = {}
    candidates: dict[str, MentionCandidate] = {}
    candidate_anchor_ids: dict[str, str] = {}
    trusted_chapters = 0
    skipped_chapters = 0
    indexed_characters = 0
    known_occurrences = 0
    ambiguous_occurrences = 0

    for chapter in sorted(chapters, key=lambda item: (item.source_order, item.chapter_id)):
        if chapter.contamination_status != "clean" or chapter.review_status in {"needs_review", "rejected"}:
            skipped_chapters += 1
            continue
        trusted_chapters += 1
        indexed_characters += chapter.body_end_char - chapter.body_start_char

        for start, end in _passage_spans(source_text, chapter):
            anchor = _anchor(source_text, chapter, start, end, "chapter_passage")
            if anchor.anchor_id not in anchors_by_id:
                anchors_by_id[anchor.anchor_id] = anchor
                passage_anchors[anchor.anchor_id] = anchor

        body = source_text[chapter.body_start_char:chapter.body_end_char]
        for start, end, surface, entity_ids in matcher.find(body, chapter.body_start_char):
            if len(entity_ids) == 1:
                anchor = _anchor(source_text, chapter, start, end, "entity_mention_fulltext")
                anchors_by_id.setdefault(anchor.anchor_id, anchor)
                mention_anchors.setdefault(anchor.anchor_id, anchors_by_id[anchor.anchor_id])
                entity_mentions.setdefault(entity_ids[0], set()).add(anchor.anchor_id)
                known_occurrences += 1
            else:
                ambiguous_occurrences += 1
                candidate = _candidate(
                    source_text,
                    chapter,
                    "ambiguous_known_alias",
                    surface,
                    start,
                    end,
                    "FULLTEXT_AMBIGUOUS_KNOWN_ALIAS",
                    1.0,
                    entity_ids,
                )
                if candidate is not None:
                    candidates.setdefault(candidate.candidate_id, candidate)

        chapter_dialogues, dialogue_candidates = _dialogues(
            source_text, chapter, alias_to_entities
        )
        for item in chapter_dialogues:
            dialogues.setdefault(item.dialogue_id, item)
        for item in dialogue_candidates:
            candidates.setdefault(item.candidate_id, item)
        for item in _rule_candidates(source_text, chapter):
            # A surface already known uniquely is an occurrence, not a new entity
            # candidate. Ambiguous known aliases remain review candidates.
            known = alias_to_entities.get(item.surface, ())
            if len(known) == 1:
                continue
            if len(known) > 1:
                item = replace(
                    item,
                    candidate_type="ambiguous_known_alias",
                    known_entity_ids=known,
                    rule_id=f"{item.rule_id}_AMBIGUOUS_ALIAS",
                    confidence=1.0,
                )
            candidates.setdefault(item.candidate_id, item)

    for item in candidates.values():
        chapter = chapter_by_id[item.chapter_id]
        anchor = _anchor(
            source_text,
            chapter,
            item.start_char,
            item.end_char,
            "entity_candidate_evidence",
        )
        anchors_by_id.setdefault(anchor.anchor_id, anchor)
        mention_anchors.setdefault(anchor.anchor_id, anchors_by_id[anchor.anchor_id])
        candidate_anchor_ids[item.candidate_id] = anchor.anchor_id

    source_order = {item.chapter_id: item.source_order for item in chapters}
    anchor_chapter = {item.anchor_id: item.chapter_id for item in anchors_by_id.values()}
    updated_entities: list[LiteraryEntity] = []
    for entity in entities:
        mention_ids = tuple(sorted(entity_mentions.get(entity.entity_id, ())))
        chapter_ids = sorted(
            {anchor_chapter[item] for item in mention_ids if item in anchor_chapter},
            key=lambda item: (source_order[item], item),
        )
        updated_entities.append(
            replace(
                entity,
                mention_anchor_ids=mention_ids,
                first_chapter_id=chapter_ids[0] if chapter_ids else entity.first_chapter_id,
                last_chapter_id=chapter_ids[-1] if chapter_ids else entity.last_chapter_id,
            )
        )

    ordered_candidates = tuple(
        sorted(candidates.values(), key=lambda item: (item.start_char, item.end_char, item.candidate_id))
    )
    tasks = tuple(_review_tasks(ordered_candidates, candidate_anchor_ids))
    return FullTextAugmentation(
        tuple(sorted(passage_anchors.values(), key=lambda item: (item.evidence_start, item.anchor_id))),
        tuple(sorted(mention_anchors.values(), key=lambda item: (item.evidence_start, item.anchor_id))),
        tuple(sorted(updated_entities, key=lambda item: item.entity_id)),
        tuple(sorted(dialogues.values(), key=lambda item: (item.start_char, item.dialogue_id))),
        ordered_candidates,
        tasks,
        trusted_chapters,
        skipped_chapters,
        indexed_characters,
        known_occurrences,
        ambiguous_occurrences,
    )


def dialogue_from_dict(payload: Mapping[str, object]) -> DialogueSpan:
    try:
        return DialogueSpan(**dict(payload))
    except TypeError as exc:
        raise LiteraryFullTextError(f"invalid dialogue record: {exc}") from exc


def candidate_from_dict(payload: Mapping[str, object]) -> MentionCandidate:
    data = dict(payload)
    known = data.get("known_entity_ids", [])
    if not isinstance(known, list):
        raise LiteraryFullTextError("known_entity_ids must be a JSON array")
    data["known_entity_ids"] = tuple(known)
    try:
        return MentionCandidate(**data)
    except TypeError as exc:
        raise LiteraryFullTextError(f"invalid mention candidate record: {exc}") from exc


def entity_task_from_dict(payload: Mapping[str, object]) -> EntityReviewTask:
    data = dict(payload)
    for key in (
        "candidate_ids",
        "chapter_ids",
        "evidence_anchor_ids",
        "allowed_decisions",
        "forbidden_authority",
    ):
        value = data.get(key, [])
        if not isinstance(value, list):
            raise LiteraryFullTextError(f"{key} must be a JSON array")
        data[key] = tuple(value)
    try:
        return EntityReviewTask(**data)
    except TypeError as exc:
        raise LiteraryFullTextError(f"invalid entity review task: {exc}") from exc


__all__ = [
    "DIALOGUE_SCHEMA_VERSION",
    "ENTITY_TASK_SCHEMA_VERSION",
    "FULLTEXT_SYSTEM_VERSION",
    "MENTION_CANDIDATE_SCHEMA_VERSION",
    "DialogueSpan",
    "EntityReviewTask",
    "FullTextAugmentation",
    "LiteraryFullTextError",
    "MentionCandidate",
    "build_fulltext_augmentation",
    "candidate_from_dict",
    "dialogue_from_dict",
    "entity_task_from_dict",
]
