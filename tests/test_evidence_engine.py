from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import unittest

from tkr.evidence_engine import (
    EVIDENCE_ENGINE_VERSION,
    EvidenceEngineError,
    EvidenceUnit,
    evidence_unit_from_dict,
    extract_evidence_units,
    measure_evidence_coverage,
    verify_evidence_units,
)
from tkr.literary_models import CHAPTER_SCHEMA_VERSION, ChapterRecord, chapter_id


SOURCE = (
    "卷一 第一章 初见\n"
    "林舟来到北山。赵衡在山门前等候。\n"
    "\n"
    "林舟说道：‘我会查明真相。’\n"
    "\n"
    "卷一 第二章 异常\n"
    "这里是被隔离的污染片段，不应生成可信证据。\n"
)
SOURCE_SHA = sha256(SOURCE.encode("utf-8")).hexdigest()


def _chapter(
    unit_id: str,
    source_order: int,
    start: int,
    end: int,
    body_start: int,
    body_end: int,
    ordinal: int,
    contamination_status: str,
    review_status: str = "accepted_candidate",
) -> ChapterRecord:
    content_hash = sha256(SOURCE[start:end].encode("utf-8")).hexdigest()
    return ChapterRecord(
        CHAPTER_SCHEMA_VERSION,
        chapter_id(SOURCE_SHA, unit_id, source_order, content_hash),
        "src_fixture",
        SOURCE_SHA,
        unit_id,
        "chapter",
        source_order,
        1,
        ordinal,
        SOURCE[start:body_start].strip(),
        SOURCE[start:body_start].strip(),
        f"chapter-{ordinal}",
        start,
        end,
        body_start,
        body_end,
        content_hash,
        "high",
        review_status,
        contamination_status,
    )


def _chapters() -> tuple[ChapterRecord, ChapterRecord]:
    second_start = SOURCE.index("卷一 第二章")
    first_heading_end = SOURCE.index("\n") + 1
    second_heading_end = SOURCE.index("\n", second_start) + 1
    return (
        _chapter(
            "unit_1",
            0,
            0,
            second_start,
            first_heading_end,
            second_start,
            1,
            "clean",
        ),
        _chapter(
            "unit_2",
            1,
            second_start,
            len(SOURCE),
            second_heading_end,
            len(SOURCE),
            2,
            "contaminated",
        ),
    )


