"""Conservative lexical rules for the six supported Claim predicates."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Iterator, Sequence

from .structure_models import parse_ordinal

_ENTITY_RE = re.compile(r"[A-Za-z0-9_\-\u3400-\u9fff·]{1,48}")
_DATE_RE = re.compile(r"\d{4}(?:年|[-/.])\d{1,2}(?:(?:月|[-/.])\d{1,2}日?)?")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?|[零〇○一二两兩三四五六七八九十百千万萬亿億]+")
_COUNT_UNIT_RE = re.compile(r"\s*(名|人|位|个|條|条|项|項|处|處|篇|变|變|路|块|塊|层|層|出|事|式|次|魂|道|招|场|場|柄|枚|本|卷|座|家|杆|桿|重|妖|门|門|件|种|種)")
ALIAS = ("更名为", "改称", "又称", "亦称", "也称", "别名为", "别名是", "别名", "原名为", "原名是", "原名", "旧称")
DEFEATS = ("击败", "战胜", "打败", "击溃")
LOCATED = ("坐落于", "位于", "地处", "设于")
# Automatic publication only uses explicit normative permission cues. Broad
# ability/modal words such as ``可以``/``能够``/``不能`` are retained for later
# model review, but are too polysemous in literary prose for canonical facts.
PERMIT_POS = ("获准", "允许", "准许", "有权")
PERMIT_NEG = ("不允许", "禁止", "无权")
COUNT = ("数量为", "数目为", "一共有", "总共有", "共有", "共计", "总计", "合计", "总共", "一共", "共分", "共")
DATE = ("出生于", "发生于", "开始于", "始于", "截至", "日期为", "时间为")
AMBIGUOUS_CUE_RE = re.compile(r"(?:同一人|身份|属于|担任|拥有|失去|成为|来自|前往|效忠|支持|反对|死亡|失踪|可能|似乎|传闻|怀疑|认为)")
_NEGATION_RE = re.compile(r"(?:并未|没有|不曾|从未|并非|不是|未曾|未能|未|不)")
_LEFT_CUES = (
    "在昨日", "在当日", "于昨日", "于当日", "后来", "随后", "最终", "曾经", "此前", "当时", "已经", "曾",
    "计划", "准备", "将要", "即将", "预计", "并未", "没有", "不曾", "从未", "未曾", "未能", "未", "不",
    "自然", "绝", "决", "也", "却", "改制",
)
_RIGHT_STOPS = ("随后", "然后", "后来", "并且", "而后", "之后", "从此", "当场", "同时")


_FUNCTION_TERMS = frozenset({
    "但", "又", "因", "因此", "其实", "同时", "随后", "然后", "依然", "仍",
    "能", "可", "总", "容", "并", "且", "终", "少", "四字", "之后", "地",
    "已", "所以", "连接", "却",
})
_BAD_TERM_PREFIXES = (
    "但", "又", "因", "因此", "其实", "同时", "随后", "然后", "依然", "已经被",
    "凭着", "助", "众妖见", "让", "如何", "为何", "看来", "仿佛", "总之",
    "斗法", "再加上", "便能", "就是", "为了", "所以", "现在", "想在", "入门不过",
    "没", "便算默认", "俨然如",
)
_BAD_TERM_SUFFIXES = (
    "为何", "虽", "已经被", "可算是", "看来", "仿佛", "之间", "之时", "以来",
    "见", "间", "后", "过", "能", "可", "便", "就", "仍", "又", "因", "但",
)
_BAD_OBJECT_PREFIXES = ("的", "了", "过的", "负", "不上", "不得不", "地", "得上")
_BAD_ACTION_EXACT = frozenset({"了", "啊", "哦", "好死", "其解", "大意", "形容"})
_BAD_ACTION_SUFFIXES = ("吧", "吗", "呢", "啊", "哦", "了")


def _relation_term(value: str, *, object_side: bool = False) -> bool:
    token = value.strip()
    if not token or len(token) > 16 or token in _FUNCTION_TERMS:
        return False
    if any(token.startswith(prefix) for prefix in _BAD_TERM_PREFIXES):
        return False
    if any(token.endswith(suffix) for suffix in _BAD_TERM_SUFFIXES):
        return False
    if object_side and any(token.startswith(prefix) for prefix in _BAD_OBJECT_PREFIXES):
        return False
    # A deterministic relation endpoint must be noun-like rather than a whole
    # clause. These high-frequency particles/verbs are strong clause signals.
    if re.search(r"(?:为何|怎么|什么|可以|不能|不得|能够|已经|成为|用这|凭着|助|见|听你|让他|之内|时候|非但|机会|被|轻易|自觉|目的|曾以|数量|之不武|所剩不多)", token):
        return False
    return True


def _count_subject(value: str, marker: str) -> str:
    token = value.strip()
    for prefix in ("其实", "便见"):
        if token.startswith(prefix):
            token = token[len(prefix):].strip()
    for suffix in ("虽", "的"):
        if token.endswith(suffix):
            token = token[:-len(suffix)].strip()
    if "绝学" in token:
        # Collapse descriptive ownership/rank prefixes so conflicting counts
        # for the same named work enter one identity scope.
        named = token.rsplit("绝学", 1)[1].strip()
        if named:
            token = named
    if not token or len(token) > 24 or token in {"已", "所以", "之后", "算上汤水"}:
        return ""
    if marker == "共" and len(token) == 1:
        return ""
    if token.startswith(("原本", "所以", "之后")):
        return ""
    return token


def _permission_terms(subject: str, action: str) -> bool:
    actor = subject.strip()
    act = action.strip()
    if not _relation_term(actor) or not (2 <= len(act) <= 24):
        return False
    if act in _BAD_ACTION_EXACT or any(act.endswith(suffix) for suffix in _BAD_ACTION_SUFFIXES):
        return False
    if act.startswith(("势", "不准", "了", "啊", "哦")):
        return False
    if re.search(r"(?:为何|什么时候|看来|仿佛|总不能|少不得|容不得|终不得|并不能)", actor):
        return False
    return True

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
            if _relation_term(subject) and _relation_term(object_value, object_side=True):
                yield dict(claim_type=claim_type, subject=subject, object=object_value, value=None, unit="", polarity=not _negated(text, start), rule=rule, trigger_start=start, trigger_end=end)
    for start, end, marker in _markers(text, (*PERMIT_NEG, *PERMIT_POS)):
        action = _action(text[end:])
        subject = _left(text[:start])
        if _permission_terms(subject, action):
            yield dict(claim_type="permission", subject=subject, object=action, value=None, unit="", polarity=marker not in PERMIT_NEG, rule="DETERMINISTIC_PERMISSION_MARKER", trigger_start=start, trigger_end=end)
    for start, end, marker in _markers(text, COUNT):
        subject = _count_subject(_left(text[:start]), marker)
        # Count values must begin immediately after the cue. This preserves
        # valid forms such as ``共十八路`` while rejecting compounds such as
        # ``共乘一船``/``共鸣`` whose later digits are unrelated.
        match = re.match(r"\s*(?:" + _NUMBER_RE.pattern + r")", text[end:end + 32])
        if not subject or not match:
            continue
        if marker == "共" and re.search(r"[，,、]", text[:start]):
            # In enumerations, the token immediately before ``共`` is often
            # the final list item rather than the collection being counted.
            continue
        value = _number(match.group(0))
        if value is None:
            continue
        tail = text[end + match.end():]
        unit_match = _COUNT_UNIT_RE.match(tail)
        yield dict(claim_type="count", subject=subject, object="", value=value, unit="" if not unit_match else unit_match.group(1), polarity=not _negated(text, start), rule="DETERMINISTIC_COUNT_CUE", trigger_start=start, trigger_end=end)
    for start, end, _ in _markers(text, DATE):
        subject = _left(text[:start])
        match = _DATE_RE.search(text[end:end + 32])
        if subject and match:
            yield dict(claim_type="date", subject=subject, object="", value=match.group(0), unit="", polarity=not _negated(text, start), rule="DETERMINISTIC_DATE_CUE", trigger_start=start, trigger_end=end)
