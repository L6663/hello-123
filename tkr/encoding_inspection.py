"""Phase 0 strict encoding selection and streaming Unicode inspection."""
from __future__ import annotations

import codecs
from dataclasses import asdict, dataclass
from os import PathLike
from pathlib import Path
from typing import Final
import unicodedata

from .admission import AdmissionError, inspect_source_identity
from .hashing import DEFAULT_BLOCK_SIZE

ENCODING_INSPECTION_SCHEMA_VERSION: Final = "tkr-encoding-inspection-v1"
_SAMPLE_SIZE: Final = 64 * 1024
_BOMS: Final = (
    (b"\x00\x00\xfe\xff", "utf-32-be", "unsupported"),
    (b"\xff\xfe\x00\x00", "utf-32-le", "unsupported"),
    (b"\xef\xbb\xbf", "utf-8", "supported"),
    (b"\xff\xfe", "utf-16-le", "supported"),
    (b"\xfe\xff", "utf-16-be", "supported"),
)


class EncodingInspectionError(ValueError):
    """Raised when encoding inspection cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class EncodingInspectionReport:
    """Strict decoding decision and Unicode-quality statistics."""

    schema_version: str
    source_id: str
    source_sha256: str
    size_bytes: int
    bom: str
    selected_encoding: str | None
    selection_basis: str
    confidence: str
    attempted_encodings: tuple[str, ...]
    strict_decode_passed: bool
    decode_error: str | None
    decoded_character_count: int | None
    replacement_character_count: int | None
    control_character_count: int | None
    noncharacter_count: int | None
    nul_character_count: int | None
    embedded_bom_count: int | None
    newline_type: str | None
    line_count: int | None
    lf_count: int | None
    crlf_count: int | None
    cr_count: int | None
    recommended_action: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _DecodedStats:
    character_count: int
    replacement_count: int
    control_count: int
    noncharacter_count: int
    nul_count: int
    embedded_bom_count: int
    newline_type: str
    line_count: int
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


def _is_noncharacter(codepoint: int) -> bool:
    return 0xFDD0 <= codepoint <= 0xFDEF or (codepoint & 0xFFFF) in {
        0xFFFE,
        0xFFFF,
    }


def _scan_decoded(
    path: Path,
    encoding: str,
    *,
    skip_prefix: int,
    block_size: int,
) -> tuple[_DecodedStats | None, str | None]:
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    character_count = replacement_count = control_count = 0
    noncharacter_count = nul_count = embedded_bom_count = 0
    lf_count = crlf_count = cr_count = 0
    pending_cr = False
    last_character: str | None = None

    def consume(text: str) -> None:
        nonlocal character_count, replacement_count, control_count
        nonlocal noncharacter_count, nul_count, embedded_bom_count
        nonlocal lf_count, crlf_count, cr_count, pending_cr, last_character
        for character in text:
            character_count += 1
            codepoint = ord(character)
            replacement_count += character == "\ufffd"
            nul_count += character == "\x00"
            embedded_bom_count += character == "\ufeff"
            noncharacter_count += _is_noncharacter(codepoint)
            control_count += (
                unicodedata.category(character) == "Cc"
                and character not in "\t\n\r\f"
            )
            if pending_cr:
                if character == "\n":
                    crlf_count += 1
                    pending_cr = False
                    last_character = character
                    continue
                cr_count += 1
                pending_cr = False
            if character == "\r":
                pending_cr = True
            elif character == "\n":
                lf_count += 1
            last_character = character

    try:
        with path.open("rb") as handle:
            if skip_prefix and len(handle.read(skip_prefix)) != skip_prefix:
                return None, "source ended inside the byte-order mark"
            while True:
                block = handle.read(block_size)
                if block == b"":
                    break
                consume(decoder.decode(block, final=False))
            consume(decoder.decode(b"", final=True))
    except UnicodeDecodeError as exc:
        return None, f"{encoding}: {exc.reason}"
    except LookupError as exc:
        return None, f"unsupported codec {encoding}: {exc}"

    if pending_cr:
        cr_count += 1
    terminators = lf_count + crlf_count + cr_count
    line_count = 0 if character_count == 0 else terminators + (
        last_character not in {"\n", "\r"}
    )
    return _DecodedStats(
        character_count,
        replacement_count,
        control_count,
        noncharacter_count,
        nul_count,
        embedded_bom_count,
        _classify_newlines(lf_count, crlf_count, cr_count),
        line_count,
        lf_count,
        crlf_count,
        cr_count,
    ), None


def _read_sample(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(_SAMPLE_SIZE)


def _bom_from_prefix(prefix: bytes) -> tuple[str, int, str]:
    for signature, name, support in _BOMS:
        if prefix.startswith(signature):
            return name, len(signature), support
    return "none", 0, "none"


def _bomless_utf16_order(sample: bytes) -> tuple[str, ...]:
    if len(sample) < 4 or len(sample) % 2:
        return ()
    pairs = max(1, len(sample) // 2)
    even_zero = sample[0::2].count(0) / pairs
    odd_zero = sample[1::2].count(0) / pairs
    le_newlines = sample.count(b"\n\x00") + sample.count(b"\r\x00")
    be_newlines = sample.count(b"\x00\n") + sample.count(b"\x00\r")
    le_signal = le_newlines > 0 or odd_zero >= 0.20
    be_signal = be_newlines > 0 or even_zero >= 0.20
    if not le_signal and not be_signal:
        return ()
    if (le_newlines, odd_zero) >= (be_newlines, even_zero):
        return ("utf-16-le", "utf-16-be") if be_signal else ("utf-16-le",)
    return ("utf-16-be", "utf-16-le") if le_signal else ("utf-16-be",)


def _warnings_for_stats(stats: _DecodedStats) -> list[str]:
    pairs = (
        (stats.replacement_count, "REPLACEMENT_CHARACTER_PRESENT"),
        (stats.control_count, "CONTROL_CHARACTERS_PRESENT"),
        (stats.noncharacter_count, "UNICODE_NONCHARACTERS_PRESENT"),
        (stats.nul_count, "NUL_CHARACTERS_PRESENT"),
        (stats.embedded_bom_count, "EMBEDDED_BOM_PRESENT"),
        (stats.newline_type == "mixed", "MIXED_NEWLINES"),
    )
    return [name for condition, name in pairs if condition]


def _report(
    *, identity, bom: str, selected_encoding: str | None,
    selection_basis: str, confidence: str, attempted_encodings: list[str],
    stats: _DecodedStats | None, decode_error: str | None,
    blockers: list[str], warnings: list[str],
) -> EncodingInspectionReport:
    action = "reject" if blockers else ("review" if warnings else "accept")
    return EncodingInspectionReport(
        ENCODING_INSPECTION_SCHEMA_VERSION,
        identity.source_id,
        identity.sha256,
        identity.size_bytes,
        bom,
        selected_encoding,
        selection_basis,
        confidence,
        tuple(attempted_encodings),
        stats is not None,
        decode_error,
        None if stats is None else stats.character_count,
        None if stats is None else stats.replacement_count,
        None if stats is None else stats.control_count,
        None if stats is None else stats.noncharacter_count,
        None if stats is None else stats.nul_count,
        None if stats is None else stats.embedded_bom_count,
        None if stats is None else stats.newline_type,
        None if stats is None else stats.line_count,
        None if stats is None else stats.lf_count,
        None if stats is None else stats.crlf_count,
        None if stats is None else stats.cr_count,
        action,
        tuple(blockers),
        tuple(dict.fromkeys(warnings)),
    )


def inspect_source_encoding(
    path: str | PathLike[str], *, block_size: int = DEFAULT_BLOCK_SIZE,
) -> EncodingInspectionReport:
    """Select a strict decoder and inspect Unicode incrementally.

    The result is a safe decoding decision, not proof of the file's historical
    authoring encoding. BOM-free UTF-16 and GB18030 remain review candidates.
    """
    try:
        identity = inspect_source_identity(path, block_size=block_size)
    except AdmissionError as exc:
        raise EncodingInspectionError(str(exc)) from exc
    candidate = Path(path)
    attempted: list[str] = []
    blockers = list(identity.blockers)
    warnings: list[str] = []

    if not identity.suffix_supported:
        return _report(
            identity=identity, bom="none", selected_encoding=None,
            selection_basis="unsupported_source", confidence="none",
            attempted_encodings=attempted, stats=None, decode_error=None,
            blockers=blockers, warnings=warnings,
        )

    sample = _read_sample(candidate)
    bom, skip_prefix, bom_support = _bom_from_prefix(sample[:4])
    if bom_support == "unsupported":
        blockers.append("UNSUPPORTED_BOM")
        return _report(
            identity=identity, bom=bom, selected_encoding=None,
            selection_basis="unsupported_bom", confidence="none",
            attempted_encodings=attempted, stats=None, decode_error=None,
            blockers=blockers, warnings=warnings,
        )
    if identity.empty_file:
        warnings.append("EMPTY_FILE")

    if bom_support == "supported":
        attempted.append(bom)
        stats, error = _scan_decoded(
            candidate, bom, skip_prefix=skip_prefix, block_size=block_size
        )
        if stats is None:
            blockers.append("STRICT_DECODE_FAILED")
        else:
            warnings.extend(_warnings_for_stats(stats))
        return _report(
            identity=identity, bom=bom,
            selected_encoding=bom if stats is not None else None,
            selection_basis="byte_order_mark",
            confidence="high" if stats is not None else "none",
            attempted_encodings=attempted, stats=stats, decode_error=error,
            blockers=blockers, warnings=warnings,
        )

    if identity.size_bytes % 2 == 0:
        for encoding in _bomless_utf16_order(sample):
            attempted.append(encoding)
            stats, _ = _scan_decoded(
                candidate, encoding, skip_prefix=0, block_size=block_size
            )
            if stats is None:
                continue
            warnings.append("BOMLESS_UTF16_CANDIDATE")
            warnings.extend(_warnings_for_stats(stats))
            return _report(
                identity=identity, bom="none", selected_encoding=encoding,
                selection_basis="utf16_byte_pattern", confidence="medium",
                attempted_encodings=attempted, stats=stats, decode_error=None,
                blockers=blockers, warnings=warnings,
            )

    attempted.append("utf-8")
    stats, utf8_error = _scan_decoded(
        candidate, "utf-8", skip_prefix=0, block_size=block_size
    )
    if stats is not None:
        warnings.extend(_warnings_for_stats(stats))
        return _report(
            identity=identity, bom="none", selected_encoding="utf-8",
            selection_basis="strict_utf8", confidence="high",
            attempted_encodings=attempted, stats=stats, decode_error=None,
            blockers=blockers, warnings=warnings,
        )

    attempted.append("gb18030")
    stats, gb_error = _scan_decoded(
        candidate, "gb18030", skip_prefix=0, block_size=block_size
    )
    if stats is not None:
        warnings.append("LEGACY_ENCODING_CANDIDATE")
        warnings.extend(_warnings_for_stats(stats))
        return _report(
            identity=identity, bom="none", selected_encoding="gb18030",
            selection_basis="gb18030_fallback", confidence="medium",
            attempted_encodings=attempted, stats=stats, decode_error=None,
            blockers=blockers, warnings=warnings,
        )

    blockers.append("NO_SUPPORTED_STRICT_DECODING")
    return _report(
        identity=identity, bom="none", selected_encoding=None,
        selection_basis="no_supported_decoder", confidence="none",
        attempted_encodings=attempted, stats=None,
        decode_error=gb_error or utf8_error,
        blockers=blockers, warnings=warnings,
    )
