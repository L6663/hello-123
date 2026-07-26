"""Stage 8-R5 precise coverage and verification patch."""
from __future__ import annotations
from . import evidence_engine as _engine

_SOURCE = r'''
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
        chapter_blocks = sorted(
            (item.start_char, item.end_char) for item in blocked_spans
            if item.chapter_id == chapter.chapter_id and item.reason == "blocked_source_span"
        )
        allowed = _allowed_intervals(chapter.body_start_char, chapter.body_end_char, chapter_blocks)
        allowed_content = sum(_content_character_count(source_text[a:b]) for a,b in allowed)
        if not _eligible_chapter(chapter, has_precise_contamination=bool(chapter_blocks)) or allowed_content == 0:
            blocked_chapters += 1
            continue
        eligible_chapters += 1
        eligible_content += allowed_content
        excluded_whitespace += sum((b-a) - _content_character_count(source_text[a:b]) for a,b in allowed)
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
            if any(start < blocked_end and blocked_start < end for blocked_start, blocked_end in chapter_blocks):
                raise EvidenceEngineError("evidence unit overlaps blocked source span")
            actual_text = source_text[start:end]
            if actual_text != unit.text:
                raise EvidenceEngineError("evidence text differs from source span")
            if sha256(actual_text.encode("utf-8")).hexdigest() != unit.text_sha256:
                raise EvidenceEngineError("evidence text hash differs from source span")
            indexed_content += unit.content_character_count

        for allowed_start, allowed_end in allowed:
            allowed_intervals = [row for row in intervals if allowed_start <= row[0] and row[1] <= allowed_end]
            previous_end = allowed_start
            for start, end, identifier in allowed_intervals:
                if previous_end < start:
                    for run_start, run_end in _non_whitespace_runs(source_text, previous_end, start):
                        uncovered_spans.append(CoverageSpan(chapter.chapter_id, run_start, run_end, "uncovered_content"))
                        uncovered_content += run_end - run_start
                elif start < previous_end:
                    overlap_end = min(previous_end, end)
                    if overlap_end > start:
                        overlap_spans.append(CoverageSpan(chapter.chapter_id, start, overlap_end, "overlap"))
                        overlap_content += _span_content_count(source_text, start, overlap_end)
                previous_end = max(previous_end, end)
            if previous_end < allowed_end:
                for run_start, run_end in _non_whitespace_runs(source_text, previous_end, allowed_end):
                    uncovered_spans.append(CoverageSpan(chapter.chapter_id, run_start, run_end, "uncovered_content"))
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
    *,
    blocked_source_spans: Sequence[Mapping[str, object]] = (),
) -> EvidenceVerification:
    """Fail closed on source mutation, bad spans, overlap, or missing content."""

    reasons: list[str] = []
    source_hash = sha256(source_text.encode("utf-8")).hexdigest()
    coverage_rate = 0.0
    try:
        blocked = []
        for chapter in chapters:
            blocked.extend(
                CoverageSpan(chapter.chapter_id, a, b, "blocked_source_span")
                for a,b in _exact_blocked_intervals(chapter, blocked_source_spans)
            )
        coverage = measure_evidence_coverage(source_text, chapters, units, blocked_spans=blocked)
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
'''

def _coverage_post_init(self) -> None:
    _engine._require_text(self.chapter_id, "chapter_id")
    start = _engine._require_non_negative(self.start_char, "start_char")
    end = _engine._require_non_negative(self.end_char, "end_char")
    if end <= start:
        raise _engine.EvidenceEngineError("coverage span must be non-empty")
    if self.reason not in {"uncovered_content", "overlap", "blocked_chapter", "blocked_source_span"}:
        raise _engine.EvidenceEngineError("unsupported coverage span reason")

def apply_stage8_r5_evidence_verify_patch() -> None:
    _engine.CoverageSpan.__post_init__ = _coverage_post_init
    exec(compile(_SOURCE, "<stage8-r5-evidence-verify>", "exec"), _engine.__dict__)
    _engine.EVIDENCE_ENGINE_VERSION = "tkr-evidence-engine-v2"

__all__ = ["apply_stage8_r5_evidence_verify_patch"]
