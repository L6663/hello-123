"""Deterministic, auditable, size-bounded text chunking.

The implementation deliberately uses only the Python standard library. Chunks
are contiguous slices of normalized source text: no separator is inserted and
no character is silently dropped. Batch APIs remain available for small inputs;
the CLI uses an atomic streaming writer so chunk objects do not accumulate in
memory for large corpora.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Iterable, Iterator, Mapping, Sequence

CHUNK_SCHEMA_VERSION = "tkr-chunk-v2"
_MIN_BOUNDARY_RATIO = 0.55
_PARAGRAPH_RE = re.compile(r"\n[ \t]*\n+")
_SENTENCE_MARKS = frozenset("。！？!?；;…")
_CLAUSE_MARKS = frozenset("，、：,:")
_CLOSING_MARKS = frozenset(("”", "’", "』", "」", "】", "》", "〉", '"', "'", ")", "]", "}", "）"))
_BOUNDARY_PRIORITY = {
    "paragraph": 0,
    "sentence": 1,
    "clause": 2,
    "whitespace": 3,
}
_ALLOWED_START_BOUNDARIES = frozenset(
    {"unit_start", "contiguous", "paragraph", "sentence", "clause", "whitespace", "hard"}
)
_ALLOWED_END_BOUNDARIES = frozenset(
    {"unit_end", "paragraph", "sentence", "clause", "whitespace", "hard"}
)


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "Chunk":
        def require_str(name: str) -> str:
            value = payload.get(name)
            if not isinstance(value, str):
                raise ChunkValidationError(f"chunk field {name!r} must be a string")
            return value

        def require_int(name: str) -> int:
            value = payload.get(name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ChunkValidationError(f"chunk field {name!r} must be an integer")
            return value

        return cls(
            chunk_id=require_str("chunk_id"),
            source_id=require_str("source_id"),
            unit_id=require_str("unit_id"),
            ordinal=require_int("ordinal"),
            norm_start=require_int("norm_start"),
            norm_end=require_int("norm_end"),
            length=require_int("length"),
            overlap_with_previous=require_int("overlap_with_previous"),
            start_boundary=require_str("start_boundary"),
            end_boundary=require_str("end_boundary"),
            text_sha256=require_str("text_sha256"),
            text=require_str("text"),
        )


class ChunkValidationError(ValueError):
    """Raised when generated or supplied chunks violate hard invariants."""


@dataclass(slots=True)
class _ChunkStats:
    chunk_count: int = 0
    max_length: int = 0
    max_overlap: int = 0
    total_overlap: int = 0
    covered_new_characters: int = 0
    boundary_counts: Counter[str] | None = None

    def __post_init__(self) -> None:
        if self.boundary_counts is None:
            self.boundary_counts = Counter()

    def add(self, chunk: Chunk) -> None:
        self.chunk_count += 1
        self.max_length = max(self.max_length, chunk.length)
        self.max_overlap = max(self.max_overlap, chunk.overlap_with_previous)
        self.total_overlap += chunk.overlap_with_previous
        self.covered_new_characters += chunk.length - chunk.overlap_with_previous
        assert self.boundary_counts is not None
        self.boundary_counts[chunk.end_boundary] += 1


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


def _advance_over_closers(text: str, position: int, upper_cut: int) -> int:
    while position < upper_cut and text[position] in _CLOSING_MARKS:
        position += 1
    return position


def _is_sentence_ending_dot(text: str, index: int) -> bool:
    """Treat a period as sentence punctuation without splitting decimal numbers."""

    if text[index] != ".":
        return False
    previous = text[index - 1] if index > 0 else ""
    following = text[index + 1] if index + 1 < len(text) else ""
    if previous.isdigit() and following.isdigit():
        return False
    return not following or following.isspace() or following in _CLOSING_MARKS


def _is_sentence_mark(text: str, index: int) -> bool:
    char = text[index]
    if char == ".":
        return _is_sentence_ending_dot(text, index)
    if char == "…" and index + 1 < len(text) and text[index + 1] == "…":
        return False
    return char in _SENTENCE_MARKS


def _candidate_boundaries(text: str, lower_cut: int, upper_cut: int) -> dict[int, str]:
    """Return candidate cut offsets and their strongest boundary type.

    ``lower_cut`` and ``upper_cut`` are cut offsets, not character indexes.
    Sentence cuts absorb immediately following closing quotes/brackets when they
    still fit inside the hard budget, preventing orphan closing punctuation at
    the beginning of the next chunk.
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
        if _is_sentence_mark(text, index):
            add(_advance_over_closers(text, cut, upper_cut), "sentence")
        elif char in _CLAUSE_MARKS:
            add(_advance_over_closers(text, cut, upper_cut), "clause")
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
        (CHUNK_SCHEMA_VERSION, source_id, unit_id, str(start), str(end), text_sha256)
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