class EvidenceEngineTests(unittest.TestCase):
    def test_extracts_complete_clean_body_and_blocks_contamination(self) -> None:
        first, second = _chapters()
        result = extract_evidence_units(SOURCE, (first, second), target_chars=18, max_chars=28)

        self.assertTrue(result.coverage.complete)
        self.assertEqual(result.coverage.coverage_rate, 1.0)
        self.assertEqual(result.coverage.eligible_chapter_count, 1)
        self.assertEqual(result.coverage.blocked_chapter_count, 1)
        self.assertEqual(len(result.coverage.blocked_spans), 1)
        self.assertEqual(result.coverage.blocked_spans[0].chapter_id, second.chapter_id)
        self.assertTrue(result.units)
        self.assertTrue(all(item.chapter_id == first.chapter_id for item in result.units))
        self.assertTrue(all(item.source_status == "clean" for item in result.units))
        self.assertNotIn("污染片段", "".join(item.text for item in result.units))

        clean_body = SOURCE[first.body_start_char:first.body_end_char]
        expected = "".join(character for character in clean_body if not character.isspace())
        actual = "".join(
            character
            for item in result.units
            for character in item.text
            if not character.isspace()
        )
        self.assertEqual(actual, expected)

    def test_every_unit_recomputes_exact_source_binding(self) -> None:
        first, second = _chapters()
        result = extract_evidence_units(SOURCE, (first, second), target_chars=30, max_chars=45)
        for item in result.units:
            self.assertEqual(SOURCE[item.start_char:item.end_char], item.text)
            self.assertEqual(sha256(item.text.encode("utf-8")).hexdigest(), item.text_sha256)
            reparsed = evidence_unit_from_dict(json.loads(json.dumps(item.to_dict(), ensure_ascii=False)))
            self.assertEqual(reparsed, item)

    def test_repeated_extraction_is_deterministic(self) -> None:
        chapters = _chapters()
        first = extract_evidence_units(SOURCE, chapters, target_chars=24, max_chars=40)
        second = extract_evidence_units(SOURCE, chapters, target_chars=24, max_chars=40)
        self.assertEqual(
            [item.to_dict() for item in first.units],
            [item.to_dict() for item in second.units],
        )
        self.assertEqual(first.coverage.to_dict(), second.coverage.to_dict())

    def test_long_sentence_is_not_cut_only_to_meet_soft_limit(self) -> None:
        heading = "第一章 长句\n"
        sentence = "甲" * 80 + "。"
        source = heading + sentence
        source_hash = sha256(source.encode("utf-8")).hexdigest()
        content_hash = sha256(source.encode("utf-8")).hexdigest()
        chapter = ChapterRecord(
            CHAPTER_SCHEMA_VERSION,
            chapter_id(source_hash, "long", 0, content_hash),
            "src_long",
            source_hash,
            "long",
            "chapter",
            0,
            1,
            1,
            heading.strip(),
            heading.strip(),
            "长句",
            0,
            len(source),
            len(heading),
            len(source),
            content_hash,
            "high",
            "accepted_candidate",
            "clean",
        )
        result = extract_evidence_units(source, (chapter,), target_chars=20, max_chars=30)
        self.assertEqual(len(result.units), 1)
        self.assertEqual(result.units[0].text, sentence)
        self.assertEqual(result.units[0].boundary_kind, "oversize_sentence")
        self.assertTrue(result.coverage.complete)

    def test_source_mutation_is_rejected(self) -> None:
        chapters = _chapters()
        mutated = SOURCE.replace("北山", "南山", 1)
        with self.assertRaisesRegex(EvidenceEngineError, "source SHA-256"):
            extract_evidence_units(mutated, chapters)

    def test_missing_unit_content_is_reported(self) -> None:
        chapters = _chapters()
        result = extract_evidence_units(SOURCE, chapters, target_chars=18, max_chars=28)
        incomplete = result.units[1:]
        verification = verify_evidence_units(SOURCE, chapters, incomplete)
        self.assertFalse(verification.valid)
        self.assertIn("EVIDENCE_CONTENT_UNCOVERED", verification.reason_codes)

    def test_overlap_is_reported(self) -> None:
        chapters = _chapters()
        result = extract_evidence_units(SOURCE, chapters, target_chars=18, max_chars=28)
        duplicated = (*result.units, result.units[0])
        with self.assertRaisesRegex(EvidenceEngineError, "duplicate evidence identifier"):
            measure_evidence_coverage(SOURCE, chapters, duplicated)

    def test_tampered_evidence_text_is_rejected(self) -> None:
        chapters = _chapters()
        result = extract_evidence_units(SOURCE, chapters)
        item = result.units[0]
        tampered_text = item.text + "伪"
        tampered_hash = sha256(tampered_text.encode("utf-8")).hexdigest()
        with self.assertRaises(EvidenceEngineError):
            EvidenceUnit(
                item.schema_version,
                item.evidence_id,
                item.source_id,
                item.source_sha256,
                item.unit_id,
                item.chapter_id,
                item.volume_ordinal,
                item.chapter_ordinal,
                item.original_heading,
                item.normalized_heading,
                item.paragraph_ordinal,
                item.sequence_in_chapter,
                item.start_char,
                item.end_char,
                tampered_text,
                tampered_hash,
                item.unit_content_sha256,
                item.source_status,
                item.boundary_kind,
                sum(not character.isspace() for character in tampered_text),
                item.review_status,
            )

    def test_review_only_chapter_is_blocked_even_when_not_contaminated(self) -> None:
        first, _ = _chapters()
        review_only = replace(first, review_status="needs_review")
        result = extract_evidence_units(SOURCE, (review_only,))
        self.assertEqual(result.units, ())
        self.assertEqual(result.coverage.eligible_chapter_count, 0)
        self.assertEqual(result.coverage.blocked_chapter_count, 1)
        self.assertTrue(result.coverage.complete)

    def test_engine_version_is_persisted(self) -> None:
        result = extract_evidence_units(SOURCE, _chapters())
        self.assertEqual(result.coverage.evidence_engine_version, EVIDENCE_ENGINE_VERSION)


