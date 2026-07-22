"""Deterministic continuity and placement review findings for Stage 2."""
from __future__ import annotations
from collections import defaultdict
from typing import Iterable
from .structure_models import HeadingCandidate, StructureFinding, UnitRecord, make_finding

def continuity_findings(*, source_sha256: str, units: list[UnitRecord],
                        body_nonwhitespace: list[bool], headings: list[HeadingCandidate],
                        detached_titles: Iterable[tuple[str, int, int, int, str]],
                        emit_empty_body_candidates: bool,
                        max_findings: int) -> tuple[list[StructureFinding], list[str]]:
    findings: list[StructureFinding] = []
    warnings: list[str] = []
    def add(finding: StructureFinding) -> None:
        if len(findings) < max_findings:
            findings.append(finding)
        elif "FINDING_LIMIT_REACHED" not in warnings:
            warnings.append("FINDING_LIMIT_REACHED")

    for heading in headings:
        if not heading.accepted_as_boundary:
            add(make_finding(
                source_sha256=source_sha256, rule_id="AMBIGUOUS_HEADING_CANDIDATE",
                category="heading_candidate", severity="low", confidence=heading.confidence,
                action="review_before_promoting_to_unit_boundary", unit_id_value=None,
                related=(), start=heading.start_char, end=heading.end_char,
                start_line=heading.start_line, end_line=heading.end_line,
                signals=(f"heading_id={heading.heading_id}", f"rule_id={heading.rule_id}", *heading.signals),
            ))
    for heading_id, start, end, line_number, text in detached_titles:
        add(make_finding(
            source_sha256=source_sha256, rule_id="DETACHED_TITLE_CANDIDATE",
            category="heading_recovery", severity="low", confidence="medium",
            action="review_before_attaching_title_to_heading", unit_id_value=None,
            related=(), start=start, end=end, start_line=line_number, end_line=line_number,
            signals=(f"heading_id={heading_id}", f"candidate_text={text}"),
        ))

    groups: dict[tuple[str | None, str], list[UnitRecord]] = defaultdict(list)
    for unit in units:
        groups[(unit.parent_unit_id, unit.unit_type)].append(unit)
    for (_, unit_type), group in groups.items():
        previous: UnitRecord | None = None
        seen_ordinals: dict[int, UnitRecord] = {}
        seen_titles: dict[str, UnitRecord] = {}
        for unit in group:
            if unit.ordinal is not None:
                first = seen_ordinals.get(unit.ordinal)
                if first is not None:
                    add(make_finding(
                        source_sha256=source_sha256, rule_id="DUPLICATE_ORDINAL_CANDIDATE",
                        category="continuity_anomaly", severity="high", confidence="high",
                        action="review_duplicate_numbering", unit_id_value=unit.unit_id,
                        related=(first.unit_id,), start=unit.start_char, end=unit.end_char,
                        start_line=unit.start_line, end_line=unit.end_line,
                        signals=(f"unit_type={unit_type}", f"ordinal={unit.ordinal}"),
                    ))
                else:
                    seen_ordinals[unit.ordinal] = unit
                if previous is not None and previous.ordinal is not None:
                    if unit.ordinal < previous.ordinal:
                        add(make_finding(
                            source_sha256=source_sha256, rule_id="ORDINAL_INVERSION_CANDIDATE",
                            category="continuity_anomaly", severity="high", confidence="high",
                            action="review_numbering_order", unit_id_value=unit.unit_id,
                            related=(previous.unit_id,), start=unit.start_char, end=unit.end_char,
                            start_line=unit.start_line, end_line=unit.end_line,
                            signals=(f"previous={previous.ordinal}", f"current={unit.ordinal}", f"unit_type={unit_type}"),
                        ))
                    elif unit.ordinal > previous.ordinal + 1:
                        add(make_finding(
                            source_sha256=source_sha256, rule_id="ORDINAL_GAP_CANDIDATE",
                            category="continuity_anomaly", severity="medium", confidence="high",
                            action="review_missing_or_intentionally_skipped_units", unit_id_value=unit.unit_id,
                            related=(previous.unit_id,), start=unit.start_char, end=unit.end_char,
                            start_line=unit.start_line, end_line=unit.end_line,
                            signals=(f"previous={previous.ordinal}", f"current={unit.ordinal}",
                                     f"missing_start={previous.ordinal + 1}", f"missing_end={unit.ordinal - 1}"),
                        ))
                previous = unit
            normalized_title = " ".join(unit.title.casefold().split())
            if normalized_title:
                first_title = seen_titles.get(normalized_title)
                if first_title is not None:
                    add(make_finding(
                        source_sha256=source_sha256, rule_id="DUPLICATE_TITLE_CANDIDATE",
                        category="structure_anomaly", severity="low", confidence="medium",
                        action="review_duplicate_heading_text", unit_id_value=unit.unit_id,
                        related=(first_title.unit_id,), start=unit.start_char, end=unit.end_char,
                        start_line=unit.start_line, end_line=unit.end_line,
                        signals=(f"title={normalized_title}",),
                    ))
                else:
                    seen_titles[normalized_title] = unit

    if emit_empty_body_candidates:
        for unit, has_body in zip(units, body_nonwhitespace):
            if unit.unit_type in {"chapter", "section", "prologue", "epilogue", "extra_story"} and not has_body:
                add(make_finding(
                    source_sha256=source_sha256, rule_id="EMPTY_UNIT_BODY_CANDIDATE",
                    category="structure_anomaly", severity="medium", confidence="high",
                    action="review_heading_or_missing_body", unit_id_value=unit.unit_id,
                    related=(), start=unit.start_char, end=unit.end_char,
                    start_line=unit.start_line, end_line=unit.end_line,
                    signals=(f"unit_type={unit.unit_type}",),
                ))

    first_chapter = next((i for i, unit in enumerate(units) if unit.unit_type == "chapter"), None)
    for index, unit in enumerate(units):
        if unit.unit_type in {"prologue", "preface"} and first_chapter is not None and index > first_chapter:
            add(make_finding(
                source_sha256=source_sha256, rule_id="LATE_FRONT_MATTER_CANDIDATE",
                category="structure_anomaly", severity="low", confidence="medium",
                action="review_special_unit_placement", unit_id_value=unit.unit_id,
                related=(), start=unit.start_char, end=unit.end_char,
                start_line=unit.start_line, end_line=unit.end_line,
                signals=(f"unit_type={unit.unit_type}",),
            ))
        if unit.unit_type == "epilogue":
            later = next((item for item in units[index + 1:] if item.unit_type == "chapter"), None)
            if later is not None:
                add(make_finding(
                    source_sha256=source_sha256, rule_id="CHAPTER_AFTER_EPILOGUE_CANDIDATE",
                    category="structure_anomaly", severity="medium", confidence="medium",
                    action="review_special_unit_placement", unit_id_value=later.unit_id,
                    related=(unit.unit_id,), start=later.start_char, end=later.end_char,
                    start_line=later.start_line, end_line=later.end_line,
                    signals=("chapter_occurs_after_epilogue",),
                ))
    findings.sort(key=lambda item: (item.start_char, item.end_char, item.rule_id, item.finding_id))
    return findings, warnings
