from __future__ import annotations

from hashlib import sha256
import unittest

from tkr.chapter_engine import ChapterSourceInput, build_chapter_catalog


def _source_sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _unit(
    text: str,
    *,
    unit_id: str,
    unit_type: str,
    ordinal: int | None,
    start: int,
    end: int,
    heading_end: int,
    body_start: int,
    parent: str | None,
    heading_id: str | None,
    title: str,
    start_line: int,
    end_line: int,
    review_status: str = "accepted_candidate",
) -> dict[str, object]:
    return {
        "schema_version": "tkr-unit-index-v1",
        "unit_id": unit_id,
        "source_id": "fixture",
        "source_sha256": _source_sha(text),
        "unit_type": unit_type,
        "hierarchy_level": 1 if unit_type == "volume" else 2,
        "ordinal": ordinal,
        "ordinal_text": "" if ordinal is None else str(ordinal),
        "title": title,
        "parent_unit_id": parent,
        "heading_id": heading_id,
        "start_char": start,
        "end_char": end,
        "start_line": start_line,
        "end_line": end_line,
        "heading_start_char": start if heading_id else None,
        "heading_end_char": heading_end if heading_id else None,
        "body_start_char": body_start,
        "body_end_char": end,
        "character_count": end - start,
        "content_sha256": sha256(text[start:end].encode("utf-8")).hexdigest(),
        "structure_confidence": "high",
        "review_status": review_status,
    }


def _heading(
    text: str,
    *,
    heading_id: str,
    start: int,
    end: int,
    unit_type: str,
    ordinal: int | None,
    title: str,
    signals: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "tkr-heading-candidate-v1",
        "heading_id": heading_id,
        "source_id": "fixture",
        "source_sha256": _source_sha(text),
        "rule_id": "FIXTURE",
        "unit_type": unit_type,
        "hierarchy_level": 1 if unit_type == "volume" else 2,
        "ordinal": ordinal,
        "ordinal_text": "" if ordinal is None else str(ordinal),
        "title": title,
        "raw_heading": text[start:end],
        "boundary_start_char": start,
        "start_char": start,
        "end_char": end,
        "heading_end_char": end,
        "body_start_char": end,
        "start_line": 1,
        "end_line": 1,
        "confidence": "high",
        "accepted_as_boundary": True,
        "signals": signals or [],
    }


def _standalone_volume_source() -> ChapterSourceInput:
    text = "第2卷 旧卷\n第2章 后章\n正文乙。\n第1章 前章\n正文甲。\n"
    volume_start = 0
    chapter2_start = text.index("第2章")
    chapter1_start = text.index("第1章")
    volume_heading_end = text.index("\n", volume_start)
    chapter2_heading_end = text.index("\n", chapter2_start)
    chapter1_heading_end = text.index("\n", chapter1_start)
    units = (
        _unit(
            text,
            unit_id="unit_volume_2",
            unit_type="volume",
            ordinal=2,
            start=volume_start,
            end=chapter2_start,
            heading_end=volume_heading_end,
            body_start=volume_heading_end,
            parent=None,
            heading_id="hdg_volume_2",
            title="旧卷",
            start_line=1,
            end_line=1,
        ),
        _unit(
            text,
            unit_id="unit_chapter_2",
            unit_type="chapter",
            ordinal=2,
            start=chapter2_start,
            end=chapter1_start,
            heading_end=chapter2_heading_end,
            body_start=chapter2_heading_end + 1,
            parent="unit_volume_2",
            heading_id="hdg_chapter_2",
            title="后章",
            start_line=2,
            end_line=3,
        ),
        _unit(
            text,
            unit_id="unit_chapter_1",
            unit_type="chapter",
            ordinal=1,
            start=chapter1_start,
            end=len(text),
            heading_end=chapter1_heading_end,
            body_start=chapter1_heading_end + 1,
            parent="unit_volume_2",
            heading_id="hdg_chapter_1",
            title="前章",
            start_line=4,
            end_line=5,
        ),
    )
    headings = (
        _heading(
            text,
            heading_id="hdg_volume_2",
            start=volume_start,
            end=volume_heading_end,
            unit_type="volume",
            ordinal=2,
            title="旧卷",
        ),
        _heading(
            text,
            heading_id="hdg_chapter_2",
            start=chapter2_start,
            end=chapter2_heading_end,
            unit_type="chapter",
            ordinal=2,
            title="后章",
        ),
        _heading(
            text,
            heading_id="hdg_chapter_1",
            start=chapter1_start,
            end=chapter1_heading_end,
            unit_type="chapter",
            ordinal=1,
            title="前章",
        ),
    )
    return ChapterSourceInput(
        "project_standalone",
        "source_standalone",
        "standalone.txt",
        _source_sha(text),
        0,
        text,
        units,
        headings,
    )


