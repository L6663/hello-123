"""Final combined volume/chapter parser used by Stage 6-R1."""
from __future__ import annotations

import re

from . import heading_detection as _heading

_PREVIOUS_DETECTOR = _heading.detect_heading
_ARABIC_NUMBER = r"[0-9０-９]+"
_CHINESE_NUMBER = (
    r"[零〇○一二三四五六七八九十百千万萬亿億两兩]"
    r"(?:[ \t]*[零〇○一二三四五六七八九十百千万萬亿億两兩])*?"
)
_NUMBER = rf"(?:{_ARABIC_NUMBER}|{_CHINESE_NUMBER})"
_COMBINED_RE = re.compile(
    rf"^(?:"
    rf"第[ \t]*(?P<volume_prefix>{_NUMBER})[ \t]*[卷集]"
    rf"|[卷集][ \t]*(?P<volume_suffix>{_NUMBER})"
    rf")[ \t]*(?:[-—–:：·.．][ \t]*)?"
    rf"(?:"
    rf"第[ \t]*(?P<chapter_prefix>{_NUMBER})[ \t]*(?P<chapter_unit_prefix>[章回幕])"
    rf"|(?P<chapter_bare>{_NUMBER})[ \t]*(?P<chapter_unit_bare>[章回幕])"
    rf"|(?P<chapter_unit_suffix>[章回幕])[ \t]*(?P<chapter_suffix>{_NUMBER})"
    rf")(?P<rest>.*)$"
)


def _combined(content: str, policy):
    markdown = _heading.MARKDOWN_RE.match(content)
    signals: list[str] = []
    if markdown is not None and policy.accept_markdown_headings:
        search_text = markdown.group("body")
        offset = markdown.start("body")
        signals.append(f"markdown_level={len(markdown.group('marks'))}")
    else:
        offset = len(content) - len(content.lstrip())
        search_text = content[offset:]

    match = _COMBINED_RE.match(search_text)
    if match is None:
        return None
    volume_text = match.group("volume_prefix") or match.group("volume_suffix") or ""
    chapter_text = (
        match.group("chapter_prefix")
        or match.group("chapter_bare")
        or match.group("chapter_suffix")
        or ""
    )
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
    confidence = (
        "high"
        if accepted and (separated or not rest)
        else "medium"
        if accepted
        else "low"
    )
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


def _detect(content: str, policy):
    combined = _combined(content, policy)
    return combined if combined is not None else _PREVIOUS_DETECTOR(content, policy)


def apply_stage6_r1_heading_patch() -> None:
    _heading.detect_heading = _detect


__all__ = ["apply_stage6_r1_heading_patch"]
