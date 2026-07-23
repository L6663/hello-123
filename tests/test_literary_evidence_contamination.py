from __future__ import annotations

from hashlib import sha256
import unittest

from tkr import literary_engine
from tkr.literary_models import CHAPTER_SCHEMA_VERSION, ChapterRecord


class LiteraryEvidenceContaminationTests(unittest.TestCase):
    def chapter(self, source: str) -> ChapterRecord:
        return ChapterRecord(
            CHAPTER_SCHEMA_VERSION,
            "chapter-1",
            "source-1",
            "a" * 64,
            "unit-1",
            "chapter",
            0,
            None,
            1,
            "第一章",
            "第一章",
            "第一章",
            0,
            len(source),
            0,
            len(source),
            sha256(source.encode("utf-8")).hexdigest(),
            "high",
            "accepted",
            "contaminated",
        )

    def test_clean_fact_span_inside_partly_contaminated_chapter_remains_clean(self) -> None:
        source = "广告污染\n张三击败李四。"
        start = source.index("张三")
        end = len(source)
        row = {
            "evidence_start": start,
            "evidence_end": end,
            "evidence_sha256": sha256(source[start:end].encode("utf-8")).hexdigest(),
        }
        findings = [{
            "start_char": 0,
            "end_char": source.index("张三"),
            "category": "contamination_candidate",
            "severity": "high",
        }]
        anchor = literary_engine._anchor(
            source,
            row,
            self.chapter(source),
            role="direct_fact",
            supplied_hash_key="evidence_sha256",
            findings=findings,
        )
        self.assertEqual(anchor.source_status, "clean")

    def test_fact_span_overlapping_contamination_is_blocked(self) -> None:
        source = "张三击败李四。"
        row = {
            "evidence_start": 0,
            "evidence_end": len(source),
            "evidence_sha256": sha256(source.encode("utf-8")).hexdigest(),
        }
        findings = [{
            "start_char": 0,
            "end_char": len(source),
            "category": "contamination_candidate",
            "severity": "high",
        }]
        anchor = literary_engine._anchor(
            source,
            row,
            self.chapter(source),
            role="direct_fact",
            supplied_hash_key="evidence_sha256",
            findings=findings,
        )
        self.assertEqual(anchor.source_status, "contaminated")


if __name__ == "__main__":
    unittest.main()
