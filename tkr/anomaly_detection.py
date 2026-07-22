"""Phase 9.4 conservative anomaly and corpus-contamination candidates."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import io
import math
from os import PathLike
from pathlib import Path
import re
from typing import Final, Iterable
import unicodedata

from .encoding_inspection import EncodingInspectionError, inspect_source_encoding
from .hashing import DEFAULT_BLOCK_SIZE, HashingError, sha256_file

ANOMALY_INSPECTION_SCHEMA_VERSION: Final = "tkr-anomaly-inspection-v2"
ANOMALY_DETECTOR_VERSION: Final = "5.9.0-phase9.4-final"
OFFSET_BASIS: Final = "decoded_text_without_external_bom"
_BOMS: Final = {"utf-8": b"\xef\xbb\xbf", "utf-16-le": b"\xff\xfe", "utf-16-be": b"\xfe\xff"}
_WEB: Final = (
    ("HTML_TAG", re.compile(r"</?[A-Za-z][^>]{0,200}>", re.I)),
    ("URL_OR_DOMAIN", re.compile(r"(?:https?://|www\.|[A-Za-z0-9-]+\.(?:com|cn|net|org)\b)", re.I)),
    ("WEB_PROMPT", re.compile(r"未完待续|免费阅读|最新网址|请记住本站|手机阅读|章节错误|加入书签|下载本书|返回目录")),
)
_PARATEXT: Final = re.compile(r"^\s*(?:P\.?S\.?[:：]?|作者(?:有话说|的话)[:：]?|求(?:月票|推荐票|收藏|订阅)|感谢.{0,40}(?:打赏|订阅)|本章说|免费章[！!]?|作品相关[:：]?)", re.I)
_SEPARATOR_LINE: Final = re.compile(r"^\s*-{10,}\s*$")
_ENTITY: Final = re.compile(r"[\u3400-\u9fff]{1,6}(?:宗|门|宫|殿|城|国|朝|州|洲|界|山|谷|海|域|府|院|阁|军|盟|会|族|派)")
_REGISTERS: Final = {
    "modern": ("公司", "董事会", "经理", "电话", "邮件", "网络", "直播", "办公室", "警察", "汽车", "手机", "电脑", "合同", "记者"),
    "technology": ("机甲", "芯片", "系统", "数据", "程序", "量子", "飞船", "舰队", "服务器", "算法", "数据库", "机器人"),
    "xianxia": ("灵气", "真元", "丹田", "元婴", "渡劫", "宗门", "法器", "剑意", "功法", "灵石", "秘境", "金丹", "筑基", "神识"),
    "historical": ("皇帝", "太子", "将军", "朝廷", "陛下", "奏折", "城池", "骑兵", "军营", "王府", "丞相", "县令", "圣旨"),
}


class AnomalyInspectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MarkerGroup:
    name: str
    markers: tuple[str, ...]

    def __post_init__(self) -> None:
        name = self.name.strip()
        markers = tuple(x.strip() for x in self.markers if x.strip())
        if not name or not markers or len(set(markers)) != len(markers):
            raise AnomalyInspectionError("marker group requires a name and unique non-empty markers")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "markers", markers)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnomalyPolicy:
    max_line_characters: int = 20_000
    duplicate_min_characters: int = 80
    duplicate_min_line_distance: int = 20
    repeated_line_run: int = 3
    script_shift_min_characters: int = 80
    script_shift_delta: float = 0.55
    marker_min_total: int = 3
    marker_min_groups: int = 2
    max_duplicate_fingerprints: int = 100_000
    max_findings: int = 10_000
    preview_characters: int = 160
    window_characters: int = 800
    window_stride: int = 800
    window_min_characters: int = 240
    same_language_min_cjk_ratio: float = 0.60
    same_language_max_cosine_similarity: float = 0.20
    same_language_min_entity_union: int = 4
    same_language_max_entity_jaccard: float = 0.15
    same_language_min_register_delta: float = 0.60
    same_language_min_sentence_length_ratio: float = 2.8
    same_language_min_signals: int = 2
    mosaic_min_body_paragraphs: int = 7
    mosaic_max_boundary_paragraphs: int = 9
    mosaic_min_suffix_paragraphs: int = 6
    mosaic_max_block_characters: int = 100_000
    mosaic_min_candidate_suffix_characters: int = 700
    mosaic_min_template_suffix_characters: int = 300
    mosaic_max_candidate_suffix_characters: int = 3_000

    def __post_init__(self) -> None:
        positive = (
            self.max_line_characters, self.duplicate_min_characters,
            self.duplicate_min_line_distance, self.repeated_line_run,
            self.script_shift_min_characters, self.marker_min_total,
            self.marker_min_groups, self.max_duplicate_fingerprints,
            self.max_findings, self.preview_characters, self.window_characters,
            self.window_stride, self.window_min_characters,
            self.same_language_min_entity_union, self.same_language_min_signals,
            self.mosaic_min_body_paragraphs, self.mosaic_max_boundary_paragraphs,
            self.mosaic_min_suffix_paragraphs, self.mosaic_max_block_characters,
            self.mosaic_min_candidate_suffix_characters, self.mosaic_min_template_suffix_characters,
            self.mosaic_max_candidate_suffix_characters,
        )
        if any(not isinstance(x, int) or isinstance(x, bool) or x <= 0 for x in positive):
            raise AnomalyInspectionError("integer policy values must be positive")
        if self.repeated_line_run < 2 or self.window_stride > self.window_characters or self.window_min_characters > self.window_characters:
            raise AnomalyInspectionError("invalid repeated-line or window policy")
        probabilities = (
            self.script_shift_delta, self.same_language_min_cjk_ratio,
            self.same_language_max_cosine_similarity, self.same_language_max_entity_jaccard,
            self.same_language_min_register_delta,
        )
        if any(not 0.0 <= float(x) <= 1.0 for x in probabilities) or self.same_language_min_sentence_length_ratio < 1.0:
            raise AnomalyInspectionError("invalid probability or ratio policy")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    finding_id: str
    rule_id: str
    category: str
    severity: str
    confidence: str
    recommended_action: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    evidence_sha256: str
    evidence_preview: str
    signals: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnomalyInspectionReport:
    schema_version: str
    detector_version: str
    source_id: str
    source_sha256: str
    size_bytes: int
    selected_encoding: str | None
    offset_basis: str
    scan_status: str
    scanned_character_count: int
    scanned_line_count: int
    window_count: int
    finding_count: int
    category_counts: dict[str, int]
    rule_counts: dict[str, int]
    recommended_action: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    policy: dict[str, object]
    marker_groups: tuple[dict[str, object], ...]
    findings: tuple[AnomalyFinding, ...]
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_freeze: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _Window:
    start: int
    end: int
    start_line: int
    end_line: int
    text: str
    cjk: float
    grams: Counter[str]
    entities: frozenset[str]
    registers: dict[str, float]
    mean_sentence: float


def _line_breaks(text: str) -> int:
    return text.count("\n") + text.count("\r") - text.count("\r\n")


def _strip_eol(text: str) -> str:
    return text[:-2] if text.endswith("\r\n") else text[:-1] if text.endswith(("\r", "\n")) else text


def _cjk_ratio(text: str) -> float:
    chars = [x for x in text if not x.isspace()]
    if not chars:
        return 0.0
    return sum(0x3400 <= ord(x) <= 0x9FFF for x in chars) / len(chars)


def _grams(text: str) -> Counter[str]:
    stream = "".join(x.casefold() for x in text if x.isalnum() or 0x3400 <= ord(x) <= 0x9FFF)
    return Counter(stream[i:i + 2] for i in range(max(0, len(stream) - 1)))


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 1.0
    numerator = sum(left[k] * right[k] for k in set(left) & set(right))
    denominator = math.sqrt(sum(x * x for x in left.values()) * sum(x * x for x in right.values()))
    return numerator / denominator if denominator else 0.0



@dataclass(frozen=True, slots=True)
class _Paragraph:
    start: int
    end: int
    text: str


def _paragraphs(text: str) -> tuple[_Paragraph, ...]:
    """Return non-empty blank-line-delimited paragraphs with exact local spans."""
    output: list[_Paragraph] = []
    paragraph_start: int | None = None
    cursor = 0
    for physical in text.splitlines(keepends=True):
        content = _strip_eol(physical)
        if content.strip():
            if paragraph_start is None:
                paragraph_start = cursor
        elif paragraph_start is not None:
            raw = text[paragraph_start:cursor]
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw.rstrip())
            if trailing > leading:
                output.append(_Paragraph(paragraph_start + leading, paragraph_start + trailing, raw[leading:trailing]))
            paragraph_start = None
        cursor += len(physical)
    if paragraph_start is not None:
        raw = text[paragraph_start:]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        if trailing > leading:
            output.append(_Paragraph(paragraph_start + leading, paragraph_start + trailing, raw[leading:trailing]))
    return tuple(output)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 1.0


def _mosaic_features(block_text: str, policy: AnomalyPolicy) -> dict[str, object] | None:
    """Measure early paragraph mosaic incoherence without using work-specific vocabulary."""
    paragraphs = _paragraphs(block_text)
    body = paragraphs[1:] if len(paragraphs) > 1 else ()
    if len(body) < policy.mosaic_min_body_paragraphs:
        return None
    candidates: list[dict[str, object]] = []
    upper = min(policy.mosaic_max_boundary_paragraphs + 1, len(body))
    for boundary_index in range(1, upper):
        before = body[:boundary_index]
        after = body[boundary_index:]
        if len(after) < policy.mosaic_min_suffix_paragraphs:
            continue
        first = after[:10]
        grams = [_grams(item.text) for item in first]
        adjacent = [_mosaic_cosine(grams[i], grams[i + 1]) for i in range(len(grams) - 1)]
        pairwise = [
            _mosaic_cosine(grams[i], grams[j])
            for i in range(len(grams))
            for j in range(i + 1, len(grams))
        ]
        gram_union = set().union(*(set(item) for item in grams)) if grams else set()
        repeated = {
            gram for gram in gram_union
            if sum(gram in item for item in grams) >= 2
        }
        document_frequency = Counter(gram for item in grams for gram in item)
        common_threshold = max(2, len(grams) // 2)
        common_grams = {
            gram for gram, count in document_frequency.items()
            if count >= common_threshold
        }
        residual = [
            Counter({gram: count for gram, count in item.items() if gram not in common_grams})
            for item in grams
        ]
        residual_pairwise = [
            _mosaic_cosine(residual[i], residual[j])
            for i in range(len(residual))
            for j in range(i + 1, len(residual))
        ]
        total_grams = sum(sum(item.values()) for item in grams)
        prefix = "".join(item.text for item in before[-4:])
        suffix_sample = "".join(item.text for item in first)
        candidates.append(
            {
                "boundary_index": boundary_index,
                "boundary": after[0].start,
                "post_chars": sum(len(item.text) for item in after),
                "post_paragraphs": len(after),
                "prepost": _mosaic_cosine(_grams(prefix), _grams(suffix_sample)),
                "adjacent": _mean(adjacent),
                "pairwise": _mean(pairwise),
                "residual_pairwise": _mean(residual_pairwise),
                "type_token_ratio": len(gram_union) / total_grams if total_grams else 0.0,
                "repetition": len(repeated) / len(gram_union) if gram_union else 1.0,
            }
        )
    if not candidates:
        return None
    classification_best = min(
        candidates,
        key=lambda row: (
            float(row["adjacent"]) + float(row["pairwise"]) + float(row["repetition"]),
            int(row["boundary"]),
        ),
    )
    boundary_best = min(
        candidates,
        key=lambda row: (
            float(row["prepost"]) + float(row["pairwise"])
            + float(row["adjacent"]) + float(row["repetition"]),
            int(row["boundary"]),
        ),
    )
    min_pairwise = min(float(row["pairwise"]) for row in candidates)
    block_length = len(block_text) - block_text.count("\r\n")
    branch_a = (
        min_pairwise <= 0.00876699574291706
        and block_length <= 2415
        and float(classification_best["repetition"]) <= 0.03199544735252857
        and float(classification_best["prepost"]) <= 0.08747648820281029
    )
    branch_b = (
        min_pairwise > 0.00876699574291706
        and float(classification_best["adjacent"]) <= 0.010007602628320456
        and float(classification_best["prepost"]) <= 0.02134677767753601
        and int(classification_best["post_chars"]) <= policy.mosaic_max_candidate_suffix_characters
    )
    template_rows = [
        row for row in candidates
        if 0.40 <= float(row["type_token_ratio"]) <= 0.75
        and float(row["residual_pairwise"]) <= 0.01
        and int(row["post_paragraphs"]) >= 14
        and policy.mosaic_min_template_suffix_characters <= int(row["post_chars"])
        <= policy.mosaic_max_candidate_suffix_characters
    ]
    template_best = min(
        template_rows,
        key=lambda row: (
            float(row["residual_pairwise"]),
            float(row["prepost"]),
            int(row["boundary"]),
        ),
    ) if template_rows else None
    if template_best is not None:
        boundary_best = template_best
        classification_best = template_best
        classifier_branch = "template_resistant_mosaic"
    elif branch_a or branch_b:
        if (
            int(boundary_best["post_paragraphs"]) < 14
            or int(boundary_best["post_chars"]) < policy.mosaic_min_candidate_suffix_characters
        ):
            return None
        classifier_branch = "dense_mosaic" if branch_a else "abrupt_mosaic"
    else:
        return None
    return {
        **boundary_best,
        "classification_prepost": classification_best["prepost"],
        "classification_adjacent": classification_best["adjacent"],
        "classification_pairwise": classification_best["pairwise"],
        "classification_residual_pairwise": classification_best["residual_pairwise"],
        "classification_type_token_ratio": classification_best["type_token_ratio"],
        "classification_repetition": classification_best["repetition"],
        "min_pairwise": min_pairwise,
        "block_length": block_length,
        "classifier_branch": classifier_branch,
    }


def _mosaic_finding(source_hash: str, block_text: str, block_start: int, block_line: int,
                    policy: AnomalyPolicy) -> AnomalyFinding | None:
    if len(block_text) > policy.mosaic_max_block_characters:
        return None
    features = _mosaic_features(block_text, policy)
    if features is None:
        return None
    boundary = int(features["boundary"])
    evidence = block_text[boundary:]
    if not evidence:
        return None
    start = block_start + boundary
    start_line = block_line + _line_breaks(block_text[:boundary])
    end_line = block_line + _line_breaks(block_text)
    signals = (
        "detector=source_adaptive_paragraph_mosaic",
        f"classifier_branch={features['classifier_branch']}",
        f"boundary_paragraph={features['boundary_index']}",
        f"min_pairwise_cosine={float(features['min_pairwise']):.6f}",
        f"prefix_suffix_cosine={float(features['classification_prepost']):.6f}",
        f"adjacent_cosine={float(features['classification_adjacent']):.6f}",
        f"residual_pairwise_cosine={float(features['classification_residual_pairwise']):.6f}",
        f"type_token_ratio={float(features['classification_type_token_ratio']):.6f}",
        f"repeated_gram_ratio={float(features['classification_repetition']):.6f}",
        f"suffix_paragraphs={features['post_paragraphs']}",
        f"suffix_characters={features['post_chars']}",
    )
    return _finding(
        source_hash,
        "SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE",
        "contamination_candidate",
        "medium",
        "high",
        "manual_cross_work_boundary_review",
        start,
        block_start + len(block_text),
        start_line,
        end_line,
        evidence,
        policy.preview_characters,
        signals,
    )


def _mosaic_cosine(left: Counter[str], right: Counter[str]) -> float:
    # Empty or ultra-short paragraph samples carry no similarity evidence.
    if not left or not right:
        return 0.0
    return _cosine(left, right)


def _registers(text: str) -> dict[str, float]:
    counts = {name: sum(text.count(x) for x in words) for name, words in _REGISTERS.items()}
    total = sum(counts.values())
    return {name: (count / total if total else 0.0) for name, count in counts.items()}


def _window(text: str, start: int, line: int) -> _Window:
    sentences = [x for x in re.split(r"[。！？!?]+", text) if x.strip()]
    return _Window(
        start, start + len(text), line, max(line, line + _line_breaks(text)), text,
        _cjk_ratio(text), _grams(text), frozenset(_ENTITY.findall(text)),
        _registers(text), (sum(map(len, sentences)) / len(sentences)) if sentences else float(len(text)),
    )


def _preview(text: str, limit: int) -> str:
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _finding(source_hash: str, rule: str, category: str, severity: str, confidence: str,
             action: str, start: int, end: int, start_line: int, end_line: int,
             evidence: str, preview: int, signals: Iterable[str] = ()) -> AnomalyFinding:
    evidence_hash = sha256(evidence.encode()).hexdigest()
    identity = "\0".join((source_hash, rule, str(start), str(end), evidence_hash)).encode()
    return AnomalyFinding(
        f"finding_sha256_{sha256(identity).hexdigest()}", rule, category, severity,
        confidence, action, start, end, start_line, end_line, evidence_hash,
        _preview(evidence, preview), tuple(signals),
    )


def _shift_signals(previous: _Window, current: _Window, policy: AnomalyPolicy) -> tuple[str, ...]:
    if min(previous.cjk, current.cjk) < policy.same_language_min_cjk_ratio:
        return ()
    signals: list[str] = []
    votes = 0
    lexical = _cosine(previous.grams, current.grams)
    if lexical <= policy.same_language_max_cosine_similarity:
        signals.append(f"lexical_cosine={lexical:.3f}")
        votes += 1
    union = previous.entities | current.entities
    jaccard = len(previous.entities & current.entities) / len(union) if union else 1.0
    if previous.entities and current.entities and len(union) >= policy.same_language_min_entity_union and jaccard <= policy.same_language_max_entity_jaccard:
        # Entity turnover is one signal. Union size is supporting metadata, not a second vote.
        signals += (f"entity_jaccard={jaccard:.3f}", f"entity_union={len(union)}")
        votes += 1
    old = max(previous.registers, key=previous.registers.get)
    new = max(current.registers, key=current.registers.get)
    if old != new and previous.registers[old] >= policy.same_language_min_register_delta and current.registers[new] >= policy.same_language_min_register_delta:
        signals.append(f"register={old}->{new}")
        votes += 1
    ratio = max(previous.mean_sentence, current.mean_sentence) / max(1.0, min(previous.mean_sentence, current.mean_sentence))
    if ratio >= policy.same_language_min_sentence_length_ratio:
        signals.append(f"sentence_length_ratio={ratio:.3f}")
        votes += 1
    if votes < policy.same_language_min_signals:
        return ()
    return (f"previous_span={previous.start}-{previous.end}", f"previous_lines={previous.start_line}-{previous.end_line}", *signals)


def _blocked(report, policy: AnomalyPolicy, groups: tuple[MarkerGroup, ...]) -> AnomalyInspectionReport:
    return AnomalyInspectionReport(
        ANOMALY_INSPECTION_SCHEMA_VERSION, ANOMALY_DETECTOR_VERSION, report.source_id,
        report.source_sha256, report.size_bytes, report.selected_encoding, OFFSET_BASIS,
        "blocked", 0, 0, 0, 0, {}, {}, "resolve_source_blockers",
        tuple(dict.fromkeys((*report.blockers, "SOURCE_NOT_STRICTLY_DECODABLE_FOR_ANOMALY_SCAN"))),
        tuple(report.warnings), policy.to_dict(), tuple(x.to_dict() for x in groups), (),
    )


def inspect_source_anomalies(path: str | PathLike[str], *, policy: AnomalyPolicy | None = None,
                             marker_groups: Iterable[MarkerGroup] = (),
                             block_size: int = DEFAULT_BLOCK_SIZE) -> AnomalyInspectionReport:
    policy = policy or AnomalyPolicy()
    groups = tuple(marker_groups)
    if len({x.name for x in groups}) != len(groups):
        raise AnomalyInspectionError("marker group names must be unique")
    try:
        encoding = inspect_source_encoding(path, block_size=block_size)
    except EncodingInspectionError as exc:
        raise AnomalyInspectionError(str(exc)) from exc
    if not encoding.strict_decode_passed or encoding.selected_encoding is None:
        return _blocked(encoding, policy, groups)

    source = Path(path)
    findings: list[AnomalyFinding] = []
    warnings = list(encoding.warnings)
    duplicates: dict[str, tuple[int, int, int]] = {}
    finding_limit = duplicate_limit = False
    previous_line = ""
    repeated = 0
    previous_script: tuple[float, float, int] | None = None
    chars = lines = windows = 0
    buffer = ""
    buffer_start = 0
    buffer_line = 1
    previous_window: _Window | None = None
    last_window_start = -1
    pending_window_findings: list[AnomalyFinding] = []
    block_parts: list[str] = []
    block_start = 0
    block_line = 1
    separator_seen = False

    def add(item: AnomalyFinding) -> None:
        nonlocal finding_limit
        if len(findings) >= policy.max_findings:
            finding_limit = True
        else:
            findings.append(item)

    def add_rule(rule: str, category: str, severity: str, confidence: str, action: str,
                 start: int, end: int, line: int, evidence: str,
                 signals: Iterable[str] = (), end_line: int | None = None) -> None:
        add(_finding(encoding.source_sha256, rule, category, severity, confidence, action,
                     start, end, line, end_line or line, evidence,
                     policy.preview_characters, signals))

    def process_window(text: str, start: int, line: int) -> None:
        nonlocal windows, previous_window, last_window_start
        if len(text) < policy.window_min_characters or start == last_window_start:
            return
        current = _window(text, start, line)
        windows += 1
        last_window_start = start
        if previous_window is None:
            previous_window = current
        elif current.start >= previous_window.end:
            signals = _shift_signals(previous_window, current, policy)
            if signals:
                pending_window_findings.append(
                    _finding(encoding.source_sha256, "SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE",
                             "contamination_candidate", "medium", "medium",
                             "manual_cross_work_boundary_review", current.start, current.end,
                             current.start_line, current.end_line, current.text,
                             policy.preview_characters, signals)
                )
            previous_window = current

    prefix = _BOMS.get(encoding.bom, b"")
    try:
        with source.open("rb") as raw:
            if prefix and raw.read(len(prefix)) != prefix:
                raise AnomalyInspectionError("source BOM changed after encoding inspection")
            with io.TextIOWrapper(raw, encoding=encoding.selected_encoding, errors="strict", newline="") as stream:
                for line_no, physical in enumerate(stream, 1):
                    lines = line_no
                    start = chars
                    chars += len(physical)
                    content = _strip_eol(physical)
                    end = start + len(content)
                    buffer += physical

                    if _SEPARATOR_LINE.fullmatch(content):
                        separator_seen = True
                        block_text = "".join(block_parts)
                        item = _mosaic_finding(encoding.source_sha256, block_text, block_start, block_line, policy)
                        if item is not None:
                            add(item)
                        elif len(block_text) > policy.mosaic_max_block_characters:
                            warnings.append("MOSAIC_BLOCK_LIMIT_REACHED")
                        block_parts = []
                        block_start = chars
                        block_line = line_no + 1
                    else:
                        block_parts.append(physical)

                    for offset, character in enumerate(content):
                        code = ord(character)
                        rule = None
                        if character == "\ufffd": rule = "UNICODE_REPLACEMENT_CHARACTER"
                        elif character == "\x00": rule = "UNICODE_NUL_CHARACTER"
                        elif character == "\ufeff": rule = "UNICODE_EMBEDDED_BOM"
                        elif 0xFDD0 <= code <= 0xFDEF or (code & 0xFFFF) in {0xFFFE, 0xFFFF}: rule = "UNICODE_NONCHARACTER"
                        elif unicodedata.category(character) == "Cc" and character not in "\t\f": rule = "UNICODE_CONTROL_CHARACTER"
                        if rule:
                            add_rule(rule, "text_anomaly", "high", "high", "inspect_exact_span",
                                     start + offset, start + offset + 1, line_no, character,
                                     (f"U+{code:04X}",))

                    if len(content) > policy.max_line_characters:
                        add_rule("LINE_EXCEEDS_LENGTH_LIMIT", "structural_anomaly", "medium",
                                 "high", "inspect_line_boundary", start, end, line_no,
                                 content, (f"length={len(content)}",))
                    for signal, pattern in _WEB:
                        for match in pattern.finditer(content):
                            add_rule("WEB_RESIDUE_CANDIDATE", "contamination_candidate", "medium",
                                     "high", "review_and_optionally_exclude_span",
                                     start + match.start(), start + match.end(), line_no,
                                     match.group(), (signal,))
                    meta = _PARATEXT.search(content)
                    if meta:
                        add_rule("AUTHOR_META_OR_PARATEXT_CANDIDATE", "paratext_candidate", "low",
                                 "medium", "classify_before_canonical_indexing", start, end,
                                 line_no, content, (meta.group().strip(),))

                    folded = content.casefold()
                    matched_groups, markers = [], set()
                    for group in groups:
                        hits = {x for x in group.markers if x.casefold() in folded}
                        if hits:
                            matched_groups.append(group.name); markers.update(hits)
                    if len(markers) >= policy.marker_min_total and len(matched_groups) >= policy.marker_min_groups:
                        add_rule("CUSTOM_MARKER_CLUSTER_CANDIDATE", "contamination_candidate",
                                 "medium", "medium", "manual_cross_work_review", start, end,
                                 line_no, content, (f"groups={','.join(matched_groups)}", *[f"marker={x}" for x in sorted(markers)]))

                    normalized = " ".join(content.split())
                    repeated = repeated + 1 if normalized and normalized == previous_line else (1 if normalized else 0)
                    previous_line = normalized
                    if repeated == policy.repeated_line_run:
                        add_rule("REPEATED_LINE_RUN_CANDIDATE", "contamination_candidate",
                                 "medium", "high", "inspect_repeated_span", start, end,
                                 line_no, content, (f"run_length={repeated}",))
                    if len(normalized) >= policy.duplicate_min_characters:
                        digest = sha256(normalized.encode()).hexdigest()
                        first = duplicates.get(digest)
                        if first and line_no - first[0] >= policy.duplicate_min_line_distance:
                            add_rule("DISTANT_DUPLICATE_PASSAGE_CANDIDATE", "contamination_candidate",
                                     "medium", "high", "compare_duplicate_occurrences",
                                     start, end, line_no, content,
                                     (f"first_line={first[0]}", f"first_span={first[1]}-{first[2]}"))
                        elif not first:
                            if len(duplicates) < policy.max_duplicate_fingerprints:
                                duplicates[digest] = (line_no, start, end)
                            else:
                                duplicate_limit = True

                    if len(content) >= policy.script_shift_min_characters:
                        cjk = _cjk_ratio(content)
                        ascii_ratio = sum(x.isascii() and x.isalpha() for x in content) / max(1, len(content))
                        if previous_script and previous_script[2] == line_no - 1 and abs(cjk - previous_script[0]) >= policy.script_shift_delta and abs(ascii_ratio - previous_script[1]) >= policy.script_shift_delta:
                            add_rule("ABRUPT_SCRIPT_PROFILE_SHIFT_CANDIDATE", "contamination_candidate",
                                     "low", "medium", "inspect_local_transition", start, end,
                                     line_no, content, (f"previous_line={previous_script[2]}",))
                        previous_script = (cjk, ascii_ratio, line_no)
                    else:
                        previous_script = None

                    while len(buffer) >= policy.window_characters:
                        process_window(buffer[:policy.window_characters], buffer_start, buffer_line)
                        dropped = buffer[:policy.window_stride]
                        buffer = buffer[policy.window_stride:]
                        buffer_start += len(dropped)
                        buffer_line += _line_breaks(dropped)
                if len(buffer) >= policy.window_min_characters:
                    process_window(buffer, buffer_start, buffer_line)
                if separator_seen:
                    block_text = "".join(block_parts)
                    item = _mosaic_finding(encoding.source_sha256, block_text, block_start, block_line, policy)
                    if item is not None:
                        add(item)
                    elif len(block_text) > policy.mosaic_max_block_characters:
                        warnings.append("MOSAIC_BLOCK_LIMIT_REACHED")
                else:
                    for item in pending_window_findings:
                        add(item)
    except (OSError, UnicodeError) as exc:
        raise AnomalyInspectionError(f"anomaly scan failed: {exc}") from exc

    try:
        if sha256_file(source, block_size=block_size) != encoding.source_sha256:
            raise AnomalyInspectionError("source changed during anomaly inspection")
    except HashingError as exc:
        raise AnomalyInspectionError(str(exc)) from exc

    if finding_limit: warnings.append("FINDING_LIMIT_REACHED")
    if duplicate_limit: warnings.append("DUPLICATE_FINGERPRINT_LIMIT_REACHED")
    findings.sort(key=lambda x: (x.start_char, x.end_char, x.rule_id, x.finding_id))
    categories = Counter(x.category for x in findings)
    rules = Counter(x.rule_id for x in findings)
    action = "review_candidates_incomplete_due_to_limit" if finding_limit else "review_candidates" if findings else "review_source_warnings" if warnings else "no_candidates_detected"
    return AnomalyInspectionReport(
        ANOMALY_INSPECTION_SCHEMA_VERSION, ANOMALY_DETECTOR_VERSION, encoding.source_id,
        encoding.source_sha256, encoding.size_bytes, encoding.selected_encoding, OFFSET_BASIS,
        "completed", chars, lines, windows, len(findings), dict(sorted(categories.items())),
        dict(sorted(rules.items())), action, (), tuple(dict.fromkeys(warnings)),
        policy.to_dict(), tuple(x.to_dict() for x in groups), tuple(findings),
    )
