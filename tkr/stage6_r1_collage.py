"""Structured same-language collage detection for Stage 6-R1.

When a source has explicit chapter-like boundaries, fixed adjacent windows are
not authoritative: one contaminated chapter can emit many internal shifts.
This detector emits at most one bounded splice candidate per structural block
when the suffix shows persistent paragraph-level incoherence.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path
import re
import statistics
from typing import Callable

from . import anomaly_detection as _anomaly

_COLLAGE_NUMBER = r"(?:[0-9０-９零〇○一二三四五六七八九十百千万萬亿億两兩][ \t]*)+"
_COLLAGE_HEADING_RE = re.compile(
    rf"(?m)^[ \t]*(?:(?:"
    rf"(?:第[ \t]*{_COLLAGE_NUMBER}[卷集]|[卷集][ \t]*{_COLLAGE_NUMBER})"
    rf"[ \t]*(?:[-—–:：·.．][ \t]*)?"
    rf"(?:第[ \t]*{_COLLAGE_NUMBER}[章回幕]|[章回幕][ \t]*{_COLLAGE_NUMBER})"
    rf")|(?:外传|外傳|番外|免费章|免費章)[^\r\n]*)[^\r\n]*"
)
_COLLAGE_PARAGRAPH_BREAK_RE = re.compile(r"(?:\r?\n)[ \t]*(?:\r?\n)+")


def _paragraphs(text: str, start: int, end: int) -> list[tuple[int, int, str]]:
    block = text[start:end]
    rows: list[tuple[int, int, str]] = []
    cursor = 0
    for match in _COLLAGE_PARAGRAPH_BREAK_RE.finditer(block):
        chunk = block[cursor:match.start()]
        if chunk.strip():
            leading = len(chunk) - len(chunk.lstrip())
            trailing = len(chunk.rstrip())
            rows.append((start + cursor + leading, start + cursor + trailing, chunk.strip()))
        cursor = match.end()
    chunk = block[cursor:]
    if chunk.strip():
        leading = len(chunk) - len(chunk.lstrip())
        trailing = len(chunk.rstrip())
        rows.append((start + cursor + leading, start + cursor + trailing, chunk.strip()))
    return rows


def _metrics(paragraphs: list[tuple[int, int, str]]) -> tuple[float, float, float]:
    if len(paragraphs) < 2:
        return (0.0, 0.0, 1.0)
    grams = [_anomaly._grams(item[2]) for item in paragraphs]
    adjacent = [_anomaly._cosine(left, right) for left, right in zip(grams, grams[1:])]
    recent_maximum = [
        max(
            _anomaly._cosine(grams[index], grams[prior])
            for prior in range(max(0, index - 3), index)
        )
        for index in range(1, len(grams))
    ]
    low_adjacent = sum(value < 0.05 for value in adjacent) / len(adjacent)
    low_recent = sum(value < 0.10 for value in recent_maximum) / len(recent_maximum)
    return (low_adjacent, low_recent, statistics.mean(adjacent))


def _findings(text: str, source_hash: str, preview: int):
    headings = list(_COLLAGE_HEADING_RE.finditer(text))
    if len(headings) < 2:
        return None

    findings = []
    for index, heading in enumerate(headings):
        block_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        paragraphs = _paragraphs(text, heading.end(), block_end)
        low_adjacent, low_recent, mean_adjacent = _metrics(paragraphs)
        if len(paragraphs) < 12 or low_adjacent < 0.80 or low_recent < 0.80:
            continue

        cut = None
        cut_index = None
        latest = min(len(paragraphs) - 8 + 1, 12)
        for paragraph_index in range(3, max(3, latest)):
            suffix = paragraphs[paragraph_index:]
            suffix_low_adjacent, suffix_low_recent, _ = _metrics(suffix)
            boundary_cosine = _anomaly._cosine(
                _anomaly._grams(paragraphs[paragraph_index - 1][2]),
                _anomaly._grams(paragraphs[paragraph_index][2]),
            )
            if (
                suffix_low_adjacent >= 0.80
                and suffix_low_recent >= 0.80
                and boundary_cosine < 0.08
            ):
                cut = paragraphs[paragraph_index][0]
                cut_index = paragraph_index
                break
        if cut is None:
            cut_index = 3
            cut = paragraphs[cut_index][0]

        start_line = 1 + _anomaly._line_breaks(text[:cut])
        end_line = max(start_line, 1 + _anomaly._line_breaks(text[:block_end]))
        evidence = text[cut:block_end]
        findings.append(
            _anomaly._finding(
                source_hash,
                "INTRA_UNIT_CROSS_WORK_SPLICE_CANDIDATE",
                "contamination_candidate",
                "high",
                "high",
                "manual_cross_work_boundary_review",
                cut,
                block_end,
                start_line,
                end_line,
                evidence,
                preview,
                (
                    f"structural_block_span={heading.start()}-{block_end}",
                    f"heading={heading.group().strip()[:80]}",
                    f"paragraph_count={len(paragraphs)}",
                    f"candidate_start_paragraph={cut_index}",
                    f"low_adjacent_cosine_ratio={low_adjacent:.3f}",
                    f"low_recent_similarity_ratio={low_recent:.3f}",
                    f"mean_adjacent_cosine={mean_adjacent:.3f}",
                ),
            )
        )
    return findings


def build_structured_anomaly_inspector(original_inspector: Callable):
    """Wrap Stage 1 and replace noisy window shifts on structured sources."""

    def inspect(path, *, policy=None, marker_groups=(), block_size=_anomaly.DEFAULT_BLOCK_SIZE):
        report = original_inspector(
            path, policy=policy, marker_groups=marker_groups, block_size=block_size
        )
        if report.scan_status != "completed" or report.selected_encoding is None:
            return report

        raw = Path(path).read_bytes()
        prefix = _anomaly._BOMS.get(report.selected_encoding, b"")
        if prefix and raw.startswith(prefix):
            raw = raw[len(prefix):]
        text = raw.decode(report.selected_encoding, errors="strict")
        collage = _findings(
            text,
            report.source_sha256,
            int(report.policy["preview_characters"]),
        )
        if collage is None:
            return report

        retained = [
            item
            for item in report.findings
            if item.rule_id != "SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE"
        ]
        findings = sorted(
            [*retained, *collage],
            key=lambda item: (item.start_char, item.end_char, item.rule_id, item.finding_id),
        )
        categories = Counter(item.category for item in findings)
        rules = Counter(item.rule_id for item in findings)
        action = (
            "review_candidates_incomplete_due_to_limit"
            if "FINDING_LIMIT_REACHED" in report.warnings
            else "review_candidates"
            if findings
            else "review_source_warnings"
            if report.warnings
            else "no_candidates_detected"
        )
        return replace(
            report,
            detector_version="5.9.0-phase9.4-final",
            finding_count=len(findings),
            category_counts=dict(sorted(categories.items())),
            rule_counts=dict(sorted(rules.items())),
            recommended_action=action,
            findings=tuple(findings),
        )

    return inspect


__all__ = ["build_structured_anomaly_inspector"]