def _validate_chunk_record(chunk: Chunk, text: str, config: ChunkConfig) -> None:
    if not chunk.chunk_id or not chunk.source_id or not chunk.unit_id:
        raise ChunkValidationError("chunk identifiers must be non-empty")
    if chunk.start_boundary not in _ALLOWED_START_BOUNDARIES:
        raise ChunkValidationError(f"invalid start boundary: {chunk.chunk_id}")
    if chunk.end_boundary not in _ALLOWED_END_BOUNDARIES:
        raise ChunkValidationError(f"invalid end boundary: {chunk.chunk_id}")
    if chunk.length <= 0 or chunk.length > config.max_chars:
        raise ChunkValidationError(f"invalid chunk length: {chunk.chunk_id}")
    if chunk.length != chunk.norm_end - chunk.norm_start:
        raise ChunkValidationError(f"length/span mismatch: {chunk.chunk_id}")
    if chunk.norm_start < 0 or chunk.norm_end > len(text):
        raise ChunkValidationError(f"chunk outside normalized text: {chunk.chunk_id}")
    if chunk.text != text[chunk.norm_start : chunk.norm_end]:
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


def _validate_chunk_transition(
    previous: Chunk | None,
    chunk: Chunk,
    unit: UnitSpan,
    expected_ordinal: int,
    config: ChunkConfig,
) -> None:
    if chunk.ordinal != expected_ordinal:
        raise ChunkValidationError(f"non-contiguous ordinals in unit: {unit.unit_id}")
    if (chunk.source_id, chunk.unit_id) != (unit.source_id, unit.unit_id):
        raise ChunkValidationError(f"chunk assigned to unexpected unit: {chunk.chunk_id}")
    if not (unit.start <= chunk.norm_start < chunk.norm_end <= unit.end):
        raise ChunkValidationError(f"chunk crosses unit boundary: {chunk.chunk_id}")
    if previous is None:
        if chunk.norm_start != unit.start:
            raise ChunkValidationError(f"unit does not start at its first chunk: {unit.unit_id}")
        if chunk.overlap_with_previous != 0:
            raise ChunkValidationError("first chunk must report zero overlap")
        return
    if chunk.norm_start > previous.norm_end:
        raise ChunkValidationError(f"gap before chunk: {chunk.chunk_id}")
    if chunk.norm_start <= previous.norm_start:
        raise ChunkValidationError(f"non-progressing chunk start: {chunk.chunk_id}")
    if chunk.norm_end <= previous.norm_end:
        raise ChunkValidationError(f"chunk adds no new text: {chunk.chunk_id}")
    overlap = previous.norm_end - chunk.norm_start
    if overlap < 0 or overlap > config.overlap_chars:
        raise ChunkValidationError(f"invalid overlap: {chunk.chunk_id}")
    if chunk.overlap_with_previous != overlap:
        raise ChunkValidationError(f"reported overlap mismatch: {chunk.chunk_id}")


def validate_chunks(
    chunks: Sequence[Chunk],
    text: str,
    units: Sequence[UnitSpan],
    config: ChunkConfig | None = None,
) -> None:
    """Independently verify all hard invariants for an in-memory chunk set."""

    active = config or ChunkConfig()
    ordered_units = _validate_units(text, units)
    by_unit: dict[tuple[str, str], list[Chunk]] = defaultdict(list)
    ids: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in ids:
            raise ChunkValidationError(f"duplicate chunk_id: {chunk.chunk_id}")
        ids.add(chunk.chunk_id)
        _validate_chunk_record(chunk, text, active)
        by_unit[(chunk.source_id, chunk.unit_id)].append(chunk)

    expected_keys = {(unit.source_id, unit.unit_id) for unit in ordered_units}
    if set(by_unit) != expected_keys:
        raise ChunkValidationError("chunks do not cover exactly the supplied units")
    for unit in ordered_units:
        unit_chunks = sorted(by_unit[(unit.source_id, unit.unit_id)], key=lambda item: item.ordinal)
        previous: Chunk | None = None
        for expected_ordinal, chunk in enumerate(unit_chunks, start=1):
            _validate_chunk_transition(previous, chunk, unit, expected_ordinal, active)
            previous = chunk
        assert previous is not None
        if previous.norm_end != unit.end:
            raise ChunkValidationError(f"unit does not end at its final chunk: {unit.unit_id}")


