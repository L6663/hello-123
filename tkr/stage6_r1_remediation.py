"""Stage 6-R1 targeted correctness remediation.

This module applies three narrow deterministic fixes identified by the first
integrated acceptance run.  It does not add claim types, relax evidence gates,
or grant acceptance/release/freeze authority.
"""
from __future__ import annotations

from decimal import Decimal
import re
from typing import Final

from . import anomaly_detection as _anomaly
from . import claim_validation as _claim
from . import heading_detection as _heading

REMEDIATION_VERSION: Final = "tkr-final-remediation-v1"

_APPLIED = False
_ORIGINAL_HEADING_DETECTOR = _heading.detect_heading


def _shift_signals(previous, current, policy) -> tuple[str, ...]:
    """Require a lexical break plus an independent corroborating family.

    Stage 1 previously emitted two signal strings for one entity-set
    observation (Jaccard and union size).  With a two-signal policy, a single
    entity change could therefore promote an ordinary chapter transition.
    Entity discontinuity is now one signal family, and lexical discontinuity
    is mandatory before any same-language cross-work candidate is emitted.
    """

    if min(previous.cjk, current.cjk) < policy.same_language_min_cjk_ratio:
        return ()

    lexical = _anomaly._cosine(previous.grams, current.grams)
    if lexical > policy.same_language_max_cosine_similarity:
        return ()

    signals: list[str] = [f"lexical_cosine={lexical:.3f}"]
    union = previous.entities | current.entities
    jaccard = len(previous.entities & current.entities) / len(union) if union else 1.0
    if (
        previous.entities
        and current.entities
        and len(union) >= policy.same_language_min_entity_union
        and jaccard <= policy.same_language_max_entity_jaccard
    ):
        signals.append(
            f"entity_discontinuity=jaccard:{jaccard:.3f};union:{len(union)}"
        )

    old = max(previous.registers, key=previous.registers.get)
    new = max(current.registers, key=current.registers.get)
    if (
        old != new
        and previous.registers[old] >= policy.same_language_min_register_delta
        and current.registers[new] >= policy.same_language_min_register_delta
    ):
        signals.append(f"register={old}->{new}")

    ratio = max(previous.mean_sentence, current.mean_sentence) / max(
        1.0, min(previous.mean_sentence, current.mean_sentence)
    )
    if ratio >= policy.same_language_min_sentence_length_ratio:
        signals.append(f"sentence_length_ratio={ratio:.3f}")

    if len(signals) < policy.same_language_min_signals:
        return ()
    return (
        f"previous_span={previous.start}-{previous.end}",
        f"previous_lines={previous.start_line}-{previous.end_line}",
        *signals,
    )


_NUMBER = _heading.NUMBER_TOKEN
_COMBINED_VOLUME_CHAPTER_RE = re.compile(
    rf"^(?:"
    rf"第\s*(?P<volume_prefix>{_NUMBER})\s*[卷集]"
    rf"|[卷集]\s*(?P<volume_suffix>{_NUMBER})"
    rf")\s*(?:[-—–:：·.．]\s*)?"
    rf"(?:"
    rf"第\s*(?P<chapter_prefix>{_NUMBER})\s*(?P<chapter_unit_prefix>[章回幕])"
    rf"|(?P<chapter_unit_suffix>[章回幕])\s*(?P<chapter_suffix>{_NUMBER})"
    rf")(?P<rest>.*)$"
)


def _combined_heading(content: str, policy) -> object | None:
    markdown = _heading.MARKDOWN_RE.match(content)
    signals: list[str] = []
    if markdown is not None and policy.accept_markdown_headings:
        search_text = markdown.group("body")
        offset = markdown.start("body")
        signals.append(f"markdown_level={len(markdown.group('marks'))}")
    else:
        offset = len(content) - len(content.lstrip())
        search_text = content[offset:]

    match = _COMBINED_VOLUME_CHAPTER_RE.match(search_text)
    if match is None:
        return None

    volume_text = match.group("volume_prefix") or match.group("volume_suffix") or ""
    chapter_text = match.group("chapter_prefix") or match.group("chapter_suffix") or ""
    volume_ordinal = _heading.parse_ordinal(volume_text)
    chapter_ordinal = _heading.parse_ordinal(chapter_text)
    marker_end = match.start("rest")
    rest = match.group("rest")
    title, heading_end, body_start, split_signals = _heading.split_title_and_body(
        rest, marker_end, policy.inline_title_max_characters
    )
    separated = not rest or rest[:1].isspace() or rest[:1] in "—–-:：·.．\t　"
    accepted = chapter_ordinal is not None and volume_ordinal is not None and (
        len(search_text) <= policy.max_heading_characters or separated or split_signals
    )
    confidence = "high" if accepted and (separated or not rest) else "medium" if accepted else "low"
    extras = [
        "combined_volume_chapter_heading",
        "container_type=volume",
        f"container_ordinal={volume_ordinal}",
        *split_signals,
    ]
    if not accepted:
        extras.append("ambiguous_combined_heading")

    return _heading.DetectedHeading(
        "COMBINED_VOLUME_CHAPTER_HEADING",
        "chapter",
        2,
        chapter_ordinal,
        chapter_text,
        title,
        search_text[:heading_end],
        offset,
        offset + marker_end,
        offset + heading_end,
        offset + body_start,
        confidence,
        accepted,
        tuple(signals + extras),
    )


