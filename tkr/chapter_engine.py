"""Deterministic Stage 2 canonical chapter catalog.

The existing structure scanner produces source-covering Unit records.  This
module lifts those records into a multi-source chapter catalog without changing
source text or pretending that inferred order is an original fact.

Key guarantees:

* every chapter remains bound to one verified source, Unit, span and SHA-256;
* physical order and canonical-order candidates are stored separately;
* volume inheritance records its exact basis;
* gaps, inversions, duplicates, unknown ordinals and contamination remain
  explicit findings;
* canonical mappings never rewrite or renumber the corpus.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Final, Iterable, Mapping, Sequence

CHAPTER_ENGINE_VERSION: Final = "tkr-chapter-engine-v1"
SOURCE_BINDING_SCHEMA_VERSION: Final = "tkr-chapter-source-binding-v1"
CHAPTER_RECORD_SCHEMA_VERSION: Final = "tkr-canonical-chapter-v1"
CHAPTER_FINDING_SCHEMA_VERSION: Final = "tkr-chapter-finding-v1"
CANONICAL_ORDER_SCHEMA_VERSION: Final = "tkr-canonical-order-v1"
CHAPTER_CATALOG_REPORT_SCHEMA_VERSION: Final = "tkr-chapter-catalog-report-v1"

_NARRATIVE_TYPES: Final = frozenset({"chapter", "prologue", "epilogue", "extra_story"})
_TERMINAL_TYPES: Final = frozenset({"epilogue", "afterword"})


class ChapterEngineError(ValueError):
    """Raised when chapter records cannot be derived without corruption."""


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\0".join(
        json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if isinstance(part, (dict, list, tuple))
        else str(part)
        for part in parts
    )
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:32]


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ChapterEngineError(f"{name} must be a string")
    if not allow_empty and not value:
        raise ChapterEngineError(f"{name} must be non-empty")
    return value


def _require_nonnegative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ChapterEngineError(f"{name} must be a non-negative integer")
    return value


def _optional_positive(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ChapterEngineError(f"{name} must be a positive integer or null")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ChapterSourceInput:
    project_id: str
    source_id: str
    source_filename: str
    source_sha256: str
    input_order: int
    source_text: str
    units: tuple[Mapping[str, object], ...]
    headings: tuple[Mapping[str, object], ...]
    anomaly_findings: tuple[Mapping[str, object], ...] = ()
    structure_findings: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        for name in ("project_id", "source_id", "source_filename", "source_sha256"):
            _require_text(getattr(self, name), name)
        _require_nonnegative(self.input_order, "input_order")
        if sha256(self.source_text.encode("utf-8")).hexdigest() != self.source_sha256:
            raise ChapterEngineError("source text SHA-256 differs from source binding")
        if not self.units:
            raise ChapterEngineError("chapter source input requires Unit records")


@dataclass(frozen=True, slots=True)
class SourceBinding:
    schema_version: str
    source_binding_id: str
    project_id: str
    source_id: str
    source_filename: str
    source_sha256: str
    input_order: int
    chapter_count: int
    first_known_volume: int | None
    first_known_chapter: int | None
    last_known_volume: int | None
    last_known_chapter: int | None
    numbering_coverage: float

    def __post_init__(self) -> None:
        if self.schema_version != SOURCE_BINDING_SCHEMA_VERSION:
            raise ChapterEngineError("source binding schema version mismatch")
        for name in (
            "source_binding_id", "project_id", "source_id", "source_filename", "source_sha256"
        ):
            _require_text(getattr(self, name), name)
        _require_nonnegative(self.input_order, "input_order")
        _require_nonnegative(self.chapter_count, "chapter_count")
        for name in (
            "first_known_volume", "first_known_chapter", "last_known_volume", "last_known_chapter"
        ):
            _optional_positive(getattr(self, name), name)
        if not 0.0 <= self.numbering_coverage <= 1.0:
            raise ChapterEngineError("numbering_coverage must be between zero and one")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CanonicalChapter:
    schema_version: str
    chapter_id: str
    source_binding_id: str
    project_id: str
    source_id: str
    source_filename: str
    source_sha256: str
    source_input_order: int
    local_physical_order: int
    global_physical_order: int
    unit_id: str
    parent_unit_id: str | None
    heading_id: str | None
    unit_type: str
    volume_ordinal: int | None
    volume_basis: str
    chapter_ordinal: int | None
    chapter_basis: str
    original_heading: str
    normalized_heading: str
    title: str
    heading_status: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    heading_start_char: int | None
    heading_end_char: int | None
    body_start_char: int
    body_end_char: int
    content_sha256: str
    structure_confidence: str
    review_status: str
    contamination_status: str
    canonical_key: str

    def __post_init__(self) -> None:
        if self.schema_version != CHAPTER_RECORD_SCHEMA_VERSION:
            raise ChapterEngineError("chapter schema version mismatch")
        for name in (
            "chapter_id", "source_binding_id", "project_id", "source_id",
            "source_filename", "source_sha256", "unit_id", "unit_type",
            "volume_basis", "chapter_basis", "original_heading",
            "normalized_heading", "title", "heading_status", "content_sha256",
            "structure_confidence", "review_status", "contamination_status",
            "canonical_key",
        ):
            _require_text(getattr(self, name), name, allow_empty=name in {
                "original_heading", "normalized_heading", "title"
            })
        for name in (
            "source_input_order", "local_physical_order", "global_physical_order",
            "start_char", "end_char", "start_line", "end_line", "body_start_char",
            "body_end_char",
        ):
            _require_nonnegative(getattr(self, name), name)
        if not self.start_char < self.end_char:
            raise ChapterEngineError("chapter span must be non-empty")
        if not self.start_char <= self.body_start_char <= self.body_end_char <= self.end_char:
            raise ChapterEngineError("chapter body span is invalid")
        _optional_positive(self.volume_ordinal, "volume_ordinal")
        _optional_positive(self.chapter_ordinal, "chapter_ordinal")
        if self.volume_basis not in {
            "combined_heading", "parent_volume_unit", "preceding_volume_context", "unknown"
        }:
            raise ChapterEngineError("unsupported volume basis")
        if self.chapter_basis not in {"explicit_heading", "special_unit", "unknown"}:
            raise ChapterEngineError("unsupported chapter basis")
        if self.heading_status not in {
            "explicit_title", "titleless_heading", "missing_heading", "detached_title_candidate"
        }:
            raise ChapterEngineError("unsupported heading status")
        if self.contamination_status not in {
            "clean", "contaminated", "non_body", "needs_review"
        }:
            raise ChapterEngineError("unsupported contamination status")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChapterFinding:
    schema_version: str
    finding_id: str
    rule_id: str
    category: str
    severity: str
    confidence: str
    recommended_action: str
    chapter_ids: tuple[str, ...]
    source_binding_ids: tuple[str, ...]
    canonical_key: str
    signals: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CHAPTER_FINDING_SCHEMA_VERSION:
            raise ChapterEngineError("chapter finding schema version mismatch")
        for name in (
            "finding_id", "rule_id", "category", "severity", "confidence",
            "recommended_action", "canonical_key",
        ):
            _require_text(getattr(self, name), name, allow_empty=name == "canonical_key")
        if len(self.chapter_ids) != len(set(self.chapter_ids)):
            raise ChapterEngineError("chapter finding chapter IDs must be unique")
        if len(self.source_binding_ids) != len(set(self.source_binding_ids)):
            raise ChapterEngineError("chapter finding source bindings must be unique")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["chapter_ids"] = list(self.chapter_ids)
        payload["source_binding_ids"] = list(self.source_binding_ids)
        payload["signals"] = list(self.signals)
        return payload


@dataclass(frozen=True, slots=True)
class CanonicalOrderRecord:
    schema_version: str
    canonical_position: int
    chapter_id: str
    canonical_key: str
    physical_position: int
    order_basis: str
    confidence: str

    def __post_init__(self) -> None:
        if self.schema_version != CANONICAL_ORDER_SCHEMA_VERSION:
            raise ChapterEngineError("canonical order schema version mismatch")
        _require_nonnegative(self.canonical_position, "canonical_position")
        _require_nonnegative(self.physical_position, "physical_position")
        _require_text(self.chapter_id, "chapter_id")
        _require_text(self.canonical_key, "canonical_key")
        if self.order_basis not in {
            "explicit_volume_and_chapter", "special_unit_physical_fallback",
            "unresolved_physical_fallback",
        }:
            raise ChapterEngineError("unsupported canonical order basis")
        if self.confidence not in {"high", "medium", "low"}:
            raise ChapterEngineError("unsupported canonical order confidence")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChapterCatalogReport:
    schema_version: str
    chapter_engine_version: str
    source_count: int
    chapter_count: int
    numbered_chapter_count: int
    special_unit_count: int
    finding_count: int
    duplicate_key_count: int
    duplicate_content_count: int
    gap_count: int
    inversion_count: int
    unresolved_volume_count: int
    unresolved_chapter_count: int
    contaminated_or_review_count: int
    numbering_coverage: float
    physical_order_preserved: bool
    canonical_order_is_candidate: bool
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != CHAPTER_CATALOG_REPORT_SCHEMA_VERSION:
            raise ChapterEngineError("chapter catalog report schema version mismatch")
        if self.chapter_engine_version != CHAPTER_ENGINE_VERSION:
            raise ChapterEngineError("chapter engine version mismatch")
        for name in (
            "source_count", "chapter_count", "numbered_chapter_count", "special_unit_count",
            "finding_count", "duplicate_key_count", "duplicate_content_count", "gap_count",
            "inversion_count", "unresolved_volume_count", "unresolved_chapter_count",
            "contaminated_or_review_count",
        ):
            _require_nonnegative(getattr(self, name), name)
        if not 0.0 <= self.numbering_coverage <= 1.0:
            raise ChapterEngineError("numbering_coverage must be between zero and one")
        if not self.physical_order_preserved or not self.canonical_order_is_candidate:
            raise ChapterEngineError("Stage 2 must preserve physical order and candidate status")
        if any((
            self.project_acceptance_performed, self.may_accept_project,
            self.may_release, self.may_freeze,
        )):
            raise ChapterEngineError("Stage 2 catalog cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChapterCatalog:
    sources: tuple[SourceBinding, ...]
    chapters: tuple[CanonicalChapter, ...]
    canonical_order: tuple[CanonicalOrderRecord, ...]
    findings: tuple[ChapterFinding, ...]
    report: ChapterCatalogReport


def _value(row: Mapping[str, object], key: str, label: str) -> str:
    return _require_text(row.get(key), f"{label}.{key}")


def _integer(row: Mapping[str, object], key: str, label: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChapterEngineError(f"{label}.{key} must be an integer")
    return value


def _optional_id(row: Mapping[str, object], key: str, label: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    return _require_text(value, f"{label}.{key}")


def _heading_volume(heading: Mapping[str, object] | None) -> int | None:
    if heading is None:
        return None
    signals = heading.get("signals", [])
    if not isinstance(signals, (list, tuple)):
        return None
    for signal in signals:
        if not isinstance(signal, str) or not signal.startswith("container_ordinal="):
            continue
        raw = signal.split("=", 1)[1]
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if value > 0 else None
    return None


def _overlap(start: int, end: int, row: Mapping[str, object]) -> bool:
    other_start = row.get("start_char")
    other_end = row.get("end_char")
    return (
        isinstance(other_start, int) and not isinstance(other_start, bool)
        and isinstance(other_end, int) and not isinstance(other_end, bool)
        and start < other_end and other_start < end
    )


def _contamination_status(
    start: int, end: int, findings: Sequence[Mapping[str, object]]
) -> str:
    overlapping = [row for row in findings if _overlap(start, end, row)]
    if any(row.get("category") == "contamination_candidate" for row in overlapping):
        return "contaminated"
    if any(row.get("category") == "paratext_candidate" for row in overlapping):
        return "non_body"
    if any(row.get("severity") == "high" for row in overlapping):
        return "needs_review"
    return "clean"


def _finding(
    rule_id: str,
    category: str,
    severity: str,
    confidence: str,
    action: str,
    chapters: Sequence[CanonicalChapter],
    canonical_key: str = "",
    signals: Iterable[str] = (),
) -> ChapterFinding:
    chapter_ids = tuple(sorted({item.chapter_id for item in chapters}))
    source_ids = tuple(sorted({item.source_binding_id for item in chapters}))
    signal_tuple = tuple(signals)
    return ChapterFinding(
        CHAPTER_FINDING_SCHEMA_VERSION,
        _stable_id("chf_", rule_id, chapter_ids, canonical_key, signal_tuple),
        rule_id,
        category,
        severity,
        confidence,
        action,
        chapter_ids,
        source_ids,
        canonical_key,
        signal_tuple,
    )


def _detached_heading_ids(findings: Sequence[Mapping[str, object]]) -> set[str]:
    result: set[str] = set()
    for row in findings:
        if row.get("rule_id") != "DETACHED_TITLE_CANDIDATE":
            continue
        signals = row.get("signals", [])
        if not isinstance(signals, (list, tuple)):
            continue
        for signal in signals:
            if isinstance(signal, str) and signal.startswith("heading_id="):
                result.add(signal.split("=", 1)[1])
    return result


def _parent_volume(
    unit: Mapping[str, object], unit_by_id: Mapping[str, Mapping[str, object]]
) -> int | None:
    seen: set[str] = set()
    parent_id = unit.get("parent_unit_id")
    while isinstance(parent_id, str) and parent_id:
        if parent_id in seen:
            raise ChapterEngineError("Unit parent cycle detected")
        seen.add(parent_id)
        parent = unit_by_id.get(parent_id)
        if parent is None:
            raise ChapterEngineError(f"Unit references unknown parent: {parent_id}")
        if parent.get("unit_type") == "volume":
            ordinal = parent.get("ordinal")
            return ordinal if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0 else None
        parent_id = parent.get("parent_unit_id")
    return None


def _canonical_key(
    volume: int | None, chapter: int | None, unit_type: str, source_binding_id: str, unit_id: str
) -> str:
    if unit_type == "chapter" and volume is not None and chapter is not None:
        return f"v{volume:06d}-c{chapter:06d}"
    if unit_type != "chapter" and volume is not None:
        return f"v{volume:06d}-special-{unit_type}-{unit_id[-8:]}"
    return f"unresolved-{source_binding_id[-8:]}-{unit_id[-8:]}"


def _source_chapters(source: ChapterSourceInput, global_start: int) -> list[CanonicalChapter]:
    units = sorted(
        source.units,
        key=lambda row: (_integer(row, "start_char", "unit"), _value(row, "unit_id", "unit")),
    )
    unit_by_id = {_value(row, "unit_id", "unit"): row for row in units}
    if len(unit_by_id) != len(units):
        raise ChapterEngineError("duplicate Unit identifiers")
    heading_by_id = {
        _value(row, "heading_id", "heading"): row for row in source.headings
    }
    detached = _detached_heading_ids(source.structure_findings)
    source_binding_id = _stable_id(
        "csb_", SOURCE_BINDING_SCHEMA_VERSION, source.project_id, source.source_sha256, source.input_order
    )
    preceding_volume: int | None = None
    local_order = 0
    result: list[CanonicalChapter] = []
    for row in units:
        unit_type = _value(row, "unit_type", "unit")
        ordinal = row.get("ordinal")
        if unit_type == "volume":
            if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0:
                preceding_volume = ordinal
            continue
        if unit_type not in _NARRATIVE_TYPES:
            continue
        unit_id = _value(row, "unit_id", "unit")
        start = _integer(row, "start_char", "unit")
        end = _integer(row, "end_char", "unit")
        body_start = _integer(row, "body_start_char", "unit")
        body_end = _integer(row, "body_end_char", "unit")
        if not 0 <= start < end <= len(source.source_text):
            raise ChapterEngineError(f"Unit span outside source: {unit_id}")
        if not start <= body_start <= body_end <= end:
            raise ChapterEngineError(f"Unit body span invalid: {unit_id}")
        content_sha = _value(row, "content_sha256", "unit")
        if sha256(source.source_text[start:end].encode("utf-8")).hexdigest() != content_sha:
            raise ChapterEngineError(f"Unit content SHA-256 mismatch: {unit_id}")
        heading_id = _optional_id(row, "heading_id", "unit")
        heading = heading_by_id.get(heading_id) if heading_id else None
        combined_volume = _heading_volume(heading)
        parent_volume = _parent_volume(row, unit_by_id)
        if combined_volume is not None:
            volume_ordinal, volume_basis = combined_volume, "combined_heading"
        elif parent_volume is not None:
            volume_ordinal, volume_basis = parent_volume, "parent_volume_unit"
        elif preceding_volume is not None:
            volume_ordinal, volume_basis = preceding_volume, "preceding_volume_context"
        else:
            volume_ordinal, volume_basis = None, "unknown"
        chapter_ordinal = (
            ordinal if unit_type == "chapter" and isinstance(ordinal, int)
            and not isinstance(ordinal, bool) and ordinal > 0 else None
        )
        chapter_basis = (
            "explicit_heading" if chapter_ordinal is not None
            else "special_unit" if unit_type != "chapter" else "unknown"
        )
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
        canonical_key = _canonical_key(
            volume_ordinal, chapter_ordinal, unit_type, source_binding_id, unit_id
        )
        result.append(
            CanonicalChapter(
                CHAPTER_RECORD_SCHEMA_VERSION,
                _stable_id(
                    "cch_", CHAPTER_RECORD_SCHEMA_VERSION, source.source_sha256,
                    unit_id, start, end, content_sha,
                ),
                source_binding_id,
                source.project_id,
                source.source_id,
                source.source_filename,
                source.source_sha256,
                source.input_order,
                local_order,
                global_start + local_order,
                unit_id,
                _optional_id(row, "parent_unit_id", "unit"),
                heading_id,
                unit_type,
                volume_ordinal,
                volume_basis,
                chapter_ordinal,
                chapter_basis,
                original_heading,
                normalized_heading,
                title,
                heading_status,
                start,
                end,
                _integer(row, "start_line", "unit"),
                _integer(row, "end_line", "unit"),
                heading_start if isinstance(heading_start, int) and not isinstance(heading_start, bool) else None,
                heading_end if isinstance(heading_end, int) and not isinstance(heading_end, bool) else None,
                body_start,
                body_end,
                content_sha,
                str(row.get("structure_confidence", "unknown")),
                str(row.get("review_status", "needs_review")),
                _contamination_status(start, end, source.anomaly_findings),
                canonical_key,
            )
        )
        local_order += 1
    return result


def _findings(chapters: Sequence[CanonicalChapter]) -> list[ChapterFinding]:
    result: list[ChapterFinding] = []
    numbered = [
        item for item in chapters
        if item.unit_type == "chapter" and item.volume_ordinal is not None
        and item.chapter_ordinal is not None
    ]
    by_key: dict[str, list[CanonicalChapter]] = {}
    by_content: dict[str, list[CanonicalChapter]] = {}
    for item in chapters:
        by_key.setdefault(item.canonical_key, []).append(item)
        by_content.setdefault(item.content_sha256, []).append(item)
        if item.volume_ordinal is None:
            result.append(_finding(
                "MISSING_VOLUME_ORDINAL", "addressability", "medium", "high",
                "review_volume_context", (item,), item.canonical_key,
                (f"volume_basis={item.volume_basis}",),
            ))
        if item.unit_type == "chapter" and item.chapter_ordinal is None:
            result.append(_finding(
                "MISSING_CHAPTER_ORDINAL", "addressability", "high", "high",
                "review_chapter_heading", (item,), item.canonical_key,
            ))
        if item.heading_status == "missing_heading":
            result.append(_finding(
                "MISSING_HEADING", "heading_recovery", "high", "high",
                "review_missing_heading", (item,), item.canonical_key,
            ))
        elif item.heading_status == "titleless_heading":
            result.append(_finding(
                "TITLELESS_HEADING", "heading_recovery", "low", "high",
                "review_optional_title", (item,), item.canonical_key,
            ))
        elif item.heading_status == "detached_title_candidate":
            result.append(_finding(
                "DETACHED_TITLE_REVIEW", "heading_recovery", "low", "medium",
                "review_before_attaching_title", (item,), item.canonical_key,
            ))
        if item.body_start_char == item.body_end_char:
            result.append(_finding(
                "EMPTY_CHAPTER_BODY", "structure_anomaly", "high", "high",
                "review_missing_or_misdetected_body", (item,), item.canonical_key,
            ))
        if item.contamination_status != "clean" or item.review_status == "review":
            result.append(_finding(
                "CHAPTER_NOT_CLEAN", "source_quality", "high", "high",
                "exclude_from_canonical_fact_generation", (item,), item.canonical_key,
                (f"contamination_status={item.contamination_status}", f"review_status={item.review_status}"),
            ))
    for key, rows in by_key.items():
        if key.startswith("unresolved-") or len(rows) < 2:
            continue
        result.append(_finding(
            "DUPLICATE_CANONICAL_KEY", "continuity_anomaly", "high", "high",
            "review_duplicate_or_wrong_numbering", rows, key,
            tuple(f"content_sha256={row.content_sha256}" for row in rows),
        ))
        titles = {row.normalized_heading for row in rows if row.normalized_heading}
        if len(titles) > 1:
            result.append(_finding(
                "CONFLICTING_HEADINGS_FOR_KEY", "heading_conflict", "high", "high",
                "review_title_or_numbering_conflict", rows, key,
                tuple(f"heading={value}" for value in sorted(titles)),
            ))
    for content_sha, rows in by_content.items():
        keys = {row.canonical_key for row in rows}
        if len(rows) > 1 and len(keys) > 1:
            result.append(_finding(
                "DUPLICATE_CHAPTER_CONTENT", "duplicate_content", "medium", "high",
                "review_duplicate_text_without_deleting", rows, "",
                (f"content_sha256={content_sha}", *tuple(f"canonical_key={key}" for key in sorted(keys))),
            ))
    by_volume: dict[int, list[CanonicalChapter]] = {}
    for item in numbered:
        assert item.volume_ordinal is not None
        by_volume.setdefault(item.volume_ordinal, []).append(item)
    for volume, rows in by_volume.items():
        physical = sorted(rows, key=lambda item: item.global_physical_order)
        previous: CanonicalChapter | None = None
        for item in physical:
            if previous is not None:
                assert previous.chapter_ordinal is not None and item.chapter_ordinal is not None
                if item.chapter_ordinal < previous.chapter_ordinal:
                    result.append(_finding(
                        "CHAPTER_ORDINAL_INVERSION", "continuity_anomaly", "high", "high",
                        "review_physical_or_numbering_order", (previous, item), item.canonical_key,
                        (f"volume={volume}", f"previous={previous.chapter_ordinal}", f"current={item.chapter_ordinal}"),
                    ))
                elif item.chapter_ordinal > previous.chapter_ordinal + 1:
                    result.append(_finding(
                        "CHAPTER_ORDINAL_GAP", "continuity_anomaly", "medium", "high",
                        "review_missing_or_intentionally_absent_chapters", (previous, item), item.canonical_key,
                        (
                            f"volume={volume}", f"previous={previous.chapter_ordinal}",
                            f"current={item.chapter_ordinal}",
                            f"missing_start={previous.chapter_ordinal + 1}",
                            f"missing_end={item.chapter_ordinal - 1}",
                        ),
                    ))
            previous = item
    physical = sorted(chapters, key=lambda item: item.global_physical_order)
    terminal: CanonicalChapter | None = None
    for item in physical:
        if terminal is not None and item.unit_type == "chapter":
            result.append(_finding(
                "CHAPTER_AFTER_TERMINAL_UNIT", "placement_anomaly", "medium", "medium",
                "review_special_unit_placement", (terminal, item), item.canonical_key,
            ))
        if item.unit_type in _TERMINAL_TYPES:
            terminal = item
    return sorted(result, key=lambda item: (item.rule_id, item.canonical_key, item.finding_id))


def _order(chapters: Sequence[CanonicalChapter]) -> list[CanonicalOrderRecord]:
    def key(item: CanonicalChapter) -> tuple[object, ...]:
        if item.unit_type == "chapter" and item.volume_ordinal is not None and item.chapter_ordinal is not None:
            return (0, item.volume_ordinal, item.chapter_ordinal, item.global_physical_order)
        if item.unit_type != "chapter" and item.volume_ordinal is not None:
            return (1, item.volume_ordinal, item.global_physical_order, 0)
        return (2, item.global_physical_order, 0, 0)
    ordered = sorted(chapters, key=key)
    result: list[CanonicalOrderRecord] = []
    for position, item in enumerate(ordered):
        if item.unit_type == "chapter" and item.volume_ordinal is not None and item.chapter_ordinal is not None:
            basis, confidence = "explicit_volume_and_chapter", "high"
        elif item.unit_type != "chapter" and item.volume_ordinal is not None:
            basis, confidence = "special_unit_physical_fallback", "medium"
        else:
            basis, confidence = "unresolved_physical_fallback", "low"
        result.append(CanonicalOrderRecord(
            CANONICAL_ORDER_SCHEMA_VERSION, position, item.chapter_id, item.canonical_key,
            item.global_physical_order, basis, confidence,
        ))
    return result


def build_chapter_catalog(inputs: Sequence[ChapterSourceInput]) -> ChapterCatalog:
    """Build one deterministic chapter catalog from explicitly ordered sources."""
    if not inputs:
        raise ChapterEngineError("at least one source project is required")
    ordered_inputs = sorted(inputs, key=lambda item: (item.input_order, item.source_id))
    if len({item.input_order for item in ordered_inputs}) != len(ordered_inputs):
        raise ChapterEngineError("source input orders must be unique")
    if len({item.project_id for item in ordered_inputs}) != len(ordered_inputs):
        raise ChapterEngineError("source project IDs must be unique")
    chapters: list[CanonicalChapter] = []
    for source in ordered_inputs:
        chapters.extend(_source_chapters(source, len(chapters)))
    source_bindings: list[SourceBinding] = []
    for source in ordered_inputs:
        rows = [item for item in chapters if item.project_id == source.project_id]
        known = [
            item for item in rows
            if item.unit_type == "chapter" and item.volume_ordinal is not None
            and item.chapter_ordinal is not None
        ]
        known_sorted = sorted(
            known, key=lambda item: (item.global_physical_order, item.chapter_id)
        )
        source_bindings.append(SourceBinding(
            SOURCE_BINDING_SCHEMA_VERSION,
            _stable_id("csb_", SOURCE_BINDING_SCHEMA_VERSION, source.project_id, source.source_sha256, source.input_order),
            source.project_id,
            source.source_id,
            source.source_filename,
            source.source_sha256,
            source.input_order,
            len(rows),
            known_sorted[0].volume_ordinal if known_sorted else None,
            known_sorted[0].chapter_ordinal if known_sorted else None,
            known_sorted[-1].volume_ordinal if known_sorted else None,
            known_sorted[-1].chapter_ordinal if known_sorted else None,
            len(known) / len([item for item in rows if item.unit_type == "chapter"])
            if any(item.unit_type == "chapter" for item in rows) else 1.0,
        ))
    findings = _findings(chapters)
    canonical_order = _order(chapters)
    numbered_count = sum(
        item.unit_type == "chapter" and item.volume_ordinal is not None
        and item.chapter_ordinal is not None for item in chapters
    )
    report = ChapterCatalogReport(
        CHAPTER_CATALOG_REPORT_SCHEMA_VERSION,
        CHAPTER_ENGINE_VERSION,
        len(source_bindings),
        len(chapters),
        numbered_count,
        sum(item.unit_type != "chapter" for item in chapters),
        len(findings),
        sum(item.rule_id == "DUPLICATE_CANONICAL_KEY" for item in findings),
        sum(item.rule_id == "DUPLICATE_CHAPTER_CONTENT" for item in findings),
        sum(item.rule_id == "CHAPTER_ORDINAL_GAP" for item in findings),
        sum(item.rule_id == "CHAPTER_ORDINAL_INVERSION" for item in findings),
        sum(item.volume_ordinal is None for item in chapters),
        sum(item.unit_type == "chapter" and item.chapter_ordinal is None for item in chapters),
        sum(item.contamination_status != "clean" or item.review_status == "review" for item in chapters),
        numbered_count / sum(item.unit_type == "chapter" for item in chapters)
        if any(item.unit_type == "chapter" for item in chapters) else 1.0,
        True,
        True,
    )
    return ChapterCatalog(
        tuple(source_bindings),
        tuple(sorted(chapters, key=lambda item: item.global_physical_order)),
        tuple(canonical_order),
        tuple(findings),
        report,
    )


__all__ = [
    "CANONICAL_ORDER_SCHEMA_VERSION",
    "CHAPTER_CATALOG_REPORT_SCHEMA_VERSION",
    "CHAPTER_ENGINE_VERSION",
    "CHAPTER_FINDING_SCHEMA_VERSION",
    "CHAPTER_RECORD_SCHEMA_VERSION",
    "SOURCE_BINDING_SCHEMA_VERSION",
    "CanonicalChapter",
    "CanonicalOrderRecord",
    "ChapterCatalog",
    "ChapterCatalogReport",
    "ChapterEngineError",
    "ChapterFinding",
    "ChapterSourceInput",
    "SourceBinding",
    "build_chapter_catalog",
]
