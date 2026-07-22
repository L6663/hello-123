"""Phase 9.4 conservative anomaly and contamination candidate detection.

The detector emits auditable review candidates. It does not decide that a source is
clean, contaminated, accepted, release-ready, or suitable for freezing.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import io
from os import PathLike
from pathlib import Path
import re
from typing import Final, Iterable
import unicodedata

from .encoding_inspection import EncodingInspectionError, inspect_source_encoding
from .hashing import DEFAULT_BLOCK_SIZE, HashingError, sha256_file

ANOMALY_INSPECTION_SCHEMA_VERSION: Final = "tkr-anomaly-inspection-v1"
ANOMALY_DETECTOR_VERSION: Final = "5.9.0-phase9.4"
OFFSET_BASIS: Final = "decoded_text_without_external_bom"

_BOM_PREFIX_BYTES: Final = {
    "utf-8": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
}

_WEB_PATTERNS: Final = (
    ("HTML_TAG", re.compile(r"</?[A-Za-z][^>]{0,200}>", re.IGNORECASE)),
    (
        "URL_OR_DOMAIN",
        re.compile(
            r"(?:https?://|www\.|(?:w|ｗ){3,}[.。]|"
            r"[A-Za-z0-9-]+\.(?:com|cn|net|org)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "WEB_READING_PROMPT",
        re.compile(
            r"未完待续|免费阅读|最新网址|请记住本站|手机阅读|章节错误|"
            r"加入书签|点击(?:下一页|阅读)|本章未完"
        ),
    ),
)

_PARATEXT_PATTERN: Final = re.compile(
    r"^\s*(?:P\.?S\.?[:：]?|作者(?:有话说|的话)[:：]?|"
    r"求(?:月票|推荐票|收藏|订阅)|感谢.{0,40}(?:打赏|订阅)|"
    r"本章说|免费章[！!]?|战力排行[！!]?)",
    re.IGNORECASE,
)


class AnomalyInspectionError(ValueError):
    """Raised when an anomaly scan cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class MarkerGroup:
    """Caller-supplied lexical markers used only to emit review candidates."""

    name: str
    markers: tuple[str, ...]

    def __post_init__(self) -> None:
        cleaned_name = self.name.strip()
        cleaned_markers = tuple(marker for marker in self.markers if marker)
        if not cleaned_name:
            raise AnomalyInspectionError("marker group name must not be empty")
        if not cleaned_markers:
            raise AnomalyInspectionError(
                f"marker group {cleaned_name!r} must contain a non-empty marker"
            )
        if len(set(cleaned_markers)) != len(cleaned_markers):
            raise AnomalyInspectionError(
                f"marker group {cleaned_name!r} contains duplicate markers"
            )
        object.__setattr__(self, "name", cleaned_name)
        object.__setattr__(self, "markers", cleaned_markers)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnomalyPolicy:
    """Deterministic thresholds for conservative candidate generation."""

    max_line_characters: int = 20_000
    duplicate_min_characters: int = 80
    duplicate_min_line_distance: int = 20
    repeated_line_run: int = 3
    script_shift_min_characters: int = 80
    script_shift_cjk_delta: float = 0.55
    script_shift_ascii_delta: float = 0.55
    marker_min_total: int = 3
    marker_min_groups: int = 2
    max_duplicate_fingerprints: int = 100_000
    max_findings: int = 10_000
    preview_characters: int = 160

    def __post_init__(self) -> None:
        integers = {
            "max_line_characters": self.max_line_characters,
            "duplicate_min_characters": self.duplicate_min_characters,
            "duplicate_min_line_distance": self.duplicate_min_line_distance,
            "repeated_line_run": self.repeated_line_run,
            "script_shift_min_characters": self.script_shift_min_characters,
            "marker_min_total": self.marker_min_total,
            "marker_min_groups": self.marker_min_groups,
            "max_duplicate_fingerprints": self.max_duplicate_fingerprints,
            "max_findings": self.max_findings,
            "preview_characters": self.preview_characters,
        }
        for name, value in integers.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise AnomalyInspectionError(f"{name} must be a positive integer")
        if self.repeated_line_run < 2:
            raise AnomalyInspectionError("repeated_line_run must be at least 2")
        for name, value in (
            ("script_shift_cjk_delta", self.script_shift_cjk_delta),
            ("script_shift_ascii_delta", self.script_shift_ascii_delta),
        ):
            if not 0.0 <= value <= 1.0:
                raise AnomalyInspectionError(f"{name} must be between 0 and 1")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    """One exact-span anomaly or contamination review candidate."""

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
    """Source-bound Phase 9.4 scan report."""

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
    finding_count: int
    category_counts: dict[str, int]
    rule_counts: dict[str, int]
    recommended_action: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    policy: dict[str, object]
    marker_groups: tuple[dict[str, object], ...]
    findings: tuple[AnomalyFinding, ...]
    project_acceptance_performed: bool
    may_accept_project: bool
    may_freeze: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _ScriptProfile:
    cjk_ratio: float
    ascii_alpha_ratio: float