def _detect_heading(content: str, policy):
    combined = _combined_heading(content, policy)
    return combined if combined is not None else _ORIGINAL_HEADING_DETECTOR(content, policy)


_COUNT_SEGMENT_BREAK_RE = re.compile(r"[\n。！？!?；;，,]+")
_COUNT_CUE_RE = re.compile(_claim._marker_pattern(_claim._COUNT_CUES), re.IGNORECASE)


def _count_segments(evidence: str) -> list[tuple[int, str]]:
    segments: list[tuple[int, str]] = []
    start = 0
    for match in _COUNT_SEGMENT_BREAK_RE.finditer(evidence):
        if match.start() > start:
            segments.append((start, evidence[start:match.start()]))
        start = match.end()
    if start < len(evidence):
        segments.append((start, evidence[start:]))
    return segments


def _validate_count(candidate, evidence: str):
    """Validate only cue-governed numeric values outside Subject spans."""

    expected = _claim._decimal_value(candidate.value)
    if not candidate.subject or expected is None:
        return _claim._finish(
            candidate,
            evidence,
            status=_claim._STATUS_REJECTED,
            reasons=("COUNT_SUBJECT_AND_NUMERIC_VALUE_REQUIRED",),
        )

    subject_pattern = re.compile(_claim._literal_pattern(candidate.subject), re.IGNORECASE)
    relevant: list[tuple[int, str]] = []
    normalized_subject = _claim._normalized_text(candidate.subject).casefold()
    for start, segment in _count_segments(evidence):
        if (
            normalized_subject in _claim._normalized_text(segment).casefold()
            and _claim._contains_marker(segment, _claim._COUNT_CUES)
        ):
            relevant.append((start, segment))
    if not relevant:
        return _claim._finish(
            candidate,
            evidence,
            status=_claim._STATUS_REJECTED,
            reasons=("COUNT_ASSERTION_NOT_FOUND",),
        )

    exact_spans: list[tuple[int, int]] = []
    modal_exact_spans: list[tuple[int, int]] = []
    observed_assertive: set[Decimal] = set()
    observed_any: set[Decimal] = set()

    for segment_start, segment in relevant:
        segment_modal = bool(
            _claim._MODALITY_RE.search(segment) or _claim._QUESTION_RE.search(segment)
        )
        subject_spans = [(m.start(), m.end()) for m in subject_pattern.finditer(segment)]
        cues = list(_COUNT_CUE_RE.finditer(segment))
        for number, start, end in _claim._extract_numbers(segment):
            if any(left < end and start < right for left, right in subject_spans):
                continue
            preceding = [cue for cue in cues if cue.end() <= start]
            if not preceding:
                continue
            cue = preceding[-1]
            subject_governs_value = any(right <= cue.start() for _, right in subject_spans) or any(
                left >= end for left, _ in subject_spans
            )
            if not subject_governs_value:
                continue

            observed_any.add(number)
            if not segment_modal:
                observed_assertive.add(number)
            if number != expected:
                continue
            if candidate.unit:
                tail = segment[end:end + max(8, len(candidate.unit) + 4)]
                if _claim._normalized_text(candidate.unit).casefold() not in _claim._normalized_text(tail).casefold():
                    continue
            target = modal_exact_spans if segment_modal else exact_spans
            target.append((segment_start + start, segment_start + end))

    if exact_spans and any(value != expected for value in observed_assertive):
        return _claim._finish(
            candidate,
            evidence,
            status=_claim._STATUS_REVIEW,
            reasons=("MULTIPLE_COUNT_VALUES",),
            spans=exact_spans,
        )
    if exact_spans:
        return _claim._finish(
            candidate,
            evidence,
            status=_claim._STATUS_ACCEPTED,
            reasons=("EXACT_TYPED_COUNT_MATCH",),
            spans=exact_spans,
        )
    if modal_exact_spans:
        return _claim._finish(
            candidate,
            evidence,
            status=_claim._STATUS_REVIEW,
            reasons=("MODAL_REPORTED_OR_QUESTION_ASSERTION",),
            spans=modal_exact_spans,
        )
    reason = "NUMERIC_VALUE_MISMATCH" if observed_any else "COUNT_VALUE_NOT_FOUND"
    return _claim._finish(candidate, evidence, status=_claim._STATUS_REJECTED, reasons=(reason,))


def apply_stage6_r1_remediation() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _anomaly._shift_signals = _shift_signals
    _anomaly.ANOMALY_DETECTOR_VERSION = "5.9.0-phase9.4-final"
    _heading.detect_heading = _detect_heading
    _claim._validate_count = _validate_count
    _claim.VALIDATOR_VERSION = "tkr-claim-validator-v1-final"
    _APPLIED = True


__all__ = ["REMEDIATION_VERSION", "apply_stage6_r1_remediation"]