if __name__ == "__main__":
    unittest.main()


class PreciseSourceSpanBlockingTests(unittest.TestCase):
    def test_short_web_footer_is_excluded_without_blocking_the_chapter(self) -> None:
        heading = "第一章 精确隔离\n"
        body = "正文第一句。\n未完待续\n正文第二句。\n"
        source = heading + body
        source_hash = sha256(source.encode("utf-8")).hexdigest()
        content_hash = sha256(source.encode("utf-8")).hexdigest()
        chapter = ChapterRecord(
            CHAPTER_SCHEMA_VERSION,
            chapter_id(source_hash, "precise", 0, content_hash),
            "src_precise",
            source_hash,
            "precise",
            "chapter",
            0,
            1,
            1,
            heading.strip(),
            heading.strip(),
            "精确隔离",
            0,
            len(source),
            len(heading),
            len(source),
            content_hash,
            "high",
            "accepted_candidate",
            "contaminated",
        )
        blocked_start = source.index("未完待续")
        findings = (
            {
                "category": "contamination_candidate",
                "severity": "medium",
                "start_char": blocked_start,
                "end_char": blocked_start + len("未完待续"),
            },
        )

        result = extract_evidence_units(
            source,
            (chapter,),
            target_chars=12,
            max_chars=24,
            blocked_source_spans=findings,
        )

        self.assertTrue(result.coverage.complete)
        self.assertEqual(result.coverage.eligible_chapter_count, 1)
        self.assertEqual(result.coverage.blocked_chapter_count, 0)
        self.assertEqual(len(result.coverage.blocked_spans), 1)
        self.assertEqual(result.coverage.blocked_spans[0].reason, "blocked_source_span")
        self.assertNotIn("未完待续", "".join(item.text for item in result.units))
        self.assertTrue(
            all(
                not (item.start_char < blocked_start + 4 and blocked_start < item.end_char)
                for item in result.units
            )
        )
        expected = "".join(
            character
            for index, character in enumerate(source[len(heading):], start=len(heading))
            if not character.isspace()
            and not blocked_start <= index < blocked_start + len("未完待续")
        )
        actual = "".join(
            character
            for item in result.units
            for character in item.text
            if not character.isspace()
        )
        self.assertEqual(actual, expected)
        verification = verify_evidence_units(
            source,
            (chapter,),
            result.units,
            blocked_source_spans=findings,
        )
        self.assertTrue(verification.valid, verification.reason_codes)

    def test_exact_span_covering_all_content_blocks_the_chapter(self) -> None:
        heading = "第一章 全阻断\n"
        body = "未完待续"
        source = heading + body
        source_hash = sha256(source.encode("utf-8")).hexdigest()
        content_hash = sha256(source.encode("utf-8")).hexdigest()
        chapter = ChapterRecord(
            CHAPTER_SCHEMA_VERSION,
            chapter_id(source_hash, "fully-blocked", 0, content_hash),
            "src_fully_blocked",
            source_hash,
            "fully-blocked",
            "chapter",
            0,
            1,
            1,
            heading.strip(),
            heading.strip(),
            "全阻断",
            0,
            len(source),
            len(heading),
            len(source),
            content_hash,
            "high",
            "accepted_candidate",
            "contaminated",
        )
        findings = (
            {
                "category": "contamination_candidate",
                "severity": "medium",
                "start_char": len(heading),
                "end_char": len(source),
            },
        )
        result = extract_evidence_units(
            source,
            (chapter,),
            blocked_source_spans=findings,
        )
        self.assertEqual(result.units, ())
        self.assertEqual(result.coverage.eligible_chapter_count, 0)
        self.assertEqual(result.coverage.blocked_chapter_count, 1)
        self.assertTrue(result.coverage.complete)