@dataclass(frozen=True, slots=True)
class _SeenLine:
    line_number: int
    start_char: int
    end_char: int


def _is_noncharacter(codepoint: int) -> bool:
    return 0xFDD0 <= codepoint <= 0xFDEF or (codepoint & 0xFFFF) in {
        0xFFFE,
        0xFFFF,
    }


def _strip_line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\r", "\n")):
        return line[:-1]
    return line


def _normalized_line(text: str) -> str:
    return " ".join(text.split())


def _script_profile(text: str) -> _ScriptProfile:
    if not text:
        return _ScriptProfile(0.0, 0.0)
    cjk_count = 0
    ascii_alpha_count = 0
    for character in text:
        codepoint = ord(character)
        cjk_count += (
            0x3400 <= codepoint <= 0x4DBF
            or 0x4E00 <= codepoint <= 0x9FFF
            or 0xF900 <= codepoint <= 0xFAFF
        )
        ascii_alpha_count += character.isascii() and character.isalpha()
    length = len(text)
    return _ScriptProfile(cjk_count / length, ascii_alpha_count / length)


def _preview(text: str, limit: int) -> str:
    compact = text.replace("\r", "\\r").replace("\n", "\\n")
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _make_finding(
    *,
    source_sha256: str,
    rule_id: str,
    category: str,
    severity: str,
    confidence: str,
    recommended_action: str,
    start_char: int,
    end_char: int,
    start_line: int,
    end_line: int,
    evidence: str,
    preview_characters: int,
    signals: Iterable[str] = (),
) -> AnomalyFinding:
    evidence_digest = sha256(evidence.encode("utf-8")).hexdigest()
    identity = "\0".join(
        (
            source_sha256,
            rule_id,
            str(start_char),
            str(end_char),
            evidence_digest,
        )
    ).encode("utf-8")
    return AnomalyFinding(
        finding_id=f"finding_sha256_{sha256(identity).hexdigest()}",
        rule_id=rule_id,
        category=category,
        severity=severity,
        confidence=confidence,
        recommended_action=recommended_action,
        start_char=start_char,
        end_char=end_char,
        start_line=start_line,
        end_line=end_line,
        evidence_sha256=evidence_digest,
        evidence_preview=_preview(evidence, preview_characters),
        signals=tuple(signals),
    )


def _blocked_report(
    *,
    encoding_report,
    policy: AnomalyPolicy,
    marker_groups: tuple[MarkerGroup, ...],
    blocker: str,
) -> AnomalyInspectionReport:
    return AnomalyInspectionReport(
        schema_version=ANOMALY_INSPECTION_SCHEMA_VERSION,
        detector_version=ANOMALY_DETECTOR_VERSION,
        source_id=encoding_report.source_id,
        source_sha256=encoding_report.source_sha256,
        size_bytes=encoding_report.size_bytes,
        selected_encoding=encoding_report.selected_encoding,
        offset_basis=OFFSET_BASIS,
        scan_status="blocked",
        scanned_character_count=0,
        scanned_line_count=0,
        finding_count=0,
        category_counts={},
        rule_counts={},
        recommended_action="resolve_source_blockers",
        blockers=tuple(dict.fromkeys((*encoding_report.blockers, blocker))),
        warnings=tuple(encoding_report.warnings),
        policy=policy.to_dict(),
        marker_groups=tuple(group.to_dict() for group in marker_groups),
        findings=(),
        project_acceptance_performed=False,
        may_accept_project=False,
        may_freeze=False,
    )