def _combined_source(*, duplicate_first: bool = False) -> ChapterSourceInput:
    first = "卷2 1章 重复章" if duplicate_first else "卷3 1章 新章"
    second = "卷3 3章 跳章"
    text = f"{first}\n正文丙。\n{second}\n正文丁。\n"
    second_start = text.index(second)
    first_end = text.index("\n")
    second_end = text.index("\n", second_start)
    first_volume = 2 if duplicate_first else 3
    units = (
        _unit(
            text,
            unit_id="unit_combined_first",
            unit_type="chapter",
            ordinal=1,
            start=0,
            end=second_start,
            heading_end=first_end,
            body_start=first_end + 1,
            parent=None,
            heading_id="hdg_combined_first",
            title="重复章" if duplicate_first else "新章",
            start_line=1,
            end_line=2,
        ),
        _unit(
            text,
            unit_id="unit_combined_second",
            unit_type="chapter",
            ordinal=3,
            start=second_start,
            end=len(text),
            heading_end=second_end,
            body_start=second_end + 1,
            parent=None,
            heading_id="hdg_combined_second",
            title="跳章",
            start_line=3,
            end_line=4,
        ),
    )
    headings = (
        _heading(
            text,
            heading_id="hdg_combined_first",
            start=0,
            end=first_end,
            unit_type="chapter",
            ordinal=1,
            title="重复章" if duplicate_first else "新章",
            signals=[f"container_ordinal={first_volume}"],
        ),
        _heading(
            text,
            heading_id="hdg_combined_second",
            start=second_start,
            end=second_end,
            unit_type="chapter",
            ordinal=3,
            title="跳章",
            signals=["container_ordinal=3"],
        ),
    )
    return ChapterSourceInput(
        "project_combined_duplicate" if duplicate_first else "project_combined",
        "source_combined_duplicate" if duplicate_first else "source_combined",
        "combined-duplicate.txt" if duplicate_first else "combined.txt",
        _source_sha(text),
        1,
        text,
        units,
        headings,
    )


class ChapterEngineTests(unittest.TestCase):
    def test_parent_volume_is_recovered_without_combined_heading(self) -> None:
        catalog = build_chapter_catalog([_standalone_volume_source()])
        self.assertEqual(len(catalog.chapters), 2)
        self.assertEqual([item.volume_ordinal for item in catalog.chapters], [2, 2])
        self.assertEqual(
            [item.volume_basis for item in catalog.chapters],
            ["parent_volume_unit", "parent_volume_unit"],
        )

    def test_physical_order_and_canonical_candidate_are_separate(self) -> None:
        catalog = build_chapter_catalog([_standalone_volume_source()])
        self.assertEqual(
            [item.chapter_ordinal for item in catalog.chapters],
            [2, 1],
        )
        ordered_ids = [item.chapter_id for item in catalog.canonical_order]
        chapter_by_id = {item.chapter_id: item for item in catalog.chapters}
        self.assertEqual(
            [chapter_by_id[item].chapter_ordinal for item in ordered_ids],
            [1, 2],
        )
        self.assertTrue(catalog.report.physical_order_preserved)
        self.assertTrue(catalog.report.canonical_order_is_candidate)
        self.assertIn(
            "CHAPTER_ORDINAL_INVERSION",
            {item.rule_id for item in catalog.findings},
        )

    def test_combined_heading_volume_and_gap_are_recorded(self) -> None:
        catalog = build_chapter_catalog([_combined_source()])
        self.assertEqual([item.volume_ordinal for item in catalog.chapters], [3, 3])
        self.assertTrue(all(item.volume_basis == "combined_heading" for item in catalog.chapters))
        gap = [item for item in catalog.findings if item.rule_id == "CHAPTER_ORDINAL_GAP"]
        self.assertEqual(len(gap), 1)
        self.assertIn("missing_start=2", gap[0].signals)
        self.assertIn("missing_end=2", gap[0].signals)

    def test_duplicate_key_across_files_is_not_silently_merged(self) -> None:
        first = _standalone_volume_source()
        second = _combined_source(duplicate_first=True)
        catalog = build_chapter_catalog([first, second])
        duplicates = [
            item for item in catalog.findings
            if item.rule_id == "DUPLICATE_CANONICAL_KEY"
        ]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].canonical_key, "v000002-c000001")
        self.assertEqual(len(duplicates[0].chapter_ids), 2)
        self.assertEqual(catalog.report.duplicate_key_count, 1)
        self.assertEqual(len(catalog.chapters), 4)

    def test_contaminated_chapter_is_retained_and_blocked(self) -> None:
        source = _standalone_volume_source()
        chapter = source.units[1]
        contaminated = ChapterSourceInput(
            source.project_id,
            source.source_id,
            source.source_filename,
            source.source_sha256,
            source.input_order,
            source.source_text,
            source.units,
            source.headings,
            (
                {
                    "category": "contamination_candidate",
                    "severity": "high",
                    "start_char": chapter["start_char"],
                    "end_char": chapter["end_char"],
                },
            ),
        )
        catalog = build_chapter_catalog([contaminated])
        self.assertEqual(catalog.chapters[0].contamination_status, "contaminated")
        self.assertIn(
            "CHAPTER_NOT_CLEAN",
            {item.rule_id for item in catalog.findings},
        )
        self.assertEqual(catalog.report.contaminated_or_review_count, 1)

    def test_repeated_builds_are_logically_identical(self) -> None:
        inputs = [_standalone_volume_source(), _combined_source()]
        first = build_chapter_catalog(inputs)
        second = build_chapter_catalog(inputs)
        self.assertEqual(
            [item.to_dict() for item in first.sources],
            [item.to_dict() for item in second.sources],
        )
        self.assertEqual(
            [item.to_dict() for item in first.chapters],
            [item.to_dict() for item in second.chapters],
        )
        self.assertEqual(
            [item.to_dict() for item in first.findings],
            [item.to_dict() for item in second.findings],
        )
        self.assertEqual(first.report.to_dict(), second.report.to_dict())


if __name__ == "__main__":
    unittest.main()
