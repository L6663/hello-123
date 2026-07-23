"""Deterministic source-bound Evidence Engine primitives.

This module is the Stage 1 foundation for the v6 literary knowledge engine.  It
creates exact evidence units from trusted chapter bodies and validates the full
source binding.  It deliberately does not infer plot, entities, events, or
literary meaning.

Core guarantees
---------------

* evidence identifiers are deterministic hashes of the source binding;
* every evidence text must equal ``source_text[start:end]`` exactly;
* file, Unit, chapter, span, text, and SHA-256 identities are retained;
* contaminated, non-body, and review-only chapters are never indexed as clean
  evidence;
* coverage is measured over non-whitespace characters, with excluded
  whitespace reported explicitly;
* uncovered non-whitespace text, overlap, source mutation, or hash mismatch is
  a verification failure.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re
from typing import Final, Iterable, Mapping, Sequence

from .literary_models import ChapterRecord, stable_id

EVIDENCE_ENGINE_VERSION: Final = "tkr-evidence-engine-v1"
EVIDENCE_UNIT_SCHEMA_VERSION: Final = "tkr-evidence-unit-v1"
EVIDENCE_COVERAGE_SCHEMA_VERSION: Final = "tkr-evidence-coverage-v1"
EVIDENCE_VERIFICATION_SCHEMA_VERSION: Final = "tkr-evidence-verification-v1"

TRUSTED_SOURCE_STATUS: Final = "clean"
BLOCKED_SOURCE_STATUSES: Final = frozenset({"contaminated", "non_body", "needs_review"})
BLOCKED_REVIEW_STATUSES: Final = frozenset({"needs_review", "rejected"})
BOUNDARY_KINDS: Final = frozenset(
    {
        "paragraph",
        "paragraph_group",
        "sentence_group",
        "oversize_sentence",
        "chapter_body",
    }
)

_PARAGRAPH_BREAK = re.compile(r"(?:\r\n|\r|\n)+")
_SENTENCE_END = frozenset("。！？!?；;")


class EvidenceEngineError(ValueError):
    """Raised when evidence violates its source or epistemic contract."""


def _canonical_json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise EvidenceEngineError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise EvidenceEngineError(f"{name} must be non-empty")
    return value


def _require_non_negative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceEngineError(f"{name} must be a non-negative integer")
    return value


def _require_optional_positive(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvidenceEngineError(f"{name} must be a positive integer or null")
    return value


def _require_sha256(value: object, name: str) -> str:
    text = _require_text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise EvidenceEngineError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def _content_character_count(text: str) -> int:
    return sum(not character.isspace() for character in text)


def evidence_unit_id(
    source_sha256: str,
    unit_id: str,
    start_char: int,
    end_char: int,
    text_sha256: str,
) -> str:
    return stable_id(
        "evu_",
        EVIDENCE_UNIT_SCHEMA_VERSION,
        source_sha256,
        unit_id,
        start_char,
        end_char,
        text_sha256,
    )


@dataclass(frozen=True, slots=True)
class EvidenceUnit:
    schema_version: str
    evidence_id: str
    source_id: str
    source_sha256: str
    unit_id: str
    chapter_id: str
    volume_ordinal: int | None
    chapter_ordinal: int | None
    original_heading: str
    normalized_heading: str
    paragraph_ordinal: int
    sequence_in_chapter: int
    start_char: int
    end_char: int
    text: str
    text_sha256: str
    unit_content_sha256: str
    source_status: str
    boundary_kind: str
    content_character_count: int
    review_status: str

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_UNIT_SCHEMA_VERSION:
            raise EvidenceEngineError("evidence unit schema version mismatch")
        for name in (
            "evidence_id",
            "source_id",
            "unit_id",
            "chapter_id",
            "text",
            "source_status",
            "boundary_kind",
            "review_status",
        ):
            _require_text(getattr(self, name), name)
        _require_sha256(self.source_sha256, "source_sha256")
        _require_sha256(self.text_sha256, "text_sha256")
        _require_sha256(self.unit_content_sha256, "unit_content_sha256")
        _require_optional_positive(self.volume_ordinal, "volume_ordinal")
        _require_optional_positive(self.chapter_ordinal, "chapter_ordinal")
        paragraph = _require_non_negative(self.paragraph_ordinal, "paragraph_ordinal")
        sequence = _require_non_negative(self.sequence_in_chapter, "sequence_in_chapter")
        if paragraph <= 0 or sequence <= 0:
            raise EvidenceEngineError("paragraph and sequence ordinals must be positive")
        start = _require_non_negative(self.start_char, "start_char")
        end = _require_non_negative(self.end_char, "end_char")
        if end <= start:
            raise EvidenceEngineError("end_char must be greater than start_char")
        if self.boundary_kind not in BOUNDARY_KINDS:
            raise EvidenceEngineError(f"unsupported boundary_kind: {self.boundary_kind}")
        if self.source_status != TRUSTED_SOURCE_STATUS:
            raise EvidenceEngineError("canonical evidence units require clean source status")
        if self.review_status != "accepted_evidence":
            raise EvidenceEngineError("evidence unit must use accepted_evidence review status")
        expected_text_hash = sha256(self.text.encode("utf-8")).hexdigest()
        if expected_text_hash != self.text_sha256:
            raise EvidenceEngineError("evidence text SHA-256 mismatch")
        expected_id = evidence_unit_id(
            self.source_sha256,
            self.unit_id,
            self.start_char,
            self.end_char,
            self.text_sha256,
        )
        if expected_id != self.evidence_id:
            raise EvidenceEngineError("evidence identifier does not match source binding")
        expected_content = _content_character_count(self.text)
        if self.content_character_count != expected_content or expected_content <= 0:
            raise EvidenceEngineError("content_character_count does not match evidence text")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CoverageSpan:
    chapter_id: str
    start_char: int
    end_char: int
    reason: str

    def __post_init__(self) -> None:
        _require_text(self.chapter_id, "chapter_id")
        start = _require_non_negative(self.start_char, "start_char")
        end = _require_non_negative(self.end_char, "end_char")
        if end <= start:
            raise EvidenceEngineError("coverage span must be non-empty")
        if self.reason not in {"uncovered_content", "overlap", "blocked_chapter"}:
            raise EvidenceEngineError("unsupported coverage span reason")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceCoverageReport:
    schema_version: str
    evidence_engine_version: str
    source_id: str
    source_sha256: str
    source_character_count: int
    chapter_count: int
    eligible_chapter_count: int
    blocked_chapter_count: int
    evidence_unit_count: int
    eligible_content_character_count: int
    indexed_content_character_count: int
    excluded_whitespace_character_count: int
    uncovered_content_character_count: int
    overlap_content_character_count: int
    coverage_rate: float
    uncovered_spans: tuple[CoverageSpan, ...]
    overlap_spans: tuple[CoverageSpan, ...]
    blocked_spans: tuple[CoverageSpan, ...]
    complete: bool

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_COVERAGE_SCHEMA_VERSION:
            raise EvidenceEngineError("coverage report schema version mismatch")
        if self.evidence_engine_version != EVIDENCE_ENGINE_VERSION:
            raise EvidenceEngineError("coverage report engine version mismatch")
        _require_text(self.source_id, "source_id")
        _require_sha256(self.source_sha256, "source_sha256")
        for name in (
            "source_character_count",
            "chapter_count",
            "eligible_chapter_count",
            "blocked_chapter_count",
            "evidence_unit_count",
            "eligible_content_character_count",
            "indexed_content_character_count",
            "excluded_whitespace_character_count",
            "uncovered_content_character_count",
            "overlap_content_character_count",
        ):
            _require_non_negative(getattr(self, name), name)
        if self.eligible_chapter_count + self.blocked_chapter_count != self.chapter_count:
            raise EvidenceEngineError("eligible and blocked chapter counts do not sum to chapter_count")
        if isinstance(self.coverage_rate, bool) or not isinstance(self.coverage_rate, (int, float)):
            raise EvidenceEngineError("coverage_rate must be numeric")
        if not 0.0 <= float(self.coverage_rate) <= 1.0:
            raise EvidenceEngineError("coverage_rate must be between zero and one")
        expected_rate = (
            self.indexed_content_character_count / self.eligible_content_character_count
            if self.eligible_content_character_count
            else 1.0
        )
        if abs(float(self.coverage_rate) - expected_rate) > 1e-12:
            raise EvidenceEngineError("coverage_rate does not match character counts")
        expected_complete = (
            self.uncovered_content_character_count == 0
            and self.overlap_content_character_count == 0
            and self.indexed_content_character_count == self.eligible_content_character_count
        )
        if self.complete != expected_complete:
            raise EvidenceEngineError("coverage complete flag does not match measured state")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("uncovered_spans", "overlap_spans", "blocked_spans"):
            payload[key] = [item.to_dict() for item in getattr(self, key)]
        return payload


@dataclass(frozen=True, slots=True)
class EvidenceExtractionResult:
    units: tuple[EvidenceUnit, ...]
    coverage: EvidenceCoverageReport


@dataclass(frozen=True, slots=True)
class EvidenceVerification:
    schema_version: str
    evidence_engine_version: str
    valid: bool
    reason_codes: tuple[str, ...]
    checked_unit_count: int
    source_sha256: str
    coverage_rate: float

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_VERIFICATION_SCHEMA_VERSION:
            raise EvidenceEngineError("verification schema version mismatch")
        if self.evidence_engine_version != EVIDENCE_ENGINE_VERSION:
            raise EvidenceEngineError("verification engine version mismatch")
        _require_sha256(self.source_sha256, "source_sha256")
        _require_non_negative(self.checked_unit_count, "checked_unit_count")
        if self.valid != (not self.reason_codes):
            raise EvidenceEngineError("verification validity does not match reason codes")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


def _trim_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _paragraph_spans(source_text: str, chapter: ChapterRecord) -> list[tuple[int, int, int]]:
    body_start = chapter.body_start_char
    body_end = chapter.body_end_char
    body = source_text[body_start:body_end]
    result: list[tuple[int, int, int]] = []
    local_start = 0
    paragraph_ordinal = 1
    for match in _PARAGRAPH_BREAK.finditer(body):
        trimmed = _trim_span(source_text, body_start + local_start, body_start + match.start())
        if trimmed is not None:
            result.append((trimmed[0], trimmed[1], paragraph_ordinal))
            paragraph_ordinal += 1
        local_start = match.end()
    trimmed = _trim_span(source_text, body_start + local_start, body_end)
    if trimmed is not None:
        result.append((trimmed[0], trimmed[1], paragraph_ordinal))
    return result


def _sentence_spans(source_text: str, start: int, end: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    cursor = start
    for index in range(start, end):
        if source_text[index] in _SENTENCE_END:
            trimmed = _trim_span(source_text, cursor, index + 1)
            if trimmed is not None:
                result.append(trimmed)
            cursor = index + 1
    trimmed = _trim_span(source_text, cursor, end)
    if trimmed is not None:
        result.append(trimmed)
    return result


def _split_paragraph(
    source_text: str,
    start: int,
    end: int,
    *,
    max_chars: int,
) -> list[tuple[int, int, str]]:
    if end - start <= max_chars:
        return [(start, end, "paragraph")]
    sentences = _sentence_spans(source_text, start, end)
    if not sentences:
        return [(start, end, "oversize_sentence")]
    result: list[tuple[int, int, str]] = []
    group_start: int | None = None
    group_end: int | None = None
    for sentence_start, sentence_end in sentences:
        if sentence_end - sentence_start > max_chars:
            if group_start is not None and group_end is not None:
                result.append((group_start, group_end, "sentence_group"))
                group_start = group_end = None
            result.append((sentence_start, sentence_end, "oversize_sentence"))
            continue
        if group_start is None:
            group_start, group_end = sentence_start, sentence_end
            continue
        assert group_end is not None
        if sentence_end - group_start <= max_chars:
            group_end = sentence_end
        else:
            result.append((group_start, group_end, "sentence_group"))
            group_start, group_end = sentence_start, sentence_end
    if group_start is not None and group_end is not None:
        result.append((group_start, group_end, "sentence_group"))
    return result


def _candidate_spans(
    source_text: str,
    chapter: ChapterRecord,
    *,
    max_chars: int,
) -> list[tuple[int, int, int, str]]:
    paragraphs = _paragraph_spans(source_text, chapter)
    result: list[tuple[int, int, int, str]] = []
    for start, end, paragraph_ordinal in paragraphs:
        for piece_start, piece_end, boundary_kind in _split_paragraph(
            source_text,
            start,
            end,
            max_chars=max_chars,
        ):
            result.append((piece_start, piece_end, paragraph_ordinal, boundary_kind))
    return result


def _merge_short_spans(
    source_text: str,
    spans: Sequence[tuple[int, int, int, str]],
    *,
    target_chars: int,
    max_chars: int,
) -> list[tuple[int, int, int, str]]:
    if not spans:
        return []
    result: list[tuple[int, int, int, str]] = []
    current_start, current_end, current_paragraph, current_kind = spans[0]
    for start, end, paragraph, kind in spans[1:]:
        current_size = current_end - current_start
        merged_size = end - current_start
        can_merge = (
            current_kind != "oversize_sentence"
            and kind != "oversize_sentence"
            and current_size < target_chars
            and merged_size <= max_chars
        )
        if can_merge:
            current_end = end
            if paragraph != current_paragraph:
                current_kind = "paragraph_group"
            else:
                current_kind = "sentence_group"
            continue
        result.append((current_start, current_end, current_paragraph, current_kind))
        current_start, current_end, current_paragraph, current_kind = start, end, paragraph, kind
    result.append((current_start, current_end, current_paragraph, current_kind))
    return result


def _eligible_chapter(chapter: ChapterRecord) -> bool:
    return (
        chapter.contamination_status == TRUSTED_SOURCE_STATUS
        and chapter.review_status not in BLOCKED_REVIEW_STATUSES
    )


def _source_identity(source_text: str, chapters: Sequence[ChapterRecord]) -> tuple[str, str]:
    if not chapters:
        raise EvidenceEngineError("at least one chapter is required")
    source_ids = {item.source_id for item in chapters}
    source_hashes = {item.source_sha256 for item in chapters}
    if len(source_ids) != 1 or len(source_hashes) != 1:
        raise EvidenceEngineError("one extraction run must bind exactly one source identity")
    source_id = next(iter(source_ids))
    source_hash = next(iter(source_hashes))
    actual_hash = sha256(source_text.encode("utf-8")).hexdigest()
    if actual_hash != source_hash:
        raise EvidenceEngineError("normalized source SHA-256 differs from chapter source binding")
    return source_id, source_hash


def _chapter_content_check(source_text: str, chapter: ChapterRecord) -> None:
    if not 0 <= chapter.start_char < chapter.end_char <= len(source_text):
        raise EvidenceEngineError(f"chapter span is outside source: {chapter.chapter_id}")
    if not chapter.start_char <= chapter.body_start_char <= chapter.body_end_char <= chapter.end_char:
        raise EvidenceEngineError(f"chapter body span is invalid: {chapter.chapter_id}")
    actual = sha256(source_text[chapter.start_char:chapter.end_char].encode("utf-8")).hexdigest()
    if actual != chapter.content_sha256:
        raise EvidenceEngineError(f"chapter content SHA-256 mismatch: {chapter.chapter_id}")


def extract_evidence_units(
    source_text: str,
    chapters: Sequence[ChapterRecord],
    *,
    target_chars: int = 900,
    max_chars: int = 1500,
) -> EvidenceExtractionResult:
    """Extract deterministic evidence units from trusted chapter bodies.

    ``target_chars`` guides grouping of short paragraphs.  ``max_chars`` is a
    soft ceiling: a single source sentence is never cut solely to satisfy the
    limit, and is emitted as ``oversize_sentence`` instead.
    """

    if not isinstance(source_text, str):
        raise EvidenceEngineError("source_text must be a string")
    if isinstance(target_chars, bool) or not isinstance(target_chars, int) or target_chars <= 0:
        raise EvidenceEngineError("target_chars must be a positive integer")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < target_chars:
        raise EvidenceEngineError("max_chars must be an integer not smaller than target_chars")

    ordered = sorted(chapters, key=lambda item: (item.source_order, item.chapter_id))
    source_id, source_hash = _source_identity(source_text, ordered)
    units: list[EvidenceUnit] = []
    blocked_spans: list[CoverageSpan] = []
    eligible_content = 0
    excluded_whitespace = 0
    eligible_chapters = 0
    blocked_chapters = 0

    for chapter in ordered:
        _chapter_content_check(source_text, chapter)
        body = source_text[chapter.body_start_char:chapter.body_end_char]
        content_count = _content_character_count(body)
        whitespace_count = len(body) - content_count
        if not _eligible_chapter(chapter):
            blocked_chapters += 1
            if chapter.body_end_char > chapter.body_start_char:
                blocked_spans.append(
                    CoverageSpan(
                        chapter.chapter_id,
                        chapter.body_start_char,
                        chapter.body_end_char,
                        "blocked_chapter",
                    )
                )
            continue
        eligible_chapters += 1
        eligible_content += content_count
        excluded_whitespace += whitespace_count
        candidates = _candidate_spans(
            source_text,
            chapter,
            max_chars=max_chars,
        )
        merged = _merge_short_spans(
            source_text,
            candidates,
            target_chars=target_chars,
            max_chars=max_chars,
        )
        for sequence, (start, end, paragraph, boundary_kind) in enumerate(merged, start=1):
            text = source_text[start:end]
            text_hash = sha256(text.encode("utf-8")).hexdigest()
            units.append(
                EvidenceUnit(
                    EVIDENCE_UNIT_SCHEMA_VERSION,
                    evidence_unit_id(source_hash, chapter.unit_id, start, end, text_hash),
                    source_id,
                    source_hash,
                    chapter.unit_id,
                    chapter.chapter_id,
                    chapter.volume_ordinal,
                    chapter.chapter_ordinal,
                    chapter.original_heading,
                    chapter.normalized_heading,
                    paragraph,
                    sequence,
                    start,
                    end,
                    text,
                    text_hash,
                    chapter.content_sha256,
                    TRUSTED_SOURCE_STATUS,
                    boundary_kind if body else "chapter_body",
                    _content_character_count(text),
                    "accepted_evidence",
                )
            )

    coverage = measure_evidence_coverage(source_text, ordered, units, blocked_spans=blocked_spans)
    if coverage.eligible_content_character_count != eligible_content:
        raise EvidenceEngineError("internal eligible content count mismatch")
    if coverage.excluded_whitespace_character_count != excluded_whitespace:
        raise EvidenceEngineError("internal whitespace count mismatch")
    if coverage.eligible_chapter_count != eligible_chapters or coverage.blocked_chapter_count != blocked_chapters:
        raise EvidenceEngineError("internal chapter count mismatch")
    return EvidenceExtractionResult(tuple(units), coverage)


def _non_whitespace_runs(text: str, start: int, end: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        while cursor < end and text[cursor].isspace():
            cursor += 1
        if cursor >= end:
            break
        run_start = cursor
        while cursor < end and not text[cursor].isspace():
            cursor += 1
        runs.append((run_start, cursor))
    return runs


def _span_content_count(source_text: str, start: int, end: int) -> int:
    return _content_character_count(source_text[start:end])


def measure_evidence_coverage(
    source_text: str,
    chapters: Sequence[ChapterRecord],
    units: Sequence[EvidenceUnit],
    *,
    blocked_spans: Sequence[CoverageSpan] = (),
) -> EvidenceCoverageReport:
    """Measure exact non-whitespace coverage and overlap for trusted bodies."""

    ordered_chapters = sorted(chapters, key=lambda item: (item.source_order, item.chapter_id))
    source_id, source_hash = _source_identity(source_text, ordered_chapters)
    chapter_by_id = {item.chapter_id: item for item in ordered_chapters}
    if len(chapter_by_id) != len(ordered_chapters):
        raise EvidenceEngineError("duplicate chapter identifiers")

    unit_by_id: dict[str, EvidenceUnit] = {}
    intervals_by_chapter: dict[str, list[tuple[int, int, str]]] = {}
    for unit in units:
        if unit.evidence_id in unit_by_id:
            raise EvidenceEngineError("duplicate evidence identifier")
        unit_by_id[unit.evidence_id] = unit
        intervals_by_chapter.setdefault(unit.chapter_id, []).append(
            (unit.start_char, unit.end_char, unit.evidence_id)
        )

    eligible_content = 0
    indexed_content = 0
    excluded_whitespace = 0
    uncovered_content = 0
    overlap_content = 0
    uncovered_spans: list[CoverageSpan] = []
    overlap_spans: list[CoverageSpan] = []
    eligible_chapters = 0
    blocked_chapters = 0

    for chapter in ordered_chapters:
        _chapter_content_check(source_text, chapter)
        body = source_text[chapter.body_start_char:chapter.body_end_char]
        if not _eligible_chapter(chapter):
            blocked_chapters += 1
            continue
        eligible_chapters += 1
        eligible_content += _content_character_count(body)
        excluded_whitespace += len(body) - _content_character_count(body)
        intervals = sorted(intervals_by_chapter.get(chapter.chapter_id, []))
        previous_end = chapter.body_start_char
        for start, end, identifier in intervals:
            unit = unit_by_id[identifier]
            if unit.source_id != source_id or unit.source_sha256 != source_hash:
                raise EvidenceEngineError("evidence unit source identity mismatch")
            if unit.unit_id != chapter.unit_id:
                raise EvidenceEngineError("evidence unit Unit binding mismatch")
            if not chapter.body_start_char <= start < end <= chapter.body_end_char:
                raise EvidenceEngineError("evidence unit escaped trusted chapter body")
            actual_text = source_text[start:end]
            if actual_text != unit.text:
                raise EvidenceEngineError("evidence text differs from source span")
            if sha256(actual_text.encode("utf-8")).hexdigest() != unit.text_sha256:
                raise EvidenceEngineError("evidence text hash differs from source span")
            if previous_end < start:
                for run_start, run_end in _non_whitespace_runs(source_text, previous_end, start):
                    uncovered_spans.append(
                        CoverageSpan(chapter.chapter_id, run_start, run_end, "uncovered_content")
                    )
                    uncovered_content += run_end - run_start
            elif start < previous_end:
                overlap_end = min(previous_end, end)
                if overlap_end > start:
                    overlap_spans.append(
                        CoverageSpan(chapter.chapter_id, start, overlap_end, "overlap")
                    )
                    overlap_content += _span_content_count(source_text, start, overlap_end)
            indexed_content += unit.content_character_count
            previous_end = max(previous_end, end)
        if previous_end < chapter.body_end_char:
            for run_start, run_end in _non_whitespace_runs(
                source_text,
                previous_end,
                chapter.body_end_char,
            ):
                uncovered_spans.append(
                    CoverageSpan(chapter.chapter_id, run_start, run_end, "uncovered_content")
                )
                uncovered_content += run_end - run_start

    if overlap_content:
        indexed_unique_content = max(0, indexed_content - overlap_content)
    else:
        indexed_unique_content = indexed_content
    coverage_rate = indexed_unique_content / eligible_content if eligible_content else 1.0
    complete = (
        uncovered_content == 0
        and overlap_content == 0
        and indexed_unique_content == eligible_content
    )
    return EvidenceCoverageReport(
        EVIDENCE_COVERAGE_SCHEMA_VERSION,
        EVIDENCE_ENGINE_VERSION,
        source_id,
        source_hash,
        len(source_text),
        len(ordered_chapters),
        eligible_chapters,
        blocked_chapters,
        len(units),
        eligible_content,
        indexed_unique_content,
        excluded_whitespace,
        uncovered_content,
        overlap_content,
        coverage_rate,
        tuple(uncovered_spans),
        tuple(overlap_spans),
        tuple(blocked_spans),
        complete,
    )


def verify_evidence_units(
    source_text: str,
    chapters: Sequence[ChapterRecord],
    units: Sequence[EvidenceUnit],
) -> EvidenceVerification:
    """Fail closed on source mutation, bad spans, overlap, or missing content."""

    reasons: list[str] = []
    source_hash = sha256(source_text.encode("utf-8")).hexdigest()
    coverage_rate = 0.0
    try:
        coverage = measure_evidence_coverage(source_text, chapters, units)
        coverage_rate = coverage.coverage_rate
        if not coverage.complete:
            if coverage.uncovered_content_character_count:
                reasons.append("EVIDENCE_CONTENT_UNCOVERED")
            if coverage.overlap_content_character_count:
                reasons.append("EVIDENCE_CONTENT_OVERLAP")
            if coverage.indexed_content_character_count != coverage.eligible_content_character_count:
                reasons.append("EVIDENCE_CONTENT_COUNT_MISMATCH")
    except EvidenceEngineError as exc:
        message = str(exc)
        if "source SHA-256" in message:
            reasons.append("EVIDENCE_SOURCE_HASH_MISMATCH")
        elif "text differs" in message:
            reasons.append("EVIDENCE_TEXT_SPAN_MISMATCH")
        elif "text hash" in message:
            reasons.append("EVIDENCE_TEXT_HASH_MISMATCH")
        elif "chapter content" in message:
            reasons.append("EVIDENCE_CHAPTER_HASH_MISMATCH")
        elif "duplicate evidence" in message:
            reasons.append("EVIDENCE_IDENTIFIER_DUPLICATE")
        else:
            reasons.append("EVIDENCE_VERIFICATION_ERROR")
    return EvidenceVerification(
        EVIDENCE_VERIFICATION_SCHEMA_VERSION,
        EVIDENCE_ENGINE_VERSION,
        not reasons,
        tuple(dict.fromkeys(reasons)),
        len(units),
        source_hash,
        coverage_rate,
    )


def evidence_unit_from_dict(payload: Mapping[str, object]) -> EvidenceUnit:
    try:
        return EvidenceUnit(**dict(payload))
    except TypeError as exc:
        raise EvidenceEngineError(f"invalid evidence unit record: {exc}") from exc


def coverage_report_from_dict(payload: Mapping[str, object]) -> EvidenceCoverageReport:
    data = dict(payload)
    for key in ("uncovered_spans", "overlap_spans", "blocked_spans"):
        raw = data.get(key, [])
        if not isinstance(raw, list):
            raise EvidenceEngineError(f"{key} must be a JSON array")
        data[key] = tuple(CoverageSpan(**dict(item)) for item in raw if isinstance(item, dict))
        if len(data[key]) != len(raw):
            raise EvidenceEngineError(f"{key} contains a non-object record")
    try:
        return EvidenceCoverageReport(**data)
    except TypeError as exc:
        raise EvidenceEngineError(f"invalid evidence coverage report: {exc}") from exc


__all__ = [
    "BLOCKED_REVIEW_STATUSES",
    "BLOCKED_SOURCE_STATUSES",
    "EVIDENCE_COVERAGE_SCHEMA_VERSION",
    "EVIDENCE_ENGINE_VERSION",
    "EVIDENCE_UNIT_SCHEMA_VERSION",
    "EVIDENCE_VERIFICATION_SCHEMA_VERSION",
    "CoverageSpan",
    "EvidenceCoverageReport",
    "EvidenceEngineError",
    "EvidenceExtractionResult",
    "EvidenceUnit",
    "EvidenceVerification",
    "coverage_report_from_dict",
    "evidence_unit_from_dict",
    "evidence_unit_id",
    "extract_evidence_units",
    "measure_evidence_coverage",
    "verify_evidence_units",
]
