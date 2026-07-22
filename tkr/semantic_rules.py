"""Conservative lexical rules for the six supported Claim predicates."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Iterator, Sequence

from .structure_models import parse_ordinal

_ENTITY_RE = re.compile(r"[A-Za-z0-9_\-\u3400-\u9fff·]{1,48}")
_DATE_RE = re.compile(r"\d{4}(?:年|[-/.])\d{1,2}(?:(?:月|[-/.])\d{1,2}日?)?")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?|[零〇○一二两兩三四五六七八九十百千万萬亿億]+")
ALIAS = ("更名为", "改称", "又称", "亦称", "也称", "别名为", "别名是", "别名", "原名为", "原名是", "原名", "旧称", "被称为")
DEFEATS = ("击败", "战胜", "打败", "击溃")
LOCATED = ("坐落于", "位于", "地处", "设于")
PERMIT_POS = ("不受限制可以", "获准", "允许", "准许", "有权", "能够", "可以")
PERMIT_NEG = ("不允许", "不可以", "不得", "禁止", "无权", "不能")
COUNT = ("数量为", "数目为", "共有", "共计", "总计", "合计", "一共", "共")
DATE = ("出生于", "发生于", "开始于", "始于", "截至", "日期为", "时间为")
AMBIGUOUS_CUE_RE = re.compile(r"(?:同一人|身份|属于|担任|拥有|失去|成为|来自|前往|效忠|支持|反对|死亡|失踪|可能|似乎|传闻|怀疑|认为)")
_NEGATION_RE = re.compile(r"(?:并未|没有|不曾|从未|并非|不是|未曾|未能|未|不)")
_LEFT_CUES = (
    "在昨日", "在当日", "于昨日", "于当日", "后来", "随后", "最终", "曾经", "此前", "当时", "已经", "曾",
    "计划", "准备", "将要", "即将", "预计", "并未", "没有", "不曾", "从未", "未曾", "未能", "未", "不",
)
_RIGHT_STOPS = ("随后", "然后", "后来", "并且", "而后", "之后", "从此", "当场", "同时")


def _left(text: str) -> str:
    value = text.strip(" \t，,:：；;")
    changed = True
    while changed:
        changed = False
        for cue in _LEFT_CUES:
            if value.endswith(cue):
                value = value[:-len(cue)].rstrip()
                changed = True
    matches = list(_ENTITY_RE.finditer(value))
    return "" if not matches else matches[-1].group(0)[-24:]


def _right(text: str) -> str:
    match = _ENTITY_RE.match(text.lstrip(" \t，,:：；;"))
    if not match:
        return ""
    value = match.group(0)
    for word in _RIGHT_STOPS:
        position = value.find(word)
        if position > 0:
            value = value[:position]
    return value[:24]


def _action(text: str) -> str:
    value = text.strip(" \t，,:：；;。！？!?")
    for word in _RIGHT_STOPS:
        position = value.find(word)
        if position > 0:
            value = value[:position]
    return value[:48].strip()


def _markers(text: str, markers: Sequence[str]) -> Iterator[tuple[int, int, str]]:
    occupied: set[tuple[int, int]] = set()
    for marker in sorted(markers, key=lambda item: (-len(item), item)):
        cursor = 0
        while True:
            start = text.find(marker, cursor)
            if start < 0:
                break
            span = (start, start + len(marker))
            if not any(a < span[1] and span[0] < b for a, b in occupied):
                occupied.add(span)
                yield span[0], span[1], marker
            cursor = start + len(marker)


def _negated(text: str, marker_start: int) -> bool:
    return bool(_NEGATION_RE.search(text[max(0, marker_start - 6):marker_start]))


def _number(token: str):
    token = token.strip()
    if re.fullmatch(r"[-+]?\d+", token):
        return int(token)
    if re.fullmatch(r"[-+]?\d+\.\d+", token):
        try:
            return float(Decimal(token))
        except InvalidOperation:
            return None
    return parse_ordinal(token)


def proposals(text: str) -> Iterator[dict[str, object]]:
    for claim_type, markers, rule in (
        ("alias", ALIAS, "DETERMINISTIC_ALIAS_MARKER"),
        ("defeats", DEFEATS, "DETERMINISTIC_DEFEAT_MARKER"),
        ("located_in", LOCATED, "DETERMINISTIC_LOCATION_MARKER"),
    ):
        for start, end, _ in _markers(text, markers):
            subject, object_value = _left(text[:start]), _right(text[end:])
            if subject and object_value:
                yield dict(claim_type=claim_type, subject=subject, object=object_value, value=None, unit="", polarity=not _negated(text, start), rule=rule, trigger_start=start, trigger_end=end)
    for start, end, marker in _markers(text, (*PERMIT_NEG, *PERMIT_POS)):
        action = _action(text[end:])
        if action:
            yield dict(claim_type="permission", subject=_left(text[:start]), object=action, value=None, unit="", polarity=marker not in PERMIT_NEG, rule="DETERMINISTIC_PERMISSION_MARKER", trigger_start=start, trigger_end=end)
    for start, end, _ in _markers(text, COUNT):
        subject = _left(text[:start])
        match = _NUMBER_RE.search(text[end:end + 32])
        if not subject or not match:
            continue
        value = _number(match.group(0))
        if value is None:
            continue
        tail = text[end + match.end():]
        unit_match = re.match(r"\s*([A-Za-z\u3400-\u9fff]{0,12})", tail)
        yield dict(claim_type="count", subject=subject, object="", value=value, unit="" if not unit_match else unit_match.group(1), polarity=not _negated(text, start), rule="DETERMINISTIC_COUNT_CUE", trigger_start=start, trigger_end=end)
    for start, end, _ in _markers(text, DATE):
        subject = _left(text[:start])
        match = _DATE_RE.search(text[end:end + 32])
        if subject and match:
            yield dict(claim_type="date", subject=subject, object="", value=match.group(0), unit="", polarity=not _negated(text, start), rule="DETERMINISTIC_DATE_CUE", trigger_start=start, trigger_end=end)
