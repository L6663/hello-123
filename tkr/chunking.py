"""Deterministic, auditable, size-bounded text chunking.

The implementation deliberately uses only the Python standard library.  Chunks
are contiguous slices of the normalized source text; no separator is inserted
and no character is silently dropped.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Iterable, Iterator, Sequence

CHUNK_SCHEMA_VERSION = "tkr-chunk-v2"
_MIN_BOUNDARY_RATIO = 0.55
_PARAGRAPH_RE = re.compile(r"\n[ \t]*\n+")
_SENTENCE_MARKS = frozenset("。！？!?；;")
_CLAUSE_MARKS = frozenset("，、：,:")
_BOUNDARY_PRIORITY = {
    "paragraph": 0,
    "sentence": 1,
    "clause": 2,
    "whitespace": 3,
}


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    max_chars: int = 1400
    overlap_chars: int = 180

    def __post_init__(self) -> None:
        validate_chunk_config(self.max_chars, self.overlap_chars)


@dataclass(frozen=True, slots=True)
class UnitSpan:
    unit_id: str
    start: int
    end: int
    source_id: str = "source"


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    source_id: str
    unit_id: str
    ordinal: int
    norm_start: int
    norm_end: int
    length: int
    overlap_with_previous: int
    start_boundary: str
    end_boundary: str
    text_sha256: str
    text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ChunkValidationError(ValueError):
    """Raised when generated or supplied chunks violate hard invariants."""


def validate_chunk_config(max_chars: int, overlap_chars: int) -> None:
    """Reject invalid parameters instead of silently correcting them."""

    if isinstance(max_chars, bool) or not isinstance(max_chars, int):
        raise TypeError("max_chars must be an integer")
    if isinstance(overlap_chars, bool) or not isinstance(overlap_chars, int):
        raise TypeError("overlap_chars must be an integer")
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than 0")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must not be negative")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")


def _validate_units(text: str, units: Sequence[UnitSpan]) -> list[UnitSpan]:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not units:
        raise ValueError("at least one unit is required")

    ordered = sorted(units, key=lambda unit: (unit.start, unit.end, unit.unit_id))
    seen_ids: set[tuple[str, str]] = set()
    previous_end = -1
    for unit in ordered:
        if not unit.unit_id or not unit.source_id:
            raise ValueError("unit_id and source_id must be non-empty")
        for value, name in ((unit.start, "start"), (unit.end, "end")):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"unit {name} must be an integer")
        if unit.start < 0 or unit.end > len(text) or unit.start >= unit.end:
            raise ValueError(f"invalid unit span: {unit.unit_id}")
        key = (unit.source_id, unit.unit_id)
        if key in seen_ids:
            raise ValueError(f"duplicate unit identifier: {key}")
        seen_ids.add(key)
        if unit.start < previous_end:
            raise ValueError("unit spans must not overlap")
        previous_end = unit.end
    return ordered


def _candidate_boundaries(text: str, lower_cut: int, upper_cut: int) -> dict[int, str]:
    """Return candidate cut offsets and their strongest boundary type.

    ``lower_cut`` and ``upper_cut`` are cut offsets, not character indexes.
    """

    if upper_cut < lower_cut:
        return {}

    candidates: dict[int, str] = {}

    def add(position: int, boundary_type: str) -> None:
        if not (lower_cut <= position <= upper_cut):
            return
        current = candidates.get(position)
        if current is None or _BOUNDARY_PRIORITY[boundary_type] < _BOUNDARY_PRIORITY[current]:
            candidates[position] = boundary_type

    scan_start = max(0, lower_cut - 2)
    for match in _PARAGRAPH_RE.finditer(text, scan_start, upper_cut):
        add(match.end(), "paragraph")

    char_start = max(0, lower_cut - 1)
    for index in range(char_start, upper_cut):
        cut = index + 1
        char = text[index]
        if char in _SENTENCE_MARKS:
            add(cut, "sentence")
        elif char in _CLAUSE_MARKS:
            add(cut, "clause")
        elif char.isspace():
            add(cut, "whitespace")

    return candidates


def _choose_end(
    text: str,
    *,
    start: int,
    hard_end: int,
    unit_end: int,
    max_chars: int,
    minimum_cut: int,
) -> tuple[int, str]:
    if hard_end >= unit_end:
        return unit_end, "unit_end"

    preferred = start + max(1, int(max_chars * _MIN_BOUNDARY_RATIO))
    lower = min(hard_end, max(start + 1, preferred, minimum_cut))
    candidates = _candidate_boundaries(text, lower, hard_end)

    for boundary_type in ("paragraph", "sentence", "clause", "whitespace"):
        positions = [position for position, kind in candidates.items() if kind == boundary_type]
        if positions:
            return max(positions), boundary_type

    return hard_end, "hard"


def _choose_next_start(
    text: str,
    *,
    desired_start: int,
    cut: int,
    overlap_chars: int,
) -> tuple[int, str]:
    if desired_start >= cut:
        return cut, "contiguous"

    # Search only a small distance forward.  This preserves most of the overlap
    # budget while avoiding an unnecessary dependency on a tokenizer.
    slack = min(64, max(1, overlap_chars // 3))
    upper = min(cut, desired_start + slack)
    candidates = _candidate_boundaries(text, desired_start, upper)
    if candidates:
        position = min(
            candidates,
            key=lambda item: (item - desired_start, _BOUNDARY_PRIORITY[candidates[item]]),
        )
        return position, candidates[position]
    return desired_start, "hard"


def _chunk_id(
    *,
    source_id: str,
    unit_id: str,
    start: int,
    end: int,
    text_sha256: str,
) -> str:
    payload = "\0".join(
        (
            CHUNK_SCHEMA_VERSION,
            source_id,
            unit_id,
            str(start),
            str(end),
            text_sha256,
        )
    )
    return "chk_" + sha256(payload.encode("utf-8")).hexdigest()[:24]


def iter_chunks(
    text: str,
    units: Sequence[UnitSpan],
    config: ChunkConfig | None = None,
) -> Iterator[Chunk]:
    """Yield deterministic chunks while preserving every supplied unit span."""

    active = config or ChunkConfig()
    ordered_units = _validate_units(text, units)

    for unit in ordered_units:
        start = unit.start
        ordinal = 1
        previous_end: int | None = None
        start_boundary = "unit_start"

        while start < unit.end:
            hard_end = min(start + active.max_chars, unit.end)
            minimum_cut = start + 1 if previous_end is None else previous_end + 1
            cut, end_boundary = _choose_end(
                text,
                start=start,
                hard_end=hard_end,
                unit_end=unit.end,
                max_chars=active.max_chars,
                minimum_cut=minimum_cut,
            )
            if cut <= start or cut > hard_end:
                raise ChunkValidationError("chunker failed to make bounded progress")

            chunk_text = text[start:cut]
            digest = sha256(chunk_text.encode("utf-8")).hexdigest()
            overlap = 0 if previous_end is None else previous_end - start
            yield Chunk(
                chunk_id=_chunk_id(
                    source_id=unit.source_id,
                    unit_id=unit.unit_id,
                    start=start,
                    end=cut,
                    text_sha256=digest,
                ),
                source_id=unit.source_id,
                unit_id=unit.unit_id,
                ordinal=ordinal,
                norm_start=start,
                norm_end=cut,
                length=cut - start,
                overlap_with_previous=overlap,
                start_boundary=start_boundary,
                end_boundary=end_boundary,
                text_sha256=digest,
                text=chunk_text,
            )

            if cut >= unit.end:
                break

            desired_start = cut - active.overlap_chars
            next_start, next_boundary = _choose_next_start(
                text,
                desired_start=desired_start,
                cut=cut,
                overlap_chars=active.overlap_chars,
            )
            next_start = max(start + 1, min(next_start, cut))
            if cut - next_start > active.overlap_chars:
                raise ChunkValidationError("computed overlap exceeds configured budget")

            previous_end = cut
            start = next_start
            start_boundary = next_boundary
            ordinal += 1


def validate_chunks(
    chunks: Sequence[Chunk],
    text: str,
    units: Sequence[UnitSpan],
    config: ChunkConfig | None = None,
) -> None:
    """Independently verify all hard chunking invariants."""

    active = config or ChunkConfig()
    ordered_units = _validate_units(text, units)
    by_unit: dict[tuple[str, str], list[Chunk]] = defaultdict(list)
    ids: set[str] = set()

    for chunk in chunks:
        if chunk.chunk_id in ids:
            raise ChunkValidationError(f"duplicate chunk_id: {chunk.chunk_id}")
        ids.add(chunk.chunk_id)
        if chunk.length <= 0 or chunk.length > active.max_chars:
            raise ChunkValidationError(f"invalid chunk length: {chunk.chunk_id}")
        if chunk.length != chunk.norm_end - chunk.norm_start:
            raise ChunkValidationError(f"length/span mismatch: {chunk.chunk_id}")
        if chunk.norm_start < 0 or chunk.norm_end > len(text):
            raise ChunkValidationError(f"chunk outside normalized text: {chunk.chunk_id}")
        expected_text = text[chunk.norm_start : chunk.norm_end]
        if chunk.text != expected_text:
            raise ChunkValidationError(f"text/span mismatch: {chunk.chunk_id}")
        expected_digest = sha256(chunk.text.encode("utf-8")).hexdigest()
        if chunk.text_sha256 != expected_digest:
            raise ChunkValidationError(f"text hash mismatch: {chunk.chunk_id}")
        expected_id = _chunk_id(
            source_id=chunk.source_id,
            unit_id=chunk.unit_id,
            start=chunk.norm_start,
            end=chunk.norm_end,
            text_sha256=chunk.text_sha256,
        )
        if chunk.chunk_id != expected_id:
            raise ChunkValidationError(f"unstable chunk id: {chunk.chunk_id}")
        by_unit[(chunk.source_id, chunk.unit_id)].append(chunk)

    expected_keys = {(unit.source_id, unit.unit_id) for unit in ordered_units}
    if set(by_unit) != expected_keys:
        raise ChunkValidationError("chunks do not cover exactly the supplied units")

    for unit in ordered_units:
        key = (unit.source_id, unit.unit_id)
        unit_chunks = sorted(by_unit[key], key=lambda chunk: chunk.ordinal)
        if unit_chunks[0].norm_start != unit.start:
            raise ChunkValidationError(f"unit does not start at its first chunk: {unit.unit_id}")
        if unit_chunks[-1].norm_end != unit.end:
            raise ChunkValidationError(f"unit does not end at its final chunk: {unit.unit_id}")

        previous: Chunk | None = None
        for expected_ordinal, chunk in enumerate(unit_chunks, start=1):
            if chunk.ordinal != expected_ordinal:
                raise ChunkValidationError(f"non-contiguous ordinals in unit: {unit.unit_id}")
            if not (unit.start <= chunk.norm_start < chunk.norm_end <= unit.end):
                raise ChunkValidationError(f"chunk crosses unit boundary: {chunk.chunk_id}")
            if previous is None:
                if chunk.overlap_with_previous != 0:
                    raise ChunkValidationError("first chunk must report zero overlap")
            else:
                if chunk.norm_start > previous.norm_end:
                    raise ChunkValidationError(f"gap before chunk: {chunk.chunk_id}")
                if chunk.norm_start <= previous.norm_start:
                    raise ChunkValidationError(f"non-progressing chunk start: {chunk.chunk_id}")
                if chunk.norm_end <= previous.norm_end:
                    raise ChunkValidationError(f"chunk adds no new text: {chunk.chunk_id}")
                overlap = previous.norm_end - chunk.norm_start
                if overlap < 0 or overlap > active.overlap_chars:
                    raise ChunkValidationError(f"invalid overlap: {chunk.chunk_id}")
                if chunk.overlap_with_previous != overlap:
                    raise ChunkValidationError(f"reported overlap mismatch: {chunk.chunk_id}")
            previous = chunk


def chunk_units(
    text: str,
    units: Sequence[UnitSpan],
    config: ChunkConfig | None = None,
) -> tuple[list[Chunk], dict[str, object]]:
    """Generate, independently validate, and summarize chunks."""

    active = config or ChunkConfig()
    chunks = list(iter_chunks(text, units, active))
    validate_chunks(chunks, text, units, active)
    boundary_counts = Counter(chunk.end_boundary for chunk in chunks)
    report: dict[str, object] = {
        "schema_version": CHUNK_SCHEMA_VERSION,
        "status": "accepted",
        "max_chars": active.max_chars,
        "overlap_chars": active.overlap_chars,
        "unit_count": len(units),
        "chunk_count": len(chunks),
        "max_observed_length": max(chunk.length for chunk in chunks),
        "max_observed_overlap": max(chunk.overlap_with_previous for chunk in chunks),
        "coverage_ok": True,
        "hard_split_count": boundary_counts.get("hard", 0),
        "end_boundary_counts": dict(sorted(boundary_counts.items())),
    }
    return chunks, report


def write_chunk_artifacts(
    chunks: Iterable[Chunk],
    report: dict[str, object],
    outdir: str | Path,
) -> tuple[Path, Path]:
    """Write compact JSONL chunks plus one shared report."""

    directory = Path(outdir)
    directory.mkdir(parents=True, exist_ok=True)
    chunks_path = directory / "chunks.jsonl"
    report_path = directory / "chunking-report.json"
    with chunks_path.open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return chunks_path, report_path
