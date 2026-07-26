"""Stage 8-R5 long-form structure and cross-source volume remediation."""
from __future__ import annotations

from dataclasses import replace
from typing import Final

from . import structure_detection as _structure
from . import chapter_engine as _chapter

PATCH_VERSION: Final = "tkr-stage8-r5-structure-patch-v1"
_APPLIED = False
_ORIGINAL_SCAN = _structure._scan_headings
_ORIGINAL_SOURCE_CHAPTERS = _chapter._source_chapters
_INHERITED_VOLUME: int | None = None


def _scan_headings(path, encoding_report, policy):
    headings, boundaries, detached, scanned_chars, scanned_lines, warnings = _ORIGINAL_SCAN(
        path, encoding_report, policy
    )
    accepted_sections = [
        item for item in headings
        if item.accepted_as_boundary and item.unit_type == "section"
        and item.ordinal is not None and item.confidence in {"high", "medium"}
    ]
    explicit_chapters = [
        item for item in headings
        if item.accepted_as_boundary and item.unit_type == "chapter"
        and "compact_numbered_heading" not in item.signals
    ]
    ordinals = [item.ordinal for item in accepted_sections if item.ordinal is not None]
    dominant = (
        len(accepted_sections) >= 20
        and not explicit_chapters
        and len(set(ordinals)) >= max(15, int(len(ordinals) * 0.8))
    )
    if not dominant:
        return headings, boundaries, detached, scanned_chars, scanned_lines, warnings

    updated = []
    by_id = {}
    for item in headings:
        if item.unit_type == "section" and item.accepted_as_boundary and item.ordinal is not None:
            item = replace(
                item,
                unit_type="chapter",
                hierarchy_level=2,
                signals=tuple((*item.signals, "source_convention=numbered_section_as_chapter")),
            )
        elif item.accepted_as_boundary and "compact_numbered_heading" in item.signals:
            item = replace(
                item,
                accepted_as_boundary=False,
                signals=tuple((*item.signals, "source_convention=rejected_compact_numbered_boundary")),
            )
        updated.append(item)
        by_id[item.heading_id] = item
    rebuilt = [
        _structure._Boundary(by_id[item.heading.heading_id], item.line_start_char)
        for item in boundaries
        if by_id[item.heading.heading_id].accepted_as_boundary
    ]
    warnings.append("NUMBERED_SECTION_CHAPTER_CONVENTION_APPLIED")
    return updated, rebuilt, detached, scanned_chars, scanned_lines, warnings