def validate_chunk_file(
    chunks_path: str | Path,
    text: str,
    units: Sequence[UnitSpan],
    config: ChunkConfig | None = None,
) -> dict[str, object]:
    """Validate a JSONL chunk artifact in one pass without loading all chunks."""

    active = config or ChunkConfig()
    ordered_units = _validate_units(text, units)
    unit_index = 0
    previous: Chunk | None = None
    expected_ordinal = 1
    stats = _ChunkStats()
    with Path(chunks_path).open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                raise ChunkValidationError(f"blank JSONL record at line {line_number}")
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ChunkValidationError(f"invalid JSON at line {line_number}: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ChunkValidationError(f"chunk record at line {line_number} must be an object")
            chunk = Chunk.from_dict(payload)
            _validate_chunk_record(chunk, text, active)

            if unit_index >= len(ordered_units):
                raise ChunkValidationError("chunk file contains unexpected extra units")
            unit = ordered_units[unit_index]
            chunk_key = (chunk.source_id, chunk.unit_id)
            unit_key = (unit.source_id, unit.unit_id)
            if chunk_key != unit_key:
                if previous is None or previous.norm_end != unit.end:
                    raise ChunkValidationError(f"unit ended before complete coverage: {unit.unit_id}")
                unit_index += 1
                if unit_index >= len(ordered_units):
                    raise ChunkValidationError("chunk file contains unexpected extra units")
                unit = ordered_units[unit_index]
                if chunk_key != (unit.source_id, unit.unit_id):
                    raise ChunkValidationError(f"unexpected unit order at line {line_number}")
                previous = None
                expected_ordinal = 1

            _validate_chunk_transition(previous, chunk, unit, expected_ordinal, active)
            previous = chunk
            expected_ordinal += 1
            stats.add(chunk)

    if stats.chunk_count == 0 or previous is None:
        raise ChunkValidationError("chunk file is empty")
    if unit_index != len(ordered_units) - 1:
        raise ChunkValidationError("chunk file does not include every supplied unit")
    if previous.norm_end != ordered_units[-1].end:
        raise ChunkValidationError("final unit is not fully covered")
    expected_characters = sum(unit.end - unit.start for unit in ordered_units)
    if stats.covered_new_characters != expected_characters:
        raise ChunkValidationError("unique coverage does not equal supplied unit spans")
    return _build_report(text, ordered_units, active, stats)


def _build_report(
    text: str,
    units: Sequence[UnitSpan],
    config: ChunkConfig,
    stats: _ChunkStats,
) -> dict[str, object]:
    boundary_counts = stats.boundary_counts or Counter()
    unit_characters = sum(unit.end - unit.start for unit in units)
    return {
        "schema_version": CHUNK_SCHEMA_VERSION,
        "status": "accepted",
        "normalized_text_sha256": sha256(text.encode("utf-8")).hexdigest(),
        "input_characters": len(text),
        "source_ids": sorted({unit.source_id for unit in units}),
        "max_chars": config.max_chars,
        "overlap_chars": config.overlap_chars,
        "unit_count": len(units),
        "unit_characters": unit_characters,
        "chunk_count": stats.chunk_count,
        "max_observed_length": stats.max_length,
        "max_observed_overlap": stats.max_overlap,
        "total_overlap_characters": stats.total_overlap,
        "covered_new_characters": stats.covered_new_characters,
        "coverage_ok": stats.covered_new_characters == unit_characters,
        "hard_split_count": boundary_counts.get("hard", 0),
        "end_boundary_counts": dict(sorted(boundary_counts.items())),
    }


def chunk_units(
    text: str,
    units: Sequence[UnitSpan],
    config: ChunkConfig | None = None,
) -> tuple[list[Chunk], dict[str, object]]:
    """Generate, independently validate, and summarize chunks in memory."""

    active = config or ChunkConfig()
    ordered_units = _validate_units(text, units)
    chunks = list(iter_chunks(text, ordered_units, active))
    validate_chunks(chunks, text, ordered_units, active)
    stats = _ChunkStats()
    for chunk in chunks:
        stats.add(chunk)
    return chunks, _build_report(text, ordered_units, active, stats)


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


def stream_chunk_artifacts(
    text: str,
    units: Sequence[UnitSpan],
    config: ChunkConfig | None,
    outdir: str | Path,
) -> tuple[Path, Path, dict[str, object]]:
    """Generate, validate, and atomically publish artifacts in streaming mode."""

    active = config or ChunkConfig()
    ordered_units = _validate_units(text, units)
    directory = Path(outdir)
    directory.mkdir(parents=True, exist_ok=True)
    chunks_path = directory / "chunks.jsonl"
    report_path = directory / "chunking-report.json"
    chunks_tmp = directory / ".chunks.jsonl.tmp"
    report_tmp = directory / ".chunking-report.json.tmp"
    try:
        with chunks_tmp.open("w", encoding="utf-8", newline="\n") as handle:
            for chunk in iter_chunks(text, ordered_units, active):
                handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        report = validate_chunk_file(chunks_tmp, text, ordered_units, active)
        report_tmp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        chunks_tmp.replace(chunks_path)
        report_tmp.replace(report_path)
    except Exception:
        chunks_tmp.unlink(missing_ok=True)
        report_tmp.unlink(missing_ok=True)
        raise
    return chunks_path, report_path, report
