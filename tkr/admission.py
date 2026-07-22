"""Phase 0 source identity admission without decoding source text."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from os import PathLike
from pathlib import Path
from typing import Final

from .hashing import DEFAULT_BLOCK_SIZE, HashingError, inspect_file

SOURCE_IDENTITY_SCHEMA_VERSION: Final = "tkr-source-identity-v1"
SUPPORTED_SOURCE_SUFFIXES: Final = frozenset({".txt", ".md"})


class AdmissionError(ValueError):
    """Raised when source identity inspection cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class SourceIdentityReport:
    """Raw-byte identity and admission metadata for one source file."""

    schema_version: str
    source_id: str
    path: str
    filename: str
    suffix: str
    suffix_supported: bool
    size_bytes: int
    sha256: str
    empty_file: bool
    contains_nul: bool
    newline_type: str
    line_count: int | None
    line_count_reliable: bool
    lf_count: int
    crlf_count: int
    cr_count: int
    admission_status: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class _RawTextShape:
    contains_nul: bool
    newline_type: str
    line_count: int | None
    line_count_reliable: bool
    lf_count: int
    crlf_count: int
    cr_count: int


def _classify_newlines(lf_count: int, crlf_count: int, cr_count: int) -> str:
    active = sum(value > 0 for value in (lf_count, crlf_count, cr_count))
    if active == 0:
        return "none"
    if active > 1:
        return "mixed"
    if lf_count:
        return "lf"
    if crlf_count:
        return "crlf"
    return "cr"


def _scan_raw_text_shape(path: Path, *, block_size: int) -> _RawTextShape:
    contains_nul = False
    lf_count = 0
    crlf_count = 0
    cr_count = 0
    pending_cr = False
    last_byte: int | None = None

    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if block == b"":
                break
            contains_nul = contains_nul or b"\x00" in block
            for byte in block:
                if pending_cr:
                    if byte == 0x0A:
                        crlf_count += 1
                        pending_cr = False
                        last_byte = byte
                        continue
                    cr_count += 1
                    pending_cr = False
                if byte == 0x0D:
                    pending_cr = True
                elif byte == 0x0A:
                    lf_count += 1
                last_byte = byte

    if pending_cr:
        cr_count += 1

    newline_type = _classify_newlines(lf_count, crlf_count, cr_count)
    if contains_nul:
        line_count = None
        line_count_reliable = False
    elif last_byte is None:
        line_count = 0
        line_count_reliable = True
    else:
        terminator_count = lf_count + crlf_count + cr_count
        line_count = terminator_count + (last_byte not in (0x0A, 0x0D))
        line_count_reliable = True

    return _RawTextShape(
        contains_nul=contains_nul,
        newline_type=newline_type,
        line_count=line_count,
        line_count_reliable=line_count_reliable,
        lf_count=lf_count,
        crlf_count=crlf_count,
        cr_count=cr_count,
    )


def inspect_source_identity(
    path: str | PathLike[str],
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> SourceIdentityReport:
    """Inspect one raw source without decoding or mutating it.

    The function accepts only regular files, hashes them with bounded memory, and
    records raw byte-level newline information. Files containing NUL bytes remain
    eligible for Phase 9.3 encoding review, but their line count is intentionally
    reported as unreliable because UTF-16 and binary data cannot be distinguished
    at this stage.
    """

    candidate = Path(path)
    try:
        digest = inspect_file(candidate, block_size=block_size)
    except HashingError as exc:
        raise AdmissionError(str(exc)) from exc

    suffix = candidate.suffix.lower()
    suffix_supported = suffix in SUPPORTED_SOURCE_SUFFIXES
    shape = _scan_raw_text_shape(candidate, block_size=digest.block_size)

    blockers: list[str] = []
    warnings: list[str] = []
    if not suffix_supported:
        blockers.append("UNSUPPORTED_SUFFIX")
    if digest.size_bytes == 0:
        warnings.append("EMPTY_FILE")
    if shape.contains_nul:
        warnings.append("NUL_BYTES_PRESENT")
    if shape.newline_type == "mixed":
        warnings.append("MIXED_NEWLINES")

    if blockers:
        admission_status = "unsupported"
    elif warnings:
        admission_status = "review"
    else:
        admission_status = "accepted_for_encoding_inspection"

    return SourceIdentityReport(
        schema_version=SOURCE_IDENTITY_SCHEMA_VERSION,
        source_id=f"source_sha256_{digest.sha256}",
        path=digest.path,
        filename=candidate.name,
        suffix=suffix,
        suffix_supported=suffix_supported,
        size_bytes=digest.size_bytes,
        sha256=digest.sha256,
        empty_file=digest.size_bytes == 0,
        contains_nul=shape.contains_nul,
        newline_type=shape.newline_type,
        line_count=shape.line_count,
        line_count_reliable=shape.line_count_reliable,
        lf_count=shape.lf_count,
        crlf_count=shape.crlf_count,
        cr_count=shape.cr_count,
        admission_status=admission_status,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )
