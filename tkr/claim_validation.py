"""Typed, deterministic Claim validation against exact local evidence spans.

A Claim is accepted only when a type-specific validator recovers the same
relation, direction, polarity, and exact value from the cited evidence. Lexical
similarity, embeddings, incoming verification flags, and model confidence are
not acceptance signals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Mapping, Sequence
import unicodedata

from .chunking import UnitSpan

VALIDATOR_VERSION = "tkr-claim-validator-v1"
SUPPORTED_CLAIM_TYPES = frozenset(
    {"alias", "defeats", "located_in", "permission", "count", "date"}
)

_STATUS_ACCEPTED = "accepted"
_STATUS_REJECTED = "rejected"
_STATUS_REVIEW = "review"

# Directional validators do not cross these clause boundaries. This is
# intentionally conservative: false negatives can be reviewed, while a false
# positive can contaminate the canonical knowledge base.
_RELATION_GAP = r"[^\n。！？!?；;，,:：]{0,24}?"
_CLAUSE_BREAK_RE = re.compile(r"[\n。！？!?；;]+")
_NEGATION_RE = re.compile(
    r"(?:并非|并未|不是|不曾|从未|不得|不能|不可以|不允许|禁止|"
    r"未曾|未能|没有|无权|未|"
    r"\bnot\b|\bnever\b|\bno\b|\bcannot\b|\bcan't\b|"
    r"\bmay not\b|\bmust not\b)",
    re.IGNORECASE,
)
_MODALITY_RE = re.compile(
    r"(?:据说|传闻|听说|或许|可能|似乎|也许|假如|如果|倘若|若是|"
    r"声称|宣称|谎称|自称|预计|计划|准备|将要|即将|"
    r"\breportedly\b|\ballegedly\b|\bperhaps\b|\bmaybe\b|"
    r"\bif\b|\bclaimed\b|\bclaims\b|\bwill\b|\bwould\b)",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(r"[？?]")

_ALIAS_MARKERS = (
    "改称",
    "更名为",
    "更名",
    "又称",
    "亦称",
    "也称",
    "别名为",
    "别名是",
    "别称",
    "原名",
    "旧称",
    "被称为",
    "renamed to",
    "formerly known as",
    "also known as",
    "aka",
)
_DEFEAT_MARKERS = ("击败", "战胜", "打败", "击溃", "defeated", "beat")
_LOCATION_MARKERS = ("位于", "坐落于", "地处", "设于", "located in", "situated in")
_POSITIVE_PERMISSION_MARKERS = (
    "可以",
    "能够",
    "允许",
    "准许",
    "获准",
    "有权",
    "可",
    "is allowed to",
    "may",
    "can",
)
_NEGATIVE_PERMISSION_MARKERS = (
    "不可以",
    "不可",
    "不能",
    "不允许",
    "禁止",
    "不得",
    "无权",
    "is not allowed to",
    "may not",
    "cannot",
    "can't",
    "must not",
)
_COUNT_CUES = (
    "共有",
    "共计",
    "总计",
    "合计",
    "数量为",
    "数目为",
    "一共",
    "共",
    "total",
    "count",
    "has",
    "contains",
)
_DATE_CUES = (
    "出生于",
    "发生于",
    "始于",
    "截至",
    "日期",
    "时间",
    "date",
    "on",
    "since",
)

_ARABIC_NUMBER_RE = re.compile(r"(?<![\d.])[-+]?\d+(?:\.\d+)?(?![\d.])")
_CHINESE_NUMBER_RE = re.compile(r"[零〇一二两三四五六七八九十百千万亿]+")
_DATE_TOKEN_RE = re.compile(
    r"(?P<y>\d{4})(?:年|[-/.])(?P<m>\d{1,2})(?:(?:月|[-/.])(?P<d>\d{1,2})日?)?"
)

_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_CHINESE_LARGE_UNITS = {"万": 10_000, "亿": 100_000_000}


class ClaimValidationError(ValueError):
    """Raised for malformed candidate objects, not semantic rejection."""


@dataclass(frozen=True, slots=True)
class ClaimCandidate:
    claim_type: str
    subject: str
    object: str = ""
    value: str | int | float | None = None
    unit: str = ""
    polarity: bool = True
    source_id: str = "source"
    unit_id: str = "unit-1"
    evidence_start: int = 0
    evidence_end: int = 0
    evidence_text: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ClaimCandidate":
        claim_type = _require_text(payload, "claim_type").lower()
        subject = _optional_text(payload.get("subject"))
        object_value = _optional_text(payload.get("object"))
        unit = _optional_text(payload.get("unit"))
        source_id = _optional_text(payload.get("source_id")) or "source"
        unit_id = _optional_text(payload.get("unit_id")) or "unit-1"
        polarity = payload.get("polarity", True)
        if not isinstance(polarity, bool):
            raise ClaimValidationError("polarity must be a boolean")
        evidence_start = _require_int(payload, "evidence_start")
        evidence_end = _require_int(payload, "evidence_end")
        evidence_text = payload.get("evidence_text")
        if evidence_text is not None and not isinstance(evidence_text, str):
            raise ClaimValidationError("evidence_text must be a string or null")
        value = payload.get("value")
        if isinstance(value, bool):
            raise ClaimValidationError("value must not be a boolean")
        if value is not None and not isinstance(value, (str, int, float)):
            raise ClaimValidationError("value must be a string, integer, float, or null")
        return cls(
            claim_type=claim_type,
            subject=subject,
            object=object_value,
            value=value,
            unit=unit,
            polarity=polarity,
            source_id=source_id,
            unit_id=unit_id,
            evidence_start=evidence_start,
            evidence_end=evidence_end,
            evidence_text=evidence_text,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ClaimValidationResult:
    result_id: str
    claim_fingerprint: str
    validator_version: str
    status: str
    reason_codes: tuple[str, ...]
    may_index: bool
    may_freeze: bool
    source_id: str
    unit_id: str
    evidence_start: int
    evidence_end: int
    evidence_sha256: str
    matched_spans: tuple[tuple[int, int], ...]
    normalized_claim: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        payload["matched_spans"] = [list(item) for item in self.matched_spans]
        return payload


def _require_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ClaimValidationError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ClaimValidationError("text fields must be strings")
    return value.strip()


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClaimValidationError(f"{key} must be an integer")
    return value


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _literal_pattern(value: str) -> str:
    pieces = re.split(r"\s+", _normalized_text(value))
    return r"\s*".join(re.escape(piece) for piece in pieces if piece)


def _marker_pattern(markers: Sequence[str]) -> str:
    patterns: list[str] = []
    for marker in markers:
        stripped = marker.strip()
        escaped = re.escape(stripped).replace(r"\ ", r"\s+")
        if re.fullmatch(r"[A-Za-z ]+", stripped):
            patterns.append(r"\b" + escaped + r"\b")
        else:
            patterns.append(escaped)
    return "(?:" + "|".join(patterns) + ")"


def _relation_regex(subject: str, object_value: str, markers: Sequence[str]) -> re.Pattern[str]:
    return re.compile(
        rf"(?P<subject>{_literal_pattern(subject)}){_RELATION_GAP}"
        rf"(?P<marker>{_marker_pattern(markers)}){_RELATION_GAP}"
        rf"(?P<object>{_literal_pattern(object_value)})",
        re.IGNORECASE,
    )


def _clean_matches(pattern: re.Pattern[str], evidence: str) -> list[re.Match[str]]:
    return [match for match in pattern.finditer(evidence) if not _NEGATION_RE.search(match.group(0))]


def _negated_matches(pattern: re.Pattern[str], evidence: str) -> list[re.Match[str]]:
    return [match for match in pattern.finditer(evidence) if _NEGATION_RE.search(match.group(0))]


def _context_is_modal(evidence: str, start: int, end: int) -> bool:
    context = evidence[max(0, start - 24) : min(len(evidence), end + 8)]
    return bool(_MODALITY_RE.search(context) or _QUESTION_RE.search(context))


def _partition_modal(
    matches: Sequence[re.Match[str]], evidence: str
) -> tuple[list[re.Match[str]], list[re.Match[str]]]:
    assertive: list[re.Match[str]] = []
    modal: list[re.Match[str]] = []
    for match in matches:
        (modal if _context_is_modal(evidence, match.start(), match.end()) else assertive).append(match)
    return assertive, modal


def _positive_permission_matches(pattern: re.Pattern[str], evidence: str) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    for match in pattern.finditer(evidence):
        # A subject-less match can start at “可以” inside “不可以”. Include a
        # short left context so the negation cannot be dropped by the regex.
        context = evidence[max(0, match.start() - 6) : match.end()]
        if not _NEGATION_RE.search(context):
            matches.append(match)
    return matches


def _split_clauses(evidence: str) -> list[tuple[int, str]]:
    clauses: list[tuple[int, str]] = []
    start = 0
    for match in _CLAUSE_BREAK_RE.finditer(evidence):
        if match.start() > start:
            clauses.append((start, evidence[start : match.start()]))
        start = match.end()
    if start < len(evidence):
        clauses.append((start, evidence[start:]))
    return clauses


def _contains_marker(text: str, markers: Sequence[str]) -> bool:
    normalized = _normalized_text(text).casefold()
    return any(_normalized_text(marker).casefold() in normalized for marker in markers)


def _span(match: re.Match[str]) -> tuple[int, int]:
    return (match.start(), match.end())


def _chinese_integer(token: str) -> int | None:
    if not token or any(
        char not in _CHINESE_DIGITS
        and char not in _CHINESE_SMALL_UNITS
        and char not in _CHINESE_LARGE_UNITS
        for char in token
    ):
        return None
    if all(char in _CHINESE_DIGITS for char in token):
        return int("".join(str(_CHINESE_DIGITS[char]) for char in token))

    total = 0
    section = 0
    number = 0
    for char in token:
        if char in _CHINESE_DIGITS:
            number = _CHINESE_DIGITS[char]
        elif char in _CHINESE_SMALL_UNITS:
            section += (number or 1) * _CHINESE_SMALL_UNITS[char]
            number = 0
        else:
            section += number
            number = 0
            total += (section or 1) * _CHINESE_LARGE_UNITS[char]
            section = 0
    return total + section + number


def _decimal_value(value: str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    token = _normalized_text(str(value))
    chinese = _chinese_integer(token)
    if chinese is not None:
        return Decimal(chinese)
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def _extract_numbers(text: str) -> list[tuple[Decimal, int, int]]:
    values: list[tuple[Decimal, int, int]] = []
    occupied: list[tuple[int, int]] = []
    for match in _ARABIC_NUMBER_RE.finditer(text):
        try:
            number = Decimal(match.group(0))
        except InvalidOperation:
            continue
        values.append((number, match.start(), match.end()))
        occupied.append((match.start(), match.end()))
    for match in _CHINESE_NUMBER_RE.finditer(text):
        if any(start < match.end() and match.start() < end for start, end in occupied):
            continue
        number = _chinese_integer(match.group(0))
        if number is not None:
            values.append((Decimal(number), match.start(), match.end()))
    return sorted(values, key=lambda item: (item[1], item[2]))


def _normalize_date(value: object) -> str | None:
    if value is None:
        return None
    match = _DATE_TOKEN_RE.fullmatch(_normalized_text(str(value)))
    if not match:
        return None
    year = int(match.group("y"))
    month = int(match.group("m"))
    day = int(match.group("d")) if match.group("d") else None
    if day is None:
        return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None
    try:
        date(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _normalized_claim(candidate: ClaimCandidate) -> dict[str, object]:
    value: object = candidate.value
    if candidate.claim_type == "count":
        number = _decimal_value(candidate.value)
        value = str(number.normalize()) if number is not None else candidate.value
    elif candidate.claim_type == "date":
        value = _normalize_date(candidate.value) or candidate.value
    return {
        "claim_type": candidate.claim_type,
        "subject": _normalized_text(candidate.subject),
        "object": _normalized_text(candidate.object),
        "value": value,
        "unit": _normalized_text(candidate.unit),
        "polarity": candidate.polarity,
    }


def _finish(
    candidate: ClaimCandidate,
    evidence: str,
    *,
    status: str,
    reasons: Sequence[str],
    spans: Sequence[tuple[int, int]] = (),
) -> ClaimValidationResult:
    normalized = _normalized_claim(candidate)
    claim_payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = sha256(claim_payload.encode("utf-8")).hexdigest()
    evidence_hash = sha256(evidence.encode("utf-8")).hexdigest()
    unique_reasons = tuple(sorted(set(reasons)))
    result_payload = "\0".join(
        (
            VALIDATOR_VERSION,
            fingerprint,
            candidate.source_id,
            candidate.unit_id,
            str(candidate.evidence_start),
            str(candidate.evidence_end),
            evidence_hash,
            status,
            ",".join(unique_reasons),
        )
    )
    accepted = status == _STATUS_ACCEPTED
    return ClaimValidationResult(
        result_id="clv_" + sha256(result_payload.encode("utf-8")).hexdigest()[:24],
        claim_fingerprint=fingerprint,
        validator_version=VALIDATOR_VERSION,
        status=status,
        reason_codes=unique_reasons,
        may_index=accepted,
        # Claim validation alone is never sufficient for final snapshot freeze.
        may_freeze=False,
        source_id=candidate.source_id,
        unit_id=candidate.unit_id,
        evidence_start=candidate.evidence_start,
        evidence_end=candidate.evidence_end,
        evidence_sha256=evidence_hash,
        matched_spans=tuple(spans),
        normalized_claim=normalized,
    )


def _modal_review(
    candidate: ClaimCandidate,
    evidence: str,
    matches: Sequence[re.Match[str]],
) -> ClaimValidationResult:
    return _finish(
        candidate,
        evidence,
        status=_STATUS_REVIEW,
        reasons=("MODAL_REPORTED_OR_QUESTION_ASSERTION",),
        spans=[_span(match) for match in matches],
    )


def _validate_alias(candidate: ClaimCandidate, evidence: str) -> ClaimValidationResult:
    if not candidate.subject or not candidate.object:
        return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("ALIAS_TERMS_REQUIRED",))
    forward = _relation_regex(candidate.subject, candidate.object, _ALIAS_MARKERS)
    reverse = _relation_regex(candidate.object, candidate.subject, _ALIAS_MARKERS)
    positive, modal_positive = _partition_modal(
        _clean_matches(forward, evidence) + _clean_matches(reverse, evidence), evidence
    )
    negated, modal_negated = _partition_modal(
        _negated_matches(forward, evidence) + _negated_matches(reverse, evidence), evidence
    )
    if positive and negated:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REVIEW,
            reasons=("CONFLICTING_ALIAS_ASSERTIONS",),
            spans=[_span(match) for match in positive + negated],
        )
    if positive:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_ACCEPTED,
            reasons=("EXACT_TYPED_ALIAS_MATCH",),
            spans=[_span(match) for match in positive],
        )
    if negated:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REJECTED,
            reasons=("NEGATED_ALIAS_RELATION",),
            spans=[_span(match) for match in negated],
        )
    if modal_positive or modal_negated:
        return _modal_review(candidate, evidence, modal_positive + modal_negated)
    return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("ALIAS_RELATION_NOT_FOUND",))


def _validate_directional(
    candidate: ClaimCandidate,
    evidence: str,
    *,
    markers: Sequence[str],
    accepted_reason: str,
) -> ClaimValidationResult:
    if not candidate.subject or not candidate.object:
        return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("RELATION_TERMS_REQUIRED",))
    direct_pattern = _relation_regex(candidate.subject, candidate.object, markers)
    reverse_pattern = _relation_regex(candidate.object, candidate.subject, markers)
    direct, modal_direct = _partition_modal(_clean_matches(direct_pattern, evidence), evidence)
    negated, modal_negated = _partition_modal(_negated_matches(direct_pattern, evidence), evidence)
    reverse, modal_reverse = _partition_modal(_clean_matches(reverse_pattern, evidence), evidence)
    if direct and (negated or reverse):
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REVIEW,
            reasons=("CONFLICTING_RELATION_ASSERTIONS",),
            spans=[_span(match) for match in direct + negated + reverse],
        )
    if direct:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_ACCEPTED,
            reasons=(accepted_reason,),
            spans=[_span(match) for match in direct],
        )
    if negated:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REJECTED,
            reasons=("NEGATED_RELATION",),
            spans=[_span(match) for match in negated],
        )
    if reverse:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REJECTED,
            reasons=("RELATION_DIRECTION_MISMATCH",),
            spans=[_span(match) for match in reverse],
        )
    modal = modal_direct + modal_negated + modal_reverse
    if modal:
        return _modal_review(candidate, evidence, modal)
    return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("RELATION_NOT_FOUND",))


def _permission_pattern(candidate: ClaimCandidate, markers: Sequence[str]) -> re.Pattern[str]:
    action = _literal_pattern(candidate.object)
    marker = _marker_pattern(markers)
    gap = r"[^\n。！？!?；;，,]{0,16}?"
    if candidate.subject:
        return re.compile(
            rf"{_literal_pattern(candidate.subject)}{gap}(?P<marker>{marker}){gap}{action}",
            re.IGNORECASE,
        )
    return re.compile(rf"(?P<marker>{marker}){gap}{action}", re.IGNORECASE)


def _validate_permission(candidate: ClaimCandidate, evidence: str) -> ClaimValidationResult:
    if not candidate.object:
        return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("PERMISSION_ACTION_REQUIRED",))
    positive, modal_positive = _partition_modal(
        _positive_permission_matches(
            _permission_pattern(candidate, _POSITIVE_PERMISSION_MARKERS), evidence
        ),
        evidence,
    )
    negative, modal_negative = _partition_modal(
        list(_permission_pattern(candidate, _NEGATIVE_PERMISSION_MARKERS).finditer(evidence)),
        evidence,
    )
    expected = positive if candidate.polarity else negative
    opposite = negative if candidate.polarity else positive
    if expected and opposite:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REVIEW,
            reasons=("CONFLICTING_PERMISSION_ASSERTIONS",),
            spans=[_span(match) for match in expected + opposite],
        )
    if expected:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_ACCEPTED,
            reasons=("EXACT_TYPED_PERMISSION_MATCH",),
            spans=[_span(match) for match in expected],
        )
    if opposite:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REJECTED,
            reasons=("PERMISSION_POLARITY_MISMATCH",),
            spans=[_span(match) for match in opposite],
        )
    modal = modal_positive + modal_negative
    if modal:
        return _modal_review(candidate, evidence, modal)
    return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("PERMISSION_RELATION_NOT_FOUND",))


def _validate_count(candidate: ClaimCandidate, evidence: str) -> ClaimValidationResult:
    expected = _decimal_value(candidate.value)
    if not candidate.subject or expected is None:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REJECTED,
            reasons=("COUNT_SUBJECT_AND_NUMERIC_VALUE_REQUIRED",),
        )
    relevant = [
        (start, clause)
        for start, clause in _split_clauses(evidence)
        if _normalized_text(candidate.subject).casefold() in _normalized_text(clause).casefold()
        and _contains_marker(clause, _COUNT_CUES)
    ]
    if not relevant:
        return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("COUNT_ASSERTION_NOT_FOUND",))

    exact_spans: list[tuple[int, int]] = []
    modal_exact_spans: list[tuple[int, int]] = []
    observed_assertive: set[Decimal] = set()
    observed_any: set[Decimal] = set()
    for clause_start, clause in relevant:
        clause_modal = bool(_MODALITY_RE.search(clause) or _QUESTION_RE.search(clause))
        subject_spans = [match.span() for match in re.compile(_literal_pattern(candidate.subject), re.IGNORECASE).finditer(clause)]
        cue_spans = [
            match.span()
            for cue in _COUNT_CUES
            for match in re.compile(_literal_pattern(cue), re.IGNORECASE).finditer(clause)
        ]
        for number, start, end in _extract_numbers(clause):
            # Digits embedded in the subject identity (for example ``阵列00`` or
            # ``第2阵列``) are not competing count values. They remain part of
            # the entity name and therefore must be excluded from numeric scope.
            if any(span_start < end and start < span_end for span_start, span_end in (*subject_spans, *cue_spans)):
                continue
            observed_any.add(number)
            if not clause_modal:
                observed_assertive.add(number)
            if number != expected:
                continue
            if candidate.unit:
                tail = clause[end : end + max(8, len(candidate.unit) + 4)]
                if _normalized_text(candidate.unit).casefold() not in _normalized_text(tail).casefold():
                    continue
            target = modal_exact_spans if clause_modal else exact_spans
            target.append((clause_start + start, clause_start + end))
    if exact_spans and any(value != expected for value in observed_assertive):
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REVIEW,
            reasons=("MULTIPLE_COUNT_VALUES",),
            spans=exact_spans,
        )
    if exact_spans:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_ACCEPTED,
            reasons=("EXACT_TYPED_COUNT_MATCH",),
            spans=exact_spans,
        )
    if modal_exact_spans:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REVIEW,
            reasons=("MODAL_REPORTED_OR_QUESTION_ASSERTION",),
            spans=modal_exact_spans,
        )
    reason = "NUMERIC_VALUE_MISMATCH" if observed_any else "COUNT_VALUE_NOT_FOUND"
    return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=(reason,))


def _validate_date(candidate: ClaimCandidate, evidence: str) -> ClaimValidationResult:
    expected = _normalize_date(candidate.value)
    if not candidate.subject or expected is None:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REJECTED,
            reasons=("DATE_SUBJECT_AND_VALUE_REQUIRED",),
        )
    relevant = [
        (start, clause)
        for start, clause in _split_clauses(evidence)
        if _normalized_text(candidate.subject).casefold() in _normalized_text(clause).casefold()
        and _contains_marker(clause, _DATE_CUES)
    ]
    if not relevant:
        return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("DATE_ASSERTION_NOT_FOUND",))

    exact_spans: list[tuple[int, int]] = []
    modal_exact_spans: list[tuple[int, int]] = []
    observed_assertive: set[str] = set()
    observed_any: set[str] = set()
    for clause_start, clause in relevant:
        clause_modal = bool(_MODALITY_RE.search(clause) or _QUESTION_RE.search(clause))
        for match in _DATE_TOKEN_RE.finditer(clause):
            normalized = _normalize_date(match.group(0))
            if normalized is None:
                continue
            observed_any.add(normalized)
            if not clause_modal:
                observed_assertive.add(normalized)
            if normalized == expected:
                target = modal_exact_spans if clause_modal else exact_spans
                target.append((clause_start + match.start(), clause_start + match.end()))
    if exact_spans and any(value != expected for value in observed_assertive):
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REVIEW,
            reasons=("MULTIPLE_DATE_VALUES",),
            spans=exact_spans,
        )
    if exact_spans:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_ACCEPTED,
            reasons=("EXACT_TYPED_DATE_MATCH",),
            spans=exact_spans,
        )
    if modal_exact_spans:
        return _finish(
            candidate,
            evidence,
            status=_STATUS_REVIEW,
            reasons=("MODAL_REPORTED_OR_QUESTION_ASSERTION",),
            spans=modal_exact_spans,
        )
    reason = "DATE_VALUE_MISMATCH" if observed_any else "DATE_VALUE_NOT_FOUND"
    return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=(reason,))


def validate_claim(
    candidate: ClaimCandidate,
    source_text: str,
    *,
    unit_span: UnitSpan | None = None,
    require_unit: bool = False,
) -> ClaimValidationResult:
    """Validate one candidate against its exact source span and optional Unit."""

    if not isinstance(source_text, str):
        raise TypeError("source_text must be a string")
    if candidate.evidence_start < 0 or candidate.evidence_end <= candidate.evidence_start:
        return _finish(candidate, "", status=_STATUS_REJECTED, reasons=("EVIDENCE_SPAN_INVALID",))
    if candidate.evidence_end > len(source_text):
        return _finish(candidate, "", status=_STATUS_REJECTED, reasons=("EVIDENCE_SPAN_OUT_OF_RANGE",))

    evidence = source_text[candidate.evidence_start : candidate.evidence_end]
    if candidate.evidence_text is not None and candidate.evidence_text != evidence:
        return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("EVIDENCE_TEXT_MISMATCH",))
    if require_unit and unit_span is None:
        return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("UNIT_NOT_FOUND",))
    if unit_span is not None:
        if (unit_span.source_id, unit_span.unit_id) != (candidate.source_id, candidate.unit_id):
            return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("UNIT_IDENTITY_MISMATCH",))
        if not unit_span.start <= candidate.evidence_start < candidate.evidence_end <= unit_span.end:
            return _finish(candidate, evidence, status=_STATUS_REJECTED, reasons=("EVIDENCE_OUTSIDE_UNIT",))

    if candidate.claim_type not in SUPPORTED_CLAIM_TYPES:
        return _finish(candidate, evidence, status=_STATUS_REVIEW, reasons=("UNSUPPORTED_CLAIM_TYPE",))
    if candidate.claim_type == "alias":
        return _validate_alias(candidate, evidence)
    if candidate.claim_type == "defeats":
        return _validate_directional(
            candidate,
            evidence,
            markers=_DEFEAT_MARKERS,
            accepted_reason="EXACT_TYPED_DEFEAT_MATCH",
        )
    if candidate.claim_type == "located_in":
        return _validate_directional(
            candidate,
            evidence,
            markers=_LOCATION_MARKERS,
            accepted_reason="EXACT_TYPED_LOCATION_MATCH",
        )
    if candidate.claim_type == "permission":
        return _validate_permission(candidate, evidence)
    if candidate.claim_type == "count":
        return _validate_count(candidate, evidence)
    if candidate.claim_type == "date":
        return _validate_date(candidate, evidence)
    raise AssertionError("unreachable claim type")
