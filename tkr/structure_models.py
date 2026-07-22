"""Typed Stage 2 structure contracts and deterministic identifiers."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Final, Iterable

STRUCTURE_REPORT_SCHEMA_VERSION: Final = "tkr-structure-report-v1"
HEADING_CANDIDATE_SCHEMA_VERSION: Final = "tkr-heading-candidate-v1"
UNIT_INDEX_SCHEMA_VERSION: Final = "tkr-unit-index-v1"
STRUCTURE_FINDING_SCHEMA_VERSION: Final = "tkr-structure-finding-v1"
STRUCTURE_DETECTOR_VERSION: Final = "5.9.0-stage2"
OFFSET_BASIS: Final = "decoded_text_without_external_bom"

class StructureInspectionError(ValueError):
    """Raised when deterministic structure inspection cannot finish safely."""

@dataclass(frozen=True, slots=True)
class StructurePolicy:
    max_heading_characters: int = 160
    max_units: int = 200_000
    max_findings: int = 50_000
    accept_markdown_headings: bool = True
    accept_split_numbered_heading: bool = True
    inline_title_max_characters: int = 48
    emit_empty_body_candidates: bool = True

    def __post_init__(self) -> None:
        for name in ("max_heading_characters", "max_units", "max_findings", "inline_title_max_characters"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise StructureInspectionError(f"{name} must be a positive integer")
        for name in ("accept_markdown_headings", "accept_split_numbered_heading", "emit_empty_body_candidates"):
            if not isinstance(getattr(self, name), bool):
                raise StructureInspectionError(f"{name} must be boolean")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

@dataclass(frozen=True, slots=True)
class HeadingCandidate:
    schema_version: str
    heading_id: str
    source_id: str
    source_sha256: str
    rule_id: str
    unit_type: str
    hierarchy_level: int
    ordinal: int | None
    ordinal_text: str
    title: str
    raw_heading: str
    boundary_start_char: int
    start_char: int
    end_char: int
    heading_end_char: int
    body_start_char: int
    start_line: int
    end_line: int
    confidence: str
    accepted_as_boundary: bool
    signals: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

@dataclass(frozen=True, slots=True)
class UnitRecord:
    schema_version: str
    unit_id: str
    source_id: str
    source_sha256: str
    unit_type: str
    hierarchy_level: int
    ordinal: int | None
    ordinal_text: str
    title: str
    parent_unit_id: str | None
    heading_id: str | None
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    heading_start_char: int | None
    heading_end_char: int | None
    body_start_char: int
    body_end_char: int
    character_count: int
    content_sha256: str
    structure_confidence: str
    review_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

@dataclass(frozen=True, slots=True)
class StructureFinding:
    schema_version: str
    finding_id: str
    rule_id: str
    category: str
    severity: str
    confidence: str
    recommended_action: str
    unit_id: str | None
    related_unit_ids: tuple[str, ...]
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    signals: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

@dataclass(frozen=True, slots=True)
class StructureInspectionReport:
    schema_version: str
    detector_version: str
    source_id: str
    source_sha256: str
    size_bytes: int
    selected_encoding: str | None
    offset_basis: str
    scan_status: str
    scanned_character_count: int
    scanned_line_count: int
    heading_candidate_count: int
    accepted_heading_count: int
    unit_count: int
    finding_count: int
    unit_type_counts: dict[str, int]
    finding_rule_counts: dict[str, int]
    coverage_character_count: int
    coverage_ratio: float
    gap_count: int
    overlap_count: int
    recommended_action: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    policy: dict[str, object]
    headings: tuple[HeadingCandidate, ...]
    units: tuple[UnitRecord, ...]
    findings: tuple[StructureFinding, ...]
    project_acceptance_performed: bool
    may_accept_project: bool
    may_freeze: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

_CHINESE_DIGITS = {
    "零": 0, "〇": 0, "○": 0, "一": 1, "二": 2, "两": 2, "兩": 2,
    "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CHINESE_UNITS = {
    "十": 10, "百": 100, "千": 1000, "万": 10_000, "萬": 10_000,
    "亿": 100_000_000, "億": 100_000_000,
}

def parse_ordinal(text: str) -> int | None:
    """Parse ASCII/full-width digits and conventional Chinese integers."""
    compact = "".join(text.split())
    normalized = compact.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized)
    if any(ch not in _CHINESE_DIGITS and ch not in _CHINESE_UNITS for ch in compact):
        return None
    total = section = number = 0
    for ch in compact:
        if ch in _CHINESE_DIGITS:
            number = _CHINESE_DIGITS[ch]
            continue
        unit = _CHINESE_UNITS[ch]
        if unit < 10_000:
            section += (number or 1) * unit
        else:
            section += number
            total += (section or 1) * unit
            section = 0
        number = 0
    return total + section + number

def heading_id(source_sha256: str, rule_id: str, start: int, end: int, raw: str) -> str:
    evidence = sha256(raw.encode("utf-8")).hexdigest()
    payload = "\0".join((HEADING_CANDIDATE_SCHEMA_VERSION, source_sha256, rule_id, str(start), str(end), evidence))
    return "hdg_" + sha256(payload.encode("utf-8")).hexdigest()[:32]

def unit_id(source_sha256: str, unit_type: str, start: int, end: int, content_sha256: str) -> str:
    payload = "\0".join((UNIT_INDEX_SCHEMA_VERSION, source_sha256, unit_type, str(start), str(end), content_sha256))
    return "unit_" + sha256(payload.encode("utf-8")).hexdigest()[:32]

def make_finding(*, source_sha256: str, rule_id: str, category: str, severity: str,
                 confidence: str, action: str, unit_id_value: str | None,
                 related: Iterable[str], start: int, end: int,
                 start_line: int, end_line: int, signals: Iterable[str]) -> StructureFinding:
    signal_tuple = tuple(signals)
    payload = "\0".join((STRUCTURE_FINDING_SCHEMA_VERSION, source_sha256, rule_id,
                          str(start), str(end), *signal_tuple))
    finding_id = "stf_" + sha256(payload.encode("utf-8")).hexdigest()[:32]
    return StructureFinding(
        STRUCTURE_FINDING_SCHEMA_VERSION, finding_id, rule_id, category, severity,
        confidence, action, unit_id_value, tuple(related), start, end,
        start_line, end_line, signal_tuple,
    )