def inspect_source_anomalies(
    path: str | PathLike[str],
    *,
    policy: AnomalyPolicy | None = None,
    marker_groups: Iterable[MarkerGroup] = (),
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> AnomalyInspectionReport:
    """Emit conservative anomaly candidates for one strictly decodable source.

    Character offsets address decoded text after an external byte-order mark has
    been removed. Findings are evidence for review only, not contamination verdicts.
    """

    active_policy = policy or AnomalyPolicy()
    groups = tuple(marker_groups)
    names = [group.name for group in groups]
    if len(set(names)) != len(names):
        raise AnomalyInspectionError("marker group names must be unique")

    try:
        encoding_report = inspect_source_encoding(path, block_size=block_size)
    except EncodingInspectionError as exc:
        raise AnomalyInspectionError(str(exc)) from exc

    if not encoding_report.strict_decode_passed or encoding_report.selected_encoding is None:
        return _blocked_report(
            encoding_report=encoding_report,
            policy=active_policy,
            marker_groups=groups,
            blocker="SOURCE_NOT_STRICTLY_DECODABLE_FOR_ANOMALY_SCAN",
        )

    candidate = Path(path)
    findings: list[AnomalyFinding] = []
    warnings = list(encoding_report.warnings)
    duplicate_index: dict[str, _SeenLine] = {}
    finding_limit_reached = False
    duplicate_limit_reached = False
    previous_normalized: str | None = None
    repeated_run = 0
    previous_profile: _ScriptProfile | None = None
    previous_profile_line = 0
    scanned_characters = 0
    scanned_lines = 0

    def add(finding: AnomalyFinding) -> None:
        nonlocal finding_limit_reached
        if len(findings) >= active_policy.max_findings:
            finding_limit_reached = True
            return
        findings.append(finding)

    prefix = _BOM_PREFIX_BYTES.get(encoding_report.bom, b"")
    try:
        with candidate.open("rb") as raw_handle:
            if prefix and raw_handle.read(len(prefix)) != prefix:
                raise AnomalyInspectionError(
                    "source byte-order mark changed after encoding inspection"
                )
            with io.TextIOWrapper(
                raw_handle,
                encoding=encoding_report.selected_encoding,
                errors="strict",
                newline="",
            ) as text_handle:
                for line_number, physical_line in enumerate(text_handle, start=1):
                    scanned_lines = line_number
                    line_start = scanned_characters
                    scanned_characters += len(physical_line)
                    content = _strip_line_ending(physical_line)
                    line_end = line_start + len(content)

                    for index, character in enumerate(content):
                        codepoint = ord(character)
                        rule: tuple[str, str] | None = None
                        if character == "\ufffd":
                            rule = ("UNICODE_REPLACEMENT_CHARACTER", "replacement")
                        elif character == "\x00":
                            rule = ("UNICODE_NUL_CHARACTER", "nul")
                        elif character == "\ufeff":
                            rule = ("UNICODE_EMBEDDED_BOM", "embedded_bom")
                        elif _is_noncharacter(codepoint):
                            rule = ("UNICODE_NONCHARACTER", "noncharacter")
                        elif unicodedata.category(character) == "Cc" and character not in "\t\f":
                            rule = ("UNICODE_CONTROL_CHARACTER", "control")
                        if rule is not None:
                            add(
                                _make_finding(
                                    source_sha256=encoding_report.source_sha256,
                                    rule_id=rule[0],
                                    category="text_anomaly",
                                    severity="high",
                                    confidence="high",
                                    recommended_action="inspect_exact_span",
                                    start_char=line_start + index,
                                    end_char=line_start + index + 1,
                                    start_line=line_number,
                                    end_line=line_number,
                                    evidence=character,
                                    preview_characters=active_policy.preview_characters,
                                    signals=(rule[1], f"U+{codepoint:04X}"),
                                )
                            )

                    if len(content) > active_policy.max_line_characters:
                        add(
                            _make_finding(
                                source_sha256=encoding_report.source_sha256,
                                rule_id="LINE_EXCEEDS_LENGTH_LIMIT",
                                category="structural_anomaly",
                                severity="medium",
                                confidence="high",
                                recommended_action="inspect_line_boundary",
                                start_char=line_start,
                                end_char=line_end,
                                start_line=line_number,
                                end_line=line_number,
                                evidence=content,
                                preview_characters=active_policy.preview_characters,
                                signals=(f"length={len(content)}",),
                            )
                        )

                    for signal_name, pattern in _WEB_PATTERNS:
                        for match in pattern.finditer(content):
                            add(
                                _make_finding(
                                    source_sha256=encoding_report.source_sha256,
                                    rule_id="WEB_RESIDUE_CANDIDATE",
                                    category="contamination_candidate",
                                    severity="medium",
                                    confidence="high",
                                    recommended_action="review_and_optionally_exclude_span",
                                    start_char=line_start + match.start(),
                                    end_char=line_start + match.end(),
                                    start_line=line_number,
                                    end_line=line_number,
                                    evidence=match.group(0),
                                    preview_characters=active_policy.preview_characters,
                                    signals=(signal_name,),
                                )
                            )

                    paratext = _PARATEXT_PATTERN.search(content)
                    if paratext is not None:
                        add(
                            _make_finding(
                                source_sha256=encoding_report.source_sha256,
                                rule_id="AUTHOR_META_OR_PARATEXT_CANDIDATE",
                                category="paratext_candidate",
                                severity="low",
                                confidence="medium",
                                recommended_action="classify_before_canonical_indexing",
                                start_char=line_start,
                                end_char=line_end,
                                start_line=line_number,
                                end_line=line_number,
                                evidence=content,
                                preview_characters=active_policy.preview_characters,
                                signals=(paratext.group(0).strip(),),
                            )
                        )

                    folded = content.casefold()
                    matched_groups: list[str] = []
                    matched_markers: set[str] = set()
                    for group in groups:
                        group_matches = {
                            marker
                            for marker in group.markers
                            if marker.casefold() in folded
                        }
                        if group_matches:
                            matched_groups.append(group.name)
                            matched_markers.update(group_matches)
                    if (
                        len(matched_markers) >= active_policy.marker_min_total
                        and len(matched_groups) >= active_policy.marker_min_groups
                    ):
                        add(
                            _make_finding(
                                source_sha256=encoding_report.source_sha256,
                                rule_id="CUSTOM_MARKER_CLUSTER_CANDIDATE",
                                category="contamination_candidate",
                                severity="medium",
                                confidence="medium",
                                recommended_action="manual_cross_work_review",
                                start_char=line_start,
                                end_char=line_end,
                                start_line=line_number,
                                end_line=line_number,
                                evidence=content,
                                preview_characters=active_policy.preview_characters,
                                signals=tuple(
                                    [f"groups={','.join(matched_groups)}"]
                                    + [f"marker={item}" for item in sorted(matched_markers)]
                                ),
                            )
                        )

                    normalized = _normalized_line(content)
                    if not normalized:
                        previous_normalized = None
                        repeated_run = 0
                        previous_profile = None
                        previous_profile_line = 0
                        continue

                    if normalized == previous_normalized:
                        repeated_run += 1
                    else:
                        repeated_run = 1
                    previous_normalized = normalized
                    if repeated_run == active_policy.repeated_line_run:
                        add(
                            _make_finding(
                                source_sha256=encoding_report.source_sha256,
                                rule_id="REPEATED_LINE_RUN_CANDIDATE",
                                category="contamination_candidate",
                                severity="medium",
                                confidence="high",
                                recommended_action="inspect_repeated_span",
                                start_char=line_start,
                                end_char=line_end,
                                start_line=line_number,
                                end_line=line_number,
                                evidence=content,
                                preview_characters=active_policy.preview_characters,
                                signals=(f"run_length={repeated_run}",),
                            )
                        )

                    if len(normalized) >= active_policy.duplicate_min_characters:
                        digest = sha256(normalized.encode("utf-8")).hexdigest()
                        first = duplicate_index.get(digest)
                        if (
                            first is not None
                            and line_number - first.line_number
                            >= active_policy.duplicate_min_line_distance
                        ):
                            add(
                                _make_finding(
                                    source_sha256=encoding_report.source_sha256,
                                    rule_id="DISTANT_DUPLICATE_PASSAGE_CANDIDATE",
                                    category="contamination_candidate",
                                    severity="medium",
                                    confidence="high",
                                    recommended_action="compare_duplicate_occurrences",
                                    start_char=line_start,
                                    end_char=line_end,
                                    start_line=line_number,
                                    end_line=line_number,
                                    evidence=content,
                                    preview_characters=active_policy.preview_characters,
                                    signals=(
                                        f"first_line={first.line_number}",
                                        f"first_start_char={first.start_char}",
                                        f"first_end_char={first.end_char}",
                                    ),
                                )
                            )
                        elif first is None:
                            if len(duplicate_index) < active_policy.max_duplicate_fingerprints:
                                duplicate_index[digest] = _SeenLine(
                                    line_number=line_number,
                                    start_char=line_start,
                                    end_char=line_end,
                                )
                            else:
                                duplicate_limit_reached = True

                    if len(content) >= active_policy.script_shift_min_characters:
                        profile = _script_profile(content)
                        if previous_profile is not None and previous_profile_line == line_number - 1:
                            cjk_delta = abs(profile.cjk_ratio - previous_profile.cjk_ratio)
                            ascii_delta = abs(
                                profile.ascii_alpha_ratio
                                - previous_profile.ascii_alpha_ratio
                            )
                            if (
                                cjk_delta >= active_policy.script_shift_cjk_delta
                                and ascii_delta >= active_policy.script_shift_ascii_delta
                            ):
                                add(
                                    _make_finding(
                                        source_sha256=encoding_report.source_sha256,
                                        rule_id="ABRUPT_SCRIPT_PROFILE_SHIFT_CANDIDATE",
                                        category="contamination_candidate",
                                        severity="low",
                                        confidence="medium",
                                        recommended_action="inspect_local_transition",
                                        start_char=line_start,
                                        end_char=line_end,
                                        start_line=line_number,
                                        end_line=line_number,
                                        evidence=content,
                                        preview_characters=active_policy.preview_characters,
                                        signals=(
                                            f"previous_line={previous_profile_line}",
                                            f"cjk_delta={cjk_delta:.3f}",
                                            f"ascii_alpha_delta={ascii_delta:.3f}",
                                        ),
                                    )
                                )
                        previous_profile = profile
                        previous_profile_line = line_number
                    else:
                        previous_profile = None
                        previous_profile_line = 0
    except (OSError, UnicodeError) as exc:
        raise AnomalyInspectionError(f"anomaly scan failed: {exc}") from exc

    try:
        final_sha256 = sha256_file(candidate, block_size=block_size)
    except HashingError as exc:
        raise AnomalyInspectionError(str(exc)) from exc
    if final_sha256 != encoding_report.source_sha256:
        raise AnomalyInspectionError("source changed during anomaly inspection")

    if finding_limit_reached:
        warnings.append("FINDING_LIMIT_REACHED")
    if duplicate_limit_reached:
        warnings.append("DUPLICATE_FINGERPRINT_LIMIT_REACHED")

    findings.sort(
        key=lambda item: (
            item.start_char,
            item.end_char,
            item.rule_id,
            item.finding_id,
        )
    )
    category_counts = Counter(item.category for item in findings)
    rule_counts = Counter(item.rule_id for item in findings)
    if finding_limit_reached:
        action = "review_candidates_incomplete_due_to_limit"
    elif findings:
        action = "review_candidates"
    elif warnings:
        action = "review_source_warnings"
    else:
        action = "no_candidates_detected"

    return AnomalyInspectionReport(
        schema_version=ANOMALY_INSPECTION_SCHEMA_VERSION,
        detector_version=ANOMALY_DETECTOR_VERSION,
        source_id=encoding_report.source_id,
        source_sha256=encoding_report.source_sha256,
        size_bytes=encoding_report.size_bytes,
        selected_encoding=encoding_report.selected_encoding,
        offset_basis=OFFSET_BASIS,
        scan_status="completed",
        scanned_character_count=scanned_characters,
        scanned_line_count=scanned_lines,
        finding_count=len(findings),
        category_counts=dict(sorted(category_counts.items())),
        rule_counts=dict(sorted(rule_counts.items())),
        recommended_action=action,
        blockers=(),
        warnings=tuple(dict.fromkeys(warnings)),
        policy=active_policy.to_dict(),
        marker_groups=tuple(group.to_dict() for group in groups),
        findings=tuple(findings),
        project_acceptance_performed=False,
        may_accept_project=False,
        may_freeze=False,
    )
