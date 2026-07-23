from __future__ import annotations

from dataclasses import replace
import unittest

from tkr.chapter_engine import build_chapter_catalog
from tkr.chapter_ordering import augment_cross_source_order
from tests.test_chapter_engine import _combined_source, _standalone_volume_source


class ChapterOrderingTests(unittest.TestCase):
    def test_input_order_conflict_is_reported_without_rewriting_physical_order(self) -> None:
        later_numbered = replace(
            _combined_source(),
            project_id="project_volume_3_first",
            source_id="source_volume_3_first",
            source_filename="volume-3-first.txt",
            input_order=0,
        )
        earlier_numbered = replace(
            _standalone_volume_source(),
            project_id="project_volume_2_second",
            source_id="source_volume_2_second",
            source_filename="volume-2-second.txt",
            input_order=1,
        )
        catalog = augment_cross_source_order(
            build_chapter_catalog([later_numbered, earlier_numbered])
        )
        rules = {item.rule_id for item in catalog.findings}
        self.assertIn("SOURCE_INPUT_ORDER_DIFFERS_FROM_NUMBERING", rules)
        self.assertIn("SOURCE_NUMBERING_RANGE_OVERLAP", rules)
        self.assertEqual(
            [item.source_filename for item in catalog.chapters],
            [
                "volume-3-first.txt",
                "volume-3-first.txt",
                "volume-2-second.txt",
                "volume-2-second.txt",
            ],
        )
        ordered_ids = [item.chapter_id for item in catalog.canonical_order]
        chapter_by_id = {item.chapter_id: item for item in catalog.chapters}
        self.assertEqual(
            [chapter_by_id[item].volume_ordinal for item in ordered_ids],
            [2, 2, 3, 3],
        )

    def test_resolved_nonoverlapping_source_ranges_need_no_source_order_finding(self) -> None:
        catalog = augment_cross_source_order(
            build_chapter_catalog([_standalone_volume_source(), _combined_source()])
        )
        self.assertFalse(
            any(item.category == "source_order" for item in catalog.findings)
        )

    def test_cross_source_augmentation_is_deterministic_and_idempotent(self) -> None:
        base = build_chapter_catalog(
            [_standalone_volume_source(), _combined_source()]
        )
        first = augment_cross_source_order(base)
        second = augment_cross_source_order(first)
        self.assertEqual(
            [item.to_dict() for item in first.findings],
            [item.to_dict() for item in second.findings],
        )
        self.assertEqual(first.report.to_dict(), second.report.to_dict())


if __name__ == "__main__":
    unittest.main()
