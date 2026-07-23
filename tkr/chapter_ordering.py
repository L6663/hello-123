"""Cross-source ordering review for Stage 2 chapter catalogs."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Iterable, Sequence

from .chapter_engine import (
    CHAPTER_FINDING_SCHEMA_VERSION,
    CanonicalChapter,
    ChapterCatalog,
    ChapterFinding,
    SourceBinding,
)


def _stable_id(*parts: object) -> str:
    payload = "\0".join(str(part) for part in parts)
    return "chf_" + sha256(payload.encode("utf-8")).hexdigest()[:32]


def _key(volume: int | None, chapter: int | None) -> tuple[int, int] | None:
    if volume is None or chapter is None:
        return None
    return volume, chapter


def _finding(
    rule_id: str,
    severity: str,
    confidence: str,
    action: str,
    sources: Sequence[SourceBinding],
    chapters: Sequence[CanonicalChapter],
    signals: Iterable[str],
) -> ChapterFinding:
    chapter_ids = tuple(sorted({item.chapter_id for item in chapters}))
    source_ids = tuple(sorted({item.source_binding_id for item in sources}))
    signal_tuple = tuple(signals)
    return ChapterFinding(
        CHAPTER_FINDING_SCHEMA_VERSION,
        _stable_id(rule_id, source_ids, chapter_ids, signal_tuple),
        rule_id,
        "source_order",
        severity,
        confidence,
        action,
        chapter_ids,
        source_ids,
        "",
        signal_tuple,
    )


def _boundary_chapters(
    catalog: ChapterCatalog,
    source_binding_id: str,
) -> tuple[CanonicalChapter, ...]:
    rows = sorted(
        (item for item in catalog.chapters if item.source_binding_id == source_binding_id),
        key=lambda item: item.local_physical_order,
    )
    if not rows:
        return ()
    if len(rows) == 1:
        return (rows[0],)
    return rows[0], rows[-1]


def augment_cross_source_order(catalog: ChapterCatalog) -> ChapterCatalog:
    """Add deterministic cross-file order findings without altering either order."""

    sources = sorted(catalog.sources, key=lambda item: item.input_order)
    additions: list[ChapterFinding] = []
    for source in sources:
        first = _key(source.first_known_volume, source.first_known_chapter)
        last = _key(source.last_known_volume, source.last_known_chapter)
        if first is None or last is None:
            additions.append(
                _finding(
                    "SOURCE_NUMBERING_RANGE_UNRESOLVED",
                    "medium",
                    "high",
                    "preserve_input_order_and_review_source_boundaries",
                    (source,),
                    _boundary_chapters(catalog, source.source_binding_id),
                    (
                        f"source_filename={source.source_filename}",
                        f"input_order={source.input_order}",
                        f"numbering_coverage={source.numbering_coverage:.6f}",
                    ),
                )
            )
    for previous, current in zip(sources, sources[1:]):
        previous_first = _key(previous.first_known_volume, previous.first_known_chapter)
        previous_last = _key(previous.last_known_volume, previous.last_known_chapter)
        current_first = _key(current.first_known_volume, current.first_known_chapter)
        current_last = _key(current.last_known_volume, current.last_known_chapter)
        if None in (previous_first, previous_last, current_first, current_last):
            continue
        assert previous_first is not None
        assert previous_last is not None
        assert current_first is not None
        assert current_last is not None
        chapters = (
            *_boundary_chapters(catalog, previous.source_binding_id),
            *_boundary_chapters(catalog, current.source_binding_id),
        )
        if current_first <= previous_last:
            additions.append(
                _finding(
                    "SOURCE_NUMBERING_RANGE_OVERLAP",
                    "high",
                    "high",
                    "preserve_input_order_and_review_duplicate_or_wrong_numbering",
                    (previous, current),
                    chapters,
                    (
                        f"previous_source={previous.source_filename}",
                        f"previous_first={previous_first[0]}:{previous_first[1]}",
                        f"previous_last={previous_last[0]}:{previous_last[1]}",
                        f"current_source={current.source_filename}",
                        f"current_first={current_first[0]}:{current_first[1]}",
                        f"current_last={current_last[0]}:{current_last[1]}",
                    ),
                )
            )
        if current_first < previous_first:
            additions.append(
                _finding(
                    "SOURCE_INPUT_ORDER_DIFFERS_FROM_NUMBERING",
                    "medium",
                    "high",
                    "retain_physical_input_order_and_offer_numbering_order_as_candidate",
                    (previous, current),
                    chapters,
                    (
                        f"previous_input_order={previous.input_order}",
                        f"previous_first={previous_first[0]}:{previous_first[1]}",
                        f"current_input_order={current.input_order}",
                        f"current_first={current_first[0]}:{current_first[1]}",
                    ),
                )
            )
    if not additions:
        return catalog
    existing = {item.finding_id: item for item in catalog.findings}
    for item in additions:
        existing.setdefault(item.finding_id, item)
    findings = tuple(
        sorted(existing.values(), key=lambda item: (item.rule_id, item.finding_id))
    )
    report = replace(catalog.report, finding_count=len(findings))
    return ChapterCatalog(
        catalog.sources,
        catalog.chapters,
        catalog.canonical_order,
        findings,
        report,
    )


__all__ = ["augment_cross_source_order"]