def _source_chapters(source, global_start):
    """Run the R5 source converter while carrying volume context across files."""
    global _INHERITED_VOLUME
    if global_start == 0:
        _INHERITED_VOLUME = None

    units = sorted(
        source.units,
        key=lambda row: (_chapter._integer(row, "start_char", "unit"), _chapter._value(row, "unit_id", "unit")),
    )
    unit_by_id = {_chapter._value(row, "unit_id", "unit"): row for row in units}
    if len(unit_by_id) != len(units):
        raise _chapter.ChapterEngineError("duplicate Unit identifiers")
    heading_by_id = {_chapter._value(row, "heading_id", "heading"): row for row in source.headings}
    detached = _chapter._detached_heading_ids(source.structure_findings)
    source_binding_id = _chapter._stable_id(
        "csb_", _chapter.SOURCE_BINDING_SCHEMA_VERSION, source.project_id,
        source.source_sha256, source.input_order,
    )
    preceding_volume = _INHERITED_VOLUME
    local_order = 0
    seen_narrative = False
    result = []
    for row in units:
        unit_type = _chapter._value(row, "unit_type", "unit")
        ordinal = row.get("ordinal")
        if unit_type == "volume":
            if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0:
                if not seen_narrative or preceding_volume is None or ordinal >= preceding_volume:
                    preceding_volume = ordinal
            continue
        if unit_type not in _chapter._NARRATIVE_TYPES:
            continue
        unit_id = _chapter._value(row, "unit_id", "unit")
        start = _chapter._integer(row, "start_char", "unit")
        end = _chapter._integer(row, "end_char", "unit")
        body_start = _chapter._integer(row, "body_start_char", "unit")
        body_end = _chapter._integer(row, "body_end_char", "unit")
        if not 0 <= start < end <= len(source.source_text):
            raise _chapter.ChapterEngineError(f"Unit span outside source: {unit_id}")
        if not start <= body_start <= body_end <= end:
            raise _chapter.ChapterEngineError(f"Unit body span invalid: {unit_id}")
        content_sha = _chapter.sha256(source.source_text[start:end].encode("utf-8")).hexdigest()
        if content_sha != _chapter._value(row, "content_sha256", "unit"):
            raise _chapter.ChapterEngineError(f"Unit content SHA-256 mismatch: {unit_id}")
        heading_id = _chapter._optional_id(row, "heading_id", "unit")
        heading = heading_by_id.get(heading_id) if heading_id else None
        combined_volume = _chapter._heading_volume(heading)
        parent_volume = _chapter._parent_volume(row, unit_by_id)
        if combined_volume is not None and (preceding_volume is None or combined_volume >= preceding_volume):
            volume_ordinal, volume_basis = combined_volume, "combined_heading"
            preceding_volume = combined_volume
        elif parent_volume is not None and (preceding_volume is None or parent_volume >= preceding_volume):
            volume_ordinal, volume_basis = parent_volume, "parent_volume_unit"
            preceding_volume = parent_volume
        elif preceding_volume is not None:
            volume_ordinal, volume_basis = preceding_volume, "preceding_volume_context"
        else:
            volume_ordinal, volume_basis = None, "unknown"
        chapter_ordinal = (
            ordinal if unit_type == "chapter" and isinstance(ordinal, int)
            and not isinstance(ordinal, bool) and ordinal > 0 else None
        )
        chapter_basis = "explicit_heading" if chapter_ordinal is not None else "special_unit" if unit_type != "chapter" else "unknown"
        original_heading = ""
        heading_start = row.get("heading_start_char")
        heading_end = row.get("heading_end_char")
        if (
            isinstance(heading_start, int) and not isinstance(heading_start, bool)
            and isinstance(heading_end, int) and not isinstance(heading_end, bool)
            and 0 <= heading_start < heading_end <= len(source.source_text)
        ):
            original_heading = source.source_text[heading_start:heading_end].strip()
        title = str(row.get("title", ""))
        normalized_heading = " ".join(original_heading.split()) or title
        if heading_id is None:
            heading_status = "missing_heading"
        elif heading_id in detached:
            heading_status = "detached_title_candidate"
        elif title:
            heading_status = "explicit_title"
        else:
            heading_status = "titleless_heading"
        canonical_key = _chapter._canonical_key(
            volume_ordinal, chapter_ordinal, unit_type, source_binding_id, unit_id
        )
        result.append(_chapter.CanonicalChapter(
            _chapter.CHAPTER_RECORD_SCHEMA_VERSION,
            _chapter._stable_id("cch_", _chapter.CHAPTER_RECORD_SCHEMA_VERSION, source.source_sha256, unit_id, start, end, content_sha),
            source_binding_id, source.project_id, source.source_id, source.source_filename,
            source.source_sha256, source.input_order, local_order, global_start + local_order,
            unit_id, _chapter._optional_id(row, "parent_unit_id", "unit"), heading_id,
            unit_type, volume_ordinal, volume_basis, chapter_ordinal, chapter_basis,
            original_heading, normalized_heading, title, heading_status, start, end,
            _chapter._integer(row, "start_line", "unit"), _chapter._integer(row, "end_line", "unit"),
            heading_start if isinstance(heading_start, int) and not isinstance(heading_start, bool) else None,
            heading_end if isinstance(heading_end, int) and not isinstance(heading_end, bool) else None,
            body_start, body_end, content_sha, str(row.get("structure_confidence", "unknown")),
            str(row.get("review_status", "needs_review")),
            _chapter._contamination_status(start, end, source.anomaly_findings), canonical_key,
        ))
        local_order += 1
        seen_narrative = True
    _INHERITED_VOLUME = preceding_volume
    return result


def apply_stage8_r5_structure_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _structure._scan_headings = _scan_headings
    _chapter._source_chapters = _source_chapters
    _chapter.CHAPTER_ENGINE_VERSION = "tkr-chapter-engine-v2"
    _APPLIED = True


__all__ = ["PATCH_VERSION", "apply_stage8_r5_structure_patch"]
