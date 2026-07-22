"""Conservative deterministic heading candidate recognition."""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Final
from .structure_models import StructurePolicy, parse_ordinal

NUMBER_TOKEN: Final = r"(?:[0-9０-９零〇○一二三四五六七八九十百千万萬亿億两兩]\s*)+"
UNIT_CHAR_TO_TYPE: Final = {
    "卷": ("volume", 1), "部": ("part", 1), "篇": ("part", 1), "集": ("volume", 1),
    "章": ("chapter", 2), "回": ("chapter", 2), "幕": ("chapter", 2),
    "节": ("section", 3), "節": ("section", 3),
}
ENGLISH_TYPE: Final = {
    "volume": ("volume", 1), "book": ("volume", 1), "part": ("part", 1),
    "chapter": ("chapter", 2), "section": ("section", 3),
}
SPECIAL_PREFIXES: Final = (
    ("序章", "prologue", 2), ("楔子", "prologue", 2), ("引子", "prologue", 2),
    ("前言", "preface", 1), ("序言", "preface", 1), ("序", "preface", 1),
    ("终章", "epilogue", 2), ("終章", "epilogue", 2),
    ("尾声", "epilogue", 2), ("尾聲", "epilogue", 2),
    ("后记", "afterword", 1), ("後記", "afterword", 1),
    ("番外", "extra_story", 2), ("外传", "extra_story", 2),
    ("外傳", "extra_story", 2), ("特别篇", "extra_story", 2),
    ("特別篇", "extra_story", 2), ("附录", "appendix", 1), ("附錄", "appendix", 1),
)
SPECIAL_ENGLISH: Final = {
    "prologue": ("prologue", 2), "preface": ("preface", 1),
    "introduction": ("preface", 1), "epilogue": ("epilogue", 2),
    "afterword": ("afterword", 1), "appendix": ("appendix", 1),
    "interlude": ("extra_story", 2), "extra": ("extra_story", 2),
}
NUMBERED_PREFIX_RE = re.compile(rf"^第\s*(?P<number>{NUMBER_TOKEN})\s*(?P<unit>[卷部篇集章回幕节節])(?P<rest>.*)$")
NUMBERED_SUFFIX_RE = re.compile(rf"^(?P<unit>[卷部篇集章回幕节節])\s*(?P<number>{NUMBER_TOKEN})(?P<rest>.*)$")
ENGLISH_NUMBERED_RE = re.compile(r"^(?P<kind>volume|book|part|chapter|section)\s+(?P<number>[0-9]+)(?P<rest>.*)$", re.IGNORECASE)
SPLIT_PREFIX_RE = re.compile(rf"^第\s*(?P<number>{NUMBER_TOKEN})\s*$")
SPLIT_SUFFIX_RE = re.compile(r"^(?P<unit>[卷部篇集章回幕节節])(?P<rest>.*)$")
MARKDOWN_RE = re.compile(r"^(?P<indent>\s*)(?P<marks>#{1,6})[ \t]+(?P<body>.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
SENTENCE_MARKS = "。！？!?；;"
_TITLE_BODY_RE = re.compile(r"^(?P<title>.{1,48}?)(?P<sep>[：:。！？!?；;])(?P<body>\S.*)$")
_EXPLICIT_BODY_RE = re.compile(r"^(?P<title>.{0,48}?)(?P<sep>\t+| {2,}|　{2,})(?P<body>\S.*)$")

@dataclass(frozen=True, slots=True)
class DetectedHeading:
    rule_id: str
    unit_type: str
    hierarchy_level: int
    ordinal: int | None
    ordinal_text: str
    title: str
    raw_heading: str
    marker_start_in_line: int
    marker_end_in_line: int
    heading_end_in_line: int
    body_start_in_line: int
    confidence: str
    accepted_as_boundary: bool
    signals: tuple[str, ...]

def split_title_and_body(rest: str, marker_end: int, title_limit: int) -> tuple[str, int, int, tuple[str, ...]]:
    clean = rest.lstrip(" \t　—–-:：·.．")
    base = marker_end + len(rest) - len(clean)
    if not clean:
        return "", marker_end, marker_end, ()
    explicit = _EXPLICIT_BODY_RE.match(clean)
    if explicit and len(explicit.group("title").strip()) <= title_limit:
        title = explicit.group("title").strip()
        body = base + explicit.start("body")
        return title, body, body, ("inline_body_explicit_separator",)
    sentence = _TITLE_BODY_RE.match(clean)
    if sentence and len(sentence.group("title").strip()) <= title_limit:
        title = sentence.group("title").strip()
        body = base + sentence.start("body")
        return title, body, body, ("inline_body_sentence_separator",)
    return clean.strip(), base + len(clean), base + len(clean), ()

def _numbered(search_text: str, offset: int, signals: list[str], policy: StructurePolicy) -> DetectedHeading | None:
    match = NUMBERED_PREFIX_RE.match(search_text)
    rule = "NUMBERED_PREFIX_HEADING"
    if match is None:
        match = NUMBERED_SUFFIX_RE.match(search_text)
        rule = "NUMBERED_SUFFIX_HEADING"
    if match is None:
        return None
    number_text = match.group("number")
    ordinal = parse_ordinal(number_text)
    unit_type, level = UNIT_CHAR_TO_TYPE[match.group("unit")]
    marker_end = match.start("rest")
    rest = match.group("rest")
    title, heading_end, body_start, split_signals = split_title_and_body(
        rest, marker_end, policy.inline_title_max_characters
    )
    separated = not rest or rest[:1].isspace() or rest[:1] in "—–-:：·.．\t　"
    accepted = ordinal is not None and (
        len(search_text) <= policy.max_heading_characters or separated or split_signals
    )
    confidence = "high" if ordinal is not None and (separated or not rest) else "medium" if accepted else "low"
    extras = list(split_signals)
    if not separated:
        extras.append("compact_numbered_heading")
    if not accepted:
        extras.append("ambiguous_long_unseparated_heading")
    return DetectedHeading(
        rule, unit_type, level, ordinal, number_text, title, search_text[:heading_end],
        offset, offset + marker_end, offset + heading_end, offset + body_start,
        confidence, accepted, tuple(signals + extras),
    )

def detect_heading(content: str, policy: StructurePolicy) -> DetectedHeading | None:
    markdown = MARKDOWN_RE.match(content)
    signals: list[str] = []
    if markdown is not None and policy.accept_markdown_headings:
        search_text = markdown.group("body")
        offset = markdown.start("body")
        markdown_level = len(markdown.group("marks"))
        signals.append(f"markdown_level={markdown_level}")
    else:
        offset = len(content) - len(content.lstrip())
        search_text = content[offset:]
        markdown_level = None
    if not search_text:
        return None
    numbered = _numbered(search_text, offset, signals, policy)
    if numbered is not None:
        return numbered
    english = ENGLISH_NUMBERED_RE.match(search_text)
    if english is not None:
        kind = english.group("kind").lower()
        unit_type, level = ENGLISH_TYPE[kind]
        marker_end = english.start("rest")
        title, heading_end, body_start, split_signals = split_title_and_body(
            english.group("rest"), marker_end, policy.inline_title_max_characters
        )
        accepted = len(search_text) <= policy.max_heading_characters or bool(split_signals)
        return DetectedHeading(
            "ENGLISH_NUMBERED_HEADING", unit_type, level, int(english.group("number")),
            english.group("number"), title, search_text[:heading_end], offset,
            offset + marker_end, offset + heading_end, offset + body_start,
            "high" if accepted else "low", accepted,
            tuple(signals + list(split_signals) + ([] if accepted else ["ambiguous_long_heading"])),
        )
    folded = search_text.casefold()
    for word, (unit_type, level) in SPECIAL_ENGLISH.items():
        if folded == word or folded.startswith((word + " ", word + ":")):
            marker_end = len(word)
            title, heading_end, body_start, split_signals = split_title_and_body(
                search_text[marker_end:], marker_end, policy.inline_title_max_characters
            )
            accepted = len(search_text) <= policy.max_heading_characters or bool(split_signals)
            return DetectedHeading(
                "ENGLISH_SPECIAL_HEADING", unit_type, level, None, "", title,
                search_text[:heading_end], offset, offset + marker_end,
                offset + heading_end, offset + body_start, "high" if accepted else "low",
                accepted, tuple(signals + list(split_signals)),
            )
    for prefix, unit_type, level in SPECIAL_PREFIXES:
        if search_text == prefix or search_text.startswith((prefix + " ", prefix + "：", prefix + ":", prefix + "—")):
            marker_end = len(prefix)
            title, heading_end, body_start, split_signals = split_title_and_body(
                search_text[marker_end:], marker_end, policy.inline_title_max_characters
            )
            accepted = len(search_text) <= policy.max_heading_characters or bool(split_signals)
            return DetectedHeading(
                "SPECIAL_HEADING", unit_type, level, None, "", title,
                search_text[:heading_end], offset, offset + marker_end,
                offset + heading_end, offset + body_start, "high" if accepted else "low",
                accepted, tuple(signals + list(split_signals)),
            )
    if markdown_level is not None and len(search_text) <= policy.max_heading_characters:
        level = min(4, markdown_level)
        return DetectedHeading(
            "MARKDOWN_GENERIC_HEADING", "section", level, None, "",
            search_text.strip(), search_text, offset, offset,
            offset + len(search_text), offset + len(search_text), "medium", True,
            tuple(signals + ["generic_markdown_heading"]),
        )
    return None
