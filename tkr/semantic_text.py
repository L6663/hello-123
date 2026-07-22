"""Decoded Unit iteration and discourse segmentation helpers for Stage 3."""
from __future__ import annotations

from hashlib import sha256
import io
from pathlib import Path
import re
from typing import Iterator

from .semantic_models import SemanticExtractionError
from .structure_models import UnitRecord

_CLAUSE_RE = re.compile(r"[^。！？!?；;\r\n]+(?:[。！？!?；;]+|$)")
_RUMOR_RE = re.compile(r"^\s*(?:据说|传闻|听说|相传|坊间传言|消息称)[，,：:\s]*")
_ATTRIBUTED = (
    ("belief", re.compile(r"^\s*(?P<who>[A-Za-z0-9_\-\u3400-\u9fff·]{1,24})(?:认为|相信|认定|觉得)[，,：:\s]*")),
    ("suspicion", re.compile(r"^\s*(?P<who>[A-Za-z0-9_\-\u3400-\u9fff·]{1,24})(?:怀疑|猜测|推测)[，,：:\s]*")),
    ("accusation", re.compile(r"^\s*(?P<who>[A-Za-z0-9_\-\u3400-\u9fff·]{1,24})(?:指控|控告|谴责)[，,：:\s]*")),
)
_HYPOTHETICAL_RE = re.compile(r"(?:^|[，,：:\s])(?:如果|假如|倘若|若是|若)[，,：:\s]*")
_FUTURE_RE = re.compile(r"(?:计划|准备|将要|即将|拟于|预计)")


def open_decoded(path: Path, report):
    raw = path.open("rb")
    first = raw.read(4)
    raw.seek(0)
    for signature in (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"):
        if first.startswith(signature):
            raw.read(len(signature))
            break
    return io.TextIOWrapper(raw, encoding=report.selected_encoding, errors="strict", newline="")


def _read_exact(handle, count: int) -> str:
    chunks: list[str] = []
    remaining = count
    while remaining:
        block = handle.read(min(64 * 1024, remaining))
        if block == "":
            raise SemanticExtractionError("decoded source ended before the Unit Index")
        chunks.append(block)
        remaining -= len(block)
    return "".join(chunks)


def iter_unit_texts(path: Path, report) -> Iterator[tuple[UnitRecord, str]]:
    with open_decoded(path, report) as handle:
        for unit in report.units:
            text = _read_exact(handle, unit.character_count)
            if sha256(text.encode("utf-8")).hexdigest() != unit.content_sha256:
                raise SemanticExtractionError(f"Unit content hash mismatch: {unit.unit_id}")
            yield unit, text
        if handle.read(1) != "":
            raise SemanticExtractionError("decoded source exceeds the Unit Index")


def line_number(unit: UnitRecord, text: str, local_offset: int) -> int:
    prefix = text[:local_offset]
    crlf = prefix.count("\r\n")
    return unit.start_line + crlf + prefix.count("\n") - crlf + prefix.count("\r") - crlf


def iter_clauses(text: str, body_start_local: int) -> Iterator[tuple[int, int, str]]:
    body = text[body_start_local:]
    for match in _CLAUSE_RE.finditer(body):
        if match.group(0).strip():
            yield body_start_local + match.start(), body_start_local + match.end(), match.group(0)


def classify_discourse(clause: str) -> tuple[str, str, int]:
    match = _RUMOR_RE.match(clause)
    if match:
        return "rumor", "", match.end()
    for status, pattern in _ATTRIBUTED:
        match = pattern.match(clause)
        if match:
            return status, match.group("who"), match.end()
    if "？" in clause or "?" in clause:
        return "question", "", 0
    match = _HYPOTHETICAL_RE.search(clause)
    if match:
        return "hypothetical", "", match.end()
    if _FUTURE_RE.search(clause):
        return "future_intent", "", 0
    return "assertion", "", 0
