"""Conservative lexical rules for the six supported Claim predicates."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Iterator, Sequence

from .structure_models import parse_ordinal

_ENTITY_RE = re.compile(r"[A-Za-z0-9_\-\u3400-\u9fff·]{1,48}")
_DATE_RE = re.compile(r"\d{4}(?:年|[-/.])\d{1,2}(?:(?:月|[-/.])\d{1,2}日?)?")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?|[雰〇○一二两兩三四五六七八九十百千万萬亿億]+")
_COUNT_UNIT_RE = re.compile(r"\s*(名|人|位|个|條|条|项|項|处|處|篇|变|變|路|块|塊|层|層|出|事|式|次|魃|道|招|场|場|柄|枚|本|卷|座|家|杆|桿|重|妖|门|門|件|种|種)")
ALIAS = ("又称之为", "更名为", "改称", "又称", "亦称", "也称", "别名为", "别名是", "别名", "原名为", "原名是", "原名", "旧称")
DEFEATS = ("击败", "战胜", "打败", "击溃")
LOCATED = ("坐落于", "位于", "地处", "设于")
# Automatic publication only uses explicit normative permission cues. Broad
# ability/modal words such as ``可以``/``能够``/``不能`` are retained for later
# model review, but are too polysemous in literary prose for canonical facts.
PERMIT_POS = ("有权利", "获准", "允许", "准许")
PERMIT_NEG = ("不允许", "禁止", "无权")
COUNT = ("数量为", "数目为", "一共有", "总共有", "共有", "共计", "总计", "合计", "总共", "一共", "共分", "共")
DATE = ("出生于", "发生于", "开始于", "始于", "截至", "日期为", "时间为")
AMBIGUOUS_CUE_RE = re.compile(r"(?:同一人|身份|属于|担任|拥有|失去|成为|来自|前往|效忠|支持|反对|死亡|失踪|可能|似乎|传闻|怀疋|认为)")
_NEGATION_RE = re.compile(r"(?:并未|没有|不曟|从未|并非|不是|未曾|未能|未|不)")
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
    "见", "间", "后", "过", "能", "可", "便", "就", "仍", "又", "但",
)
_BAD_OBJECT_PREFIXES = ("的", "了", "过的", "负", "不上", "不得不", "地", "得上")
_BAD_ACTION_EXACT = frozenset({"了", "啊", "哦", "好死", "其解", "大意", "形容"})
_BAD_ACTION_SUFFIXES = ("吧", "吗", "呢", "啊", "哦", "了")

_PRONOUN_OR_FUNCTION_ENDPOINTS = frozenset({
    "我", "我们", "咱们", "你", "你们", "他", "他们", "她", "她们", "它", "它们",
    "其", "此", "这", "那", "谁", "有人", "众人", "人们", "大家", "自己", "对方",
    "则", "和", "与", "及", "并", "且", "或", "而", "在", "于", "从", "向", "往",
})
_BAD_ENDPOINT_PREFIXES = (
    "在", "于", "从", "向", "往", "对", "与", "和", "及", "则", "而", "若", "如果",
    "只要", "一旦", "假如", "倘若", "请", "请求", "恳请", "希望", "想要", "试图", "企图",
)
_DEFEAT_NONFACT_LEFT_RE = re.compile(
    r"(?:有希望|希望|想要|打算|计划|准备|将要|即将|预计|可以|能够|能|足以|有能力|"
    r"若|如果|只要|一旦|假如|倘若|或许|可能|也许|未必|试图|企图|欲|要)"
    r"[^。！？!?；;，,]{0,16}$"
)
_PERMISSION_REQUEST_LEFT_RE = re.compile(
    r"(?:请|请求|恳请|求你|希望|能否|是否|可否|让我|让我们|准我|允许我)"
    r"[^。！？!?；;，,]{0,12}$"
)
_ALIAS_COMMAND_RE = re.compile(r"(?:不许|不准|禁止|不得|不要|别|莫).{0,12}(?:叫|称|喊|取名|起名|别名)")


def _relation_term(value: str, *, object_side: bool = False) -> bool:
    token = value.strip()
    if not token or len(token) > 16 or token in _FUNCTION_TERMS or token in _PRONOUN_OR_FUNCTION_ENDPOINTS:
        return False
    if any(token.startswith(prefix) for prefix in _BAD_ENDPOINT_PREFIXES):
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


def _negated(text: str, marker_start: int, marker_end: int | None = None) -> bool:
    before = text[max(0, marker_start - 8):marker_start]
    after = text[marker_end if marker_end is not None else marker_start: (marker_end if marker_end is not None else marker_start) + 4]
    return bool(_NEGATION_RE.search(before) or re.match(r"(?:不了|不得|不下|不赢|不能)", after))


def _normalized_relation_subject(value: str, claim_type: str) -> str:
    token = value.strip()
    if token.startswith("自从"):
        token = token[2:].strip()
    if token.startswith("这") and len(token) > 2:
        token = token[1:]
    if claim_type == "defeats":
        for suffix in ("连续", "再次", "亲手"):
            if token.endswith(suffix) and len(token) > len(suffix):
                token = token[:-len(suffix)]
    return token


def _relation_context_allowed(text: str, start: int, end: int, claim_type: str, marker: str) -> bool:
    left = text[:start].strip(" \t，,:：；;")
    right = text[end:].lstrip(" \t，,:：；;")
    if claim_type == "alias":
        if marker in {"原名", "原名为", "原名是"} and right.startswith("声"):
            return False
        if left.endswith("分") or right.startswith("赞"):
            return False
        if _ALIAS_COMMAND_RE.search(text) or re.search(r"(?:别|不要|不许|不准|禁止|不得).{0,8}$", left):
            return False
    if claim_type == "located_in":
        if marker == "地处" and right.startswith("理"):
            return False
        if left.endswith(("原本", "曾经", "此前")) or re.search(r"(?:后来|随后).{0,8}(?:迁|移|搬)", text[end:]):
            return False
    if claim_type == "defeats":
        # Preserve future, modal, hypothetical, and attempted defeat mentions as
        # auditable non-indexable candidates.  Discourse classification and claim
        # validation own the decision to keep them out of canonical knowledge.
        # Only hard-reject fragments that cannot provide a noun-like subject.
        if left.startswith(("从正面", "再一举", "我知道", "意味着")):
            return False
        if re.match(r"(?:不了|不得|不下|不能)", right):
            return True
    return True


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
        for start, end, marker in _markers(text, markers):
            if not _relation_context_allowed(text, start, end, claim_type, marker):
                continue
            subject = _normalized_relation_subject(_left(text[:start]), claim_type)
            right_text = text[end:]
            if claim_type == "alias" and right_text.lstrip().startswith("之为"):
                right_text = right_text.lstrip()[2:]
            object_value = _right(right_text)
            polarity = not _negated(text, start, end)
            if _relation_term(subject) and _relation_term(object_value, object_side=True):
                yield dict(claim_type=claim_type, subject=subject, object=object_value, value=None, unit="", polarity=polarity, rule=rule, trigger_start=start, trigger_end=end)
    for start, end, marker in _markers(text, (*PERMIT_NEG, *PERMIT_POS)):
        action = _action(text[end:])
        subject = _normalized_relation_subject(_left(text[:start]), "permission")
        left_context = text[:start].strip()
        if marker == "有权" and action.startswith("利"):
            continue
        if (
            left_context.startswith(("只有", "甚至"))
            or "这个身份" in left_context
            or left_context.endswith(("才", "都"))
            or _PERMISSION_REQUEST_LEFT_RE.search(left_context)
            or re.search(r"(?:请问|能否|是否|可否).{0,12}(?:允许|准许|获准|有权利)", text)
        ):
            continue
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
        number_token = match.group(0).strip()
        tail = text[end + match.end():]
        if tail.startswith(("几", "多")) or re.match(r"\s*(?:[^。！？!?]{0,3})半", tail):
            continue
        if re.fullmatch(r"[零〇○一二两兩三四五六七八九十百千万萬亿億]+", number_token) and re.search(r"[万萬亿億].+[一二两兩三四五六七八九]$", number_token):
            continue
        if subject.startswith(("顿时", "让", "失笑", "现在", "这次", "他又花费")) or "：" in text[:start][-12:]:
            continue
        value = _number(number_token)
        if value is None:
            continue
        unit_match = _COUNT_UNIT_RE.match(tail)
        yield dict(claim_type="count", subject=subject, object="", value=value, unit="" if not unit_match else unit_match.group(1), polarity=not _negated(text, start, end), rule="DETERMINISTIC_COUNT_CUE", trigger_start=start, trigger_end=end)
    for start, end, _ in _markers(text, DATE):
        subject = _left(text[:start])
        match = _DATE_RE.search(text[end:end + 32])
        if subject and match:
            yield dict(claim_type="date", subject=subject, object="", value=match.group(0), unit="", polarity=not _negated(text, start, end), rule="DETERMINISTIC_DATE_CUE", trigger_start=start, trigger_end=end)
