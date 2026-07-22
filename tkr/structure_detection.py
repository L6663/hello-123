"""Deterministic source-bound heading detection and non-overlapping Unit Index generation.

Stage 2 emits auditable candidates and records. It never repairs, deletes, accepts,
certifies, or freezes a corpus.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import io
from os import PathLike
from pathlib import Path
from typing import Iterator

from .encoding_inspection import EncodingInspectionError, inspect_source_encoding
from .hashing import DEFAULT_BLOCK_SIZE, HashingError, sha256_file
from .heading_detection import (
    DetectedHeading, FENCE_RE, SENTENCE_MARKS, SPLIT_PREFIX_RE, SPLIT_SUFFIX_RE,
    UNIT_CHAR_TO_TYPE, detect_heading, split_title_and_body,
)
from .structure_continuity import continuity_findings
from .structure_models import (
    HEADING_CANDIDATE_SCHEMA_VERSION, OFFSET_BASIS, STRUCTURE_DETECTOR_VERSION,
    STRUCTURE_REPORT_SCHEMA_VERSION, UNIT_INDEX_SCHEMA_VERSION,
    HeadingCandidate, StructureInspectionError, StructureInspectionReport,
    StructurePolicy, UnitRecord, heading_id, parse_ordinal, unit_id,
)

_BOM_PREFIX_BYTES = {
    "utf-8": b"\xef\xbb\xbf", "utf-16-le": b"\xff\xfe", "utf-16-be": b"\xfe\xff",
}

@dataclass(frozen=True, slots=True)
class _Boundary:
    heading: HeadingCandidate
    line_start_char: int

@dataclass(slots=True)
class _UnitBuild:
    unit_type: str
    hierarchy_level: int
    ordinal: int | None
    ordinal_text: str
    title: str
    heading: HeadingCandidate | None
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    body_start_char: int
    parent_index: int | None = None
    content_sha256: str = ""
    body_has_nonwhitespace: bool = False
    unit_id: str = ""

def _open_decoded(path: Path, report):
    raw = path.open("rb")
    prefix = _BOM_PREFIX_BYTES.get(report.bom, b"")
    if prefix and raw.read(len(prefix)) != prefix:
        raw.close()
        raise StructureInspectionError("source byte-order mark changed after encoding inspection")
    return io.TextIOWrapper(raw, encoding=report.selected_encoding, errors="strict", newline="")

def _physical_lines(handle) -> Iterator[tuple[int, int, str]]:
    offset = 0
    for line_number, line in enumerate(handle, start=1):
        yield line_number, offset, line
        offset += len(line)

def _content_without_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\r", "\n")):
        return line[:-1]
    return line

def _blocked_report(report, policy: StructurePolicy) -> StructureInspectionReport:
    return StructureInspectionReport(
        STRUCTURE_REPORT_SCHEMA_VERSION, STRUCTURE_DETECTOR_VERSION,
        report.source_id, report.source_sha256, report.size_bytes,
        report.selected_encoding, OFFSET_BASIS, "blocked", 0, 0, 0, 0, 0, 0,
        {}, {}, 0, 1.0 if report.size_bytes == 0 else 0.0, 0, 0,
        "resolve_source_blockers",
        tuple(dict.fromkeys((*report.blockers, "SOURCE_NOT_STRICTLY_DECODABLE_FOR_STRUCTURE_SCAN"))),
        tuple(report.warnings), policy.to_dict(), (), (), (), False, False, False,
    )

def _scan_headings(path: Path, encoding_report, policy: StructurePolicy):
    headings: list[HeadingCandidate] = []
    boundaries: list[_Boundary] = []
    detached_titles: list[tuple[str, int, int, int, str]] = []
    warnings = list(encoding_report.warnings)
    scanned_chars = scanned_lines = 0
    in_fence: str | None = None
    pending_split: tuple[int, int, str, str] | None = None
    pending_detached: HeadingCandidate | None = None

    with _open_decoded(path, encoding_report) as handle:
        for line_number, line_start, physical_line in _physical_lines(handle):
            scanned_lines = line_number
            scanned_chars = line_start + len(physical_line)
            content = _content_without_ending(physical_line)
            fence = FENCE_RE.match(content)
            if fence is not None:
                token = fence.group("fence")[0]
                in_fence = None if in_fence == token else token if in_fence is None else in_fence
                pending_split = pending_detached = None
                continue
            if in_fence is not None:
                pending_split = pending_detached = None
                continue

            detected: DetectedHeading | None = None
            boundary_start = line_start
            heading_start_line = heading_end_line = line_number
            raw_for_id = content
            if pending_split is not None and policy.accept_split_numbered_heading:
                previous_line, previous_start, previous_raw, number_text = pending_split
                suffix = SPLIT_SUFFIX_RE.match(content.lstrip())
                if suffix is not None:
                    unit_type, level = UNIT_CHAR_TO_TYPE[suffix.group("unit")]
                    ordinal = parse_ordinal(number_text)
                    leading = len(content) - len(content.lstrip())
                    marker_end = leading + suffix.start("rest")
                    title, heading_end, body_start, split_signals = split_title_and_body(
                        suffix.group("rest"), marker_end, policy.inline_title_max_characters
                    )
                    detected = DetectedHeading(
                        "SPLIT_NUMBERED_HEADING", unit_type, level, ordinal, number_text,
                        title, previous_raw + physical_line[:heading_end], 0, marker_end,
                        heading_end, body_start, "medium", ordinal is not None,
                        tuple(("heading_spans_two_lines",) + split_signals),
                    )
                    boundary_start = previous_start
                    heading_start_line = previous_line
                    raw_for_id = previous_raw + physical_line[:heading_end]
                pending_split = None
            if detected is None:
                prefix = SPLIT_PREFIX_RE.match(content)
                if prefix is not None and policy.accept_split_numbered_heading:
                    pending_split = (line_number, line_start, physical_line, prefix.group("number"))
                    continue
                detected = detect_heading(content, policy)

            if pending_detached is not None and content.strip():
                if detected is None:
                    stripped = content.strip()
                    start = line_start + len(content) - len(content.lstrip())
                    if len(stripped) <= policy.inline_title_max_characters and not any(mark in stripped for mark in SENTENCE_MARKS):
                        detached_titles.append((pending_detached.heading_id, start, start + len(stripped), line_number, stripped))
                pending_detached = None
            if detected is None:
                continue

            actual_start = line_start + detected.marker_start_in_line if detected.rule_id != "SPLIT_NUMBERED_HEADING" else boundary_start
            actual_end = line_start + detected.heading_end_in_line
            body_start_char = line_start + detected.body_start_in_line
            identifier = heading_id(encoding_report.source_sha256, detected.rule_id, actual_start, actual_end, raw_for_id)
            front_matter = 1 if (boundaries and boundaries[0].line_start_char > 0) or (not boundaries and boundary_start > 0) else 0
            projected_units = len(boundaries) + 1 + front_matter
            accepted = detected.accepted_as_boundary and projected_units <= policy.max_units
            signals = detected.signals
            if detected.accepted_as_boundary and not accepted:
                warnings.append("UNIT_LIMIT_REACHED")
                signals = (*signals, "unit_limit_prevented_boundary")
            heading = HeadingCandidate(
                HEADING_CANDIDATE_SCHEMA_VERSION, identifier,
                encoding_report.source_id, encoding_report.source_sha256,
                detected.rule_id, detected.unit_type, detected.hierarchy_level,
                detected.ordinal, detected.ordinal_text, detected.title,
                detected.raw_heading, boundary_start, actual_start, actual_end,
                actual_end, body_start_char, heading_start_line, heading_end_line,
                detected.confidence, accepted, signals,
            )
            headings.append(heading)
            if accepted:
                boundaries.append(_Boundary(heading, boundary_start))
                if not heading.title and heading.body_start_char == heading.heading_end_char:
                    pending_detached = heading
    if pending_split is not None:
        warnings.append("UNRESOLVED_SPLIT_HEADING_PREFIX")
    headings.sort(key=lambda item: (item.boundary_start_char, item.start_char, item.heading_id))
    deduped: list[_Boundary] = []
    seen: set[int] = set()
    for boundary in sorted(boundaries, key=lambda item: (item.line_start_char, item.heading.heading_id)):
        if boundary.line_start_char in seen:
            warnings.append("MULTIPLE_HEADINGS_AT_SAME_BOUNDARY")
            continue
        seen.add(boundary.line_start_char)
        deduped.append(boundary)
    return headings, deduped, detached_titles, scanned_chars, scanned_lines, warnings

def _build_units(boundaries: list[_Boundary], scanned_chars: int, scanned_lines: int) -> list[_UnitBuild]:
    if scanned_chars == 0:
        return []
    if not boundaries:
        return [_UnitBuild("document", 0, None, "", "", None, 0, scanned_chars, 1, scanned_lines, 0)]
    builds: list[_UnitBuild] = []
    first = boundaries[0]
    if first.line_start_char > 0:
        builds.append(_UnitBuild("front_matter", 0, None, "", "", None, 0,
                                 first.line_start_char, 1, max(1, first.heading.start_line - 1), 0))
    for index, boundary in enumerate(boundaries):
        end = boundaries[index + 1].line_start_char if index + 1 < len(boundaries) else scanned_chars
        end_line = boundaries[index + 1].heading.start_line - 1 if index + 1 < len(boundaries) else scanned_lines
        heading = boundary.heading
        builds.append(_UnitBuild(
            heading.unit_type, heading.hierarchy_level, heading.ordinal,
            heading.ordinal_text, heading.title, heading, boundary.line_start_char,
            end, heading.start_line, max(heading.start_line, end_line), heading.body_start_char,
        ))
    stack: dict[int, int] = {}
    for index, build in enumerate(builds):
        if build.heading is None:
            continue
        lower = [level for level in stack if level < build.hierarchy_level]
        build.parent_index = stack[max(lower)] if lower else None
        stack[build.hierarchy_level] = index
        for level in tuple(stack):
            if level > build.hierarchy_level:
                del stack[level]
    return builds

def _hash_units(path: Path, encoding_report, builds: list[_UnitBuild], scanned_chars: int) -> None:
    if not builds:
        return
    hashers = [sha256() for _ in builds]
    unit_index_value = 0
    char_pos = 0
    with _open_decoded(path, encoding_report) as handle:
        while True:
            text = handle.read(64 * 1024)
            if text == "":
                break
            cursor = 0
            while cursor < len(text):
                while unit_index_value < len(builds) and char_pos >= builds[unit_index_value].end_char:
                    unit_index_value += 1
                if unit_index_value >= len(builds):
                    raise StructureInspectionError("decoded text exceeds Unit Index coverage")
                build = builds[unit_index_value]
                take = min(len(text) - cursor, build.end_char - char_pos)
                segment = text[cursor:cursor + take]
                hashers[unit_index_value].update(segment.encode("utf-8"))
                if char_pos + take > build.body_start_char:
                    body_offset = max(0, build.body_start_char - char_pos)
                    if any(not character.isspace() for character in segment[body_offset:]):
                        build.body_has_nonwhitespace = True
                cursor += take
                char_pos += take
    if char_pos != scanned_chars:
        raise StructureInspectionError("decoded character count changed during Unit hashing")
    for build, hasher in zip(builds, hashers):
        build.content_sha256 = hasher.hexdigest()
        build.unit_id = unit_id(encoding_report.source_sha256, build.unit_type,
                                build.start_char, build.end_char, build.content_sha256)

def _records(builds: list[_UnitBuild], encoding_report) -> list[UnitRecord]:
    records: list[UnitRecord] = []
    for build in builds:
        parent = builds[build.parent_index].unit_id if build.parent_index is not None else None
        confidence = "high" if build.heading is None or build.heading.confidence == "high" else "medium"
        records.append(UnitRecord(
            UNIT_INDEX_SCHEMA_VERSION, build.unit_id, encoding_report.source_id,
            encoding_report.source_sha256, build.unit_type, build.hierarchy_level,
            build.ordinal, build.ordinal_text, build.title, parent,
            None if build.heading is None else build.heading.heading_id,
            build.start_char, build.end_char, build.start_line, build.end_line,
            None if build.heading is None else build.heading.start_char,
            None if build.heading is None else build.heading.heading_end_char,
            build.body_start_char, build.end_char, build.end_char - build.start_char,
            build.content_sha256, confidence,
            "accepted_candidate" if confidence == "high" else "review",
        ))
    return records

def _coverage(units: list[UnitRecord], scanned_chars: int) -> tuple[int, int, int]:
    coverage = gap_count = overlap_count = 0
    previous_end = 0
    for unit in units:
        gap_count += unit.start_char > previous_end
        overlap_count += unit.start_char < previous_end
        coverage += max(0, unit.end_char - max(unit.start_char, previous_end))
        previous_end = max(previous_end, unit.end_char)
    if units and units[0].start_char != 0:
        gap_count += 1
    if units and units[-1].end_char != scanned_chars:
        gap_count += 1
    if scanned_chars and not units:
        gap_count += 1
    return coverage, gap_count, overlap_count

def inspect_source_structure(path: str | PathLike[str], *, policy: StructurePolicy | None = None,
                             block_size: int = DEFAULT_BLOCK_SIZE) -> StructureInspectionReport:
    """Build deterministic headings, Unit records, and continuity findings."""
    active = policy or StructurePolicy()
    try:
        encoding_report = inspect_source_encoding(path, block_size=block_size)
    except EncodingInspectionError as exc:
        raise StructureInspectionError(str(exc)) from exc
    if not encoding_report.strict_decode_passed or encoding_report.selected_encoding is None:
        return _blocked_report(encoding_report, active)
    candidate = Path(path)
    try:
        headings, boundaries, detached, scanned_chars, scanned_lines, warnings = _scan_headings(
            candidate, encoding_report, active
        )
        builds = _build_units(boundaries, scanned_chars, scanned_lines)
        _hash_units(candidate, encoding_report, builds, scanned_chars)
    except (OSError, UnicodeError) as exc:
        raise StructureInspectionError(f"structure scan failed: {exc}") from exc
    units = _records(builds, encoding_report)
    findings, finding_warnings = continuity_findings(
        source_sha256=encoding_report.source_sha256, units=units,
        body_nonwhitespace=[build.body_has_nonwhitespace for build in builds],
        headings=headings, detached_titles=detached,
        emit_empty_body_candidates=active.emit_empty_body_candidates,
        max_findings=active.max_findings,
    )
    warnings.extend(finding_warnings)
    coverage, gap_count, overlap_count = _coverage(units, scanned_chars)
    try:
        final_sha256 = sha256_file(candidate, block_size=block_size)
    except HashingError as exc:
        raise StructureInspectionError(str(exc)) from exc
    if final_sha256 != encoding_report.source_sha256:
        raise StructureInspectionError("source changed during structure inspection")
    coverage_ratio = 1.0 if scanned_chars == 0 else coverage / scanned_chars
    action = (
        "resolve_unit_coverage_failure" if gap_count or overlap_count else
        "review_structure_candidates" if findings else
        "review_source_warnings" if warnings else "structure_candidates_ready"
    )
    return StructureInspectionReport(
        STRUCTURE_REPORT_SCHEMA_VERSION, STRUCTURE_DETECTOR_VERSION,
        encoding_report.source_id, encoding_report.source_sha256, encoding_report.size_bytes,
        encoding_report.selected_encoding, OFFSET_BASIS, "completed", scanned_chars,
        scanned_lines, len(headings), len(boundaries), len(units), len(findings),
        dict(sorted(Counter(unit.unit_type for unit in units).items())),
        dict(sorted(Counter(finding.rule_id for finding in findings).items())),
        coverage, coverage_ratio, gap_count, overlap_count, action, (),
        tuple(dict.fromkeys(warnings)), active.to_dict(), tuple(headings),
        tuple(units), tuple(findings), False, False, False,
    )

def validate_structure_report(report: StructureInspectionReport) -> None:
    """Validate hard coverage and authorization invariants."""
    if report.project_acceptance_performed or report.may_accept_project or report.may_freeze:
        raise StructureInspectionError("Stage 2 cannot authorize project acceptance or freezing")
    if report.scan_status == "blocked":
        if report.units or report.headings:
            raise StructureInspectionError("blocked report must not contain units or headings")
        return
    if report.gap_count or report.overlap_count:
        raise StructureInspectionError("Unit Index contains gaps or overlaps")
    if report.coverage_character_count != report.scanned_character_count:
        raise StructureInspectionError("Unit coverage does not match decoded length")
    if report.scanned_character_count and not report.units:
        raise StructureInspectionError("non-empty source requires at least one Unit")
    previous_end = 0
    seen: set[str] = set()
    for unit in report.units:
        if unit.unit_id in seen:
            raise StructureInspectionError("duplicate unit_id")
        seen.add(unit.unit_id)
        if unit.start_char != previous_end or unit.end_char <= unit.start_char:
            raise StructureInspectionError("Units must be contiguous and non-empty")
        if unit.character_count != unit.end_char - unit.start_char:
            raise StructureInspectionError("Unit character_count mismatch")
        previous_end = unit.end_char
    if previous_end != report.scanned_character_count:
        raise StructureInspectionError("final Unit end does not equal source length")

__all__ = [
    "HeadingCandidate", "StructureFinding", "StructureInspectionError",
    "StructureInspectionReport", "StructurePolicy", "UnitRecord",
    "inspect_source_structure", "parse_ordinal", "validate_structure_report",
]
