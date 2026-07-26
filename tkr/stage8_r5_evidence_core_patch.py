"""Stage 8-R5 precise contamination-span extraction patch."""
from __future__ import annotations
from . import evidence_engine as _engine

_SOURCE = r'''
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
            and not source_text[current_end:start].strip()
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

def _eligible_chapter(chapter: ChapterRecord, *, has_precise_contamination: bool = False) -> bool:
    if chapter.review_status in BLOCKED_REVIEW_STATUSES:
        return False
    if chapter.contamination_status == TRUSTED_SOURCE_STATUS:
        return True
    return chapter.contamination_status == "contaminated" and has_precise_contamination

def _exact_blocked_intervals(
    chapter: ChapterRecord, blocked_source_spans: Sequence[Mapping[str, object]]
) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for row in blocked_source_spans:
        if row.get("category") != "contamination_candidate":
            continue
        start, end = row.get("start_char"), row.get("end_char")
        if isinstance(start, bool) or not isinstance(start, int):
            continue
        if isinstance(end, bool) or not isinstance(end, int):
            continue
        start = max(start, chapter.body_start_char)
        end = min(end, chapter.body_end_char)
        if start < end:
            intervals.append((start, end))
    if not intervals:
        return []
    intervals.sort()
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged

def _allowed_intervals(start: int, end: int, blocked: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    allowed: list[tuple[int, int]] = []
    cursor = start
    for blocked_start, blocked_end in blocked:
        if cursor < blocked_start:
            allowed.append((cursor, blocked_start))
        cursor = max(cursor, blocked_end)
    if cursor < end:
        allowed.append((cursor, end))
    return allowed

def _candidate_spans_in_ranges(
    source_text: str, chapter: ChapterRecord, ranges: Sequence[tuple[int, int]], *, max_chars: int
) -> list[tuple[int, int, int, str]]:
    result: list[tuple[int, int, int, str]] = []
    paragraph_ordinal = 1
    for range_start, range_end in ranges:
        local = source_text[range_start:range_end]
        cursor = 0
        for match in _PARAGRAPH_BREAK.finditer(local):
            trimmed = _trim_span(source_text, range_start + cursor, range_start + match.start())
            if trimmed is not None:
                for piece_start, piece_end, kind in _split_paragraph(
                    source_text, trimmed[0], trimmed[1], max_chars=max_chars
                ):
                    result.append((piece_start, piece_end, paragraph_ordinal, kind))
                paragraph_ordinal += 1
            cursor = match.end()
        trimmed = _trim_span(source_text, range_start + cursor, range_end)
        if trimmed is not None:
            for piece_start, piece_end, kind in _split_paragraph(
                source_text, trimmed[0], trimmed[1], max_chars=max_chars
            ):
                result.append((piece_start, piece_end, paragraph_ordinal, kind))
            paragraph_ordinal += 1
    return result

def extract_evidence_units(
    source_text: str,
    chapters: Sequence[ChapterRecord],
    *,
    target_chars: int = 900,
    max_chars: int = 1500,
    blocked_source_spans: Sequence[Mapping[str, object]] = (),
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
        exact_blocks = _exact_blocked_intervals(chapter, blocked_source_spans)
        allowed = _allowed_intervals(chapter.body_start_char, chapter.body_end_char, exact_blocks)
        allowed_content = sum(_content_character_count(source_text[a:b]) for a, b in allowed)
        if not _eligible_chapter(chapter, has_precise_contamination=bool(exact_blocks)) or allowed_content == 0:
            blocked_chapters += 1
            if chapter.body_end_char > chapter.body_start_char:
                blocked_spans.append(
                    CoverageSpan(chapter.chapter_id, chapter.body_start_char, chapter.body_end_char, "blocked_chapter")
                )
            continue
        eligible_chapters += 1
        eligible_content += allowed_content
        excluded_whitespace += sum((b-a) - _content_character_count(source_text[a:b]) for a,b in allowed)
        blocked_spans.extend(
            CoverageSpan(chapter.chapter_id, a, b, "blocked_source_span") for a,b in exact_blocks
        )
        candidates = _candidate_spans_in_ranges(
            source_text, chapter, allowed, max_chars=max_chars
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
'''

def apply_stage8_r5_evidence_core_patch() -> None:
    exec(compile(_SOURCE, "<stage8-r5-evidence-core>", "exec"), _engine.__dict__)

__all__ = ["apply_stage8_r5_evidence_core_patch"]
