from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tkr.anomaly_detection import AnomalyPolicy, inspect_source_anomalies
from tkr.claim_validation import ClaimCandidate, validate_claim
from tkr.structure_detection import inspect_source_structure


class Stage6R1RemediationTests(unittest.TestCase):
    def _source(self, root: Path, text: str, name: str = "source.txt") -> Path:
        path = root / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def _count(self, evidence: str, subject: str, value: int, unit: str = "枚"):
        candidate = ClaimCandidate(
            claim_type="count",
            subject=subject,
            value=value,
            unit=unit,
            source_id="source",
            unit_id="unit",
            evidence_start=0,
            evidence_end=len(evidence),
            evidence_text=evidence,
        )
        return validate_claim(candidate, evidence)

    def test_entity_discontinuity_is_one_signal_family_and_needs_lexical_break(self):
        first = "青云宗弟子守护青云城并在青云谷巡查。" * 30
        second = "赤霞宗弟子守护赤霞城并在赤霞谷巡查。" * 30
        with tempfile.TemporaryDirectory() as directory:
            path = self._source(Path(directory), first + second)
            report = inspect_source_anomalies(
                path,
                policy=AnomalyPolicy(
                    window_characters=len(first),
                    window_stride=len(first),
                    window_min_characters=100,
                    same_language_max_cosine_similarity=0.01,
                    same_language_min_entity_union=2,
                    same_language_max_entity_jaccard=0.20,
                    same_language_min_signals=2,
                ),
            )
        self.assertNotIn("SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE", report.rule_counts)

    def test_true_cross_work_shift_keeps_multiple_independent_signals(self):
        first = (
            "青云宗弟子守在剑阁，灵气沿丹田运转，携带灵石进入秘境。"
            "掌门命内门弟子前往玄天山谷修炼剑意。"
        ) * 10
        second = (
            "华星公司董事会召开会议，经理通过邮件通知办公室员工。"
            "记者使用手机直播，警察驾驶汽车抵达现场。"
        ) * 10
        with tempfile.TemporaryDirectory() as directory:
            path = self._source(Path(directory), first + second)
            report = inspect_source_anomalies(
                path,
                policy=AnomalyPolicy(
                    window_characters=len(first),
                    window_stride=len(first),
                    window_min_characters=100,
                    same_language_max_cosine_similarity=0.45,
                    same_language_min_entity_union=2,
                    same_language_max_entity_jaccard=0.20,
                    same_language_min_register_delta=0.55,
                    same_language_min_signals=2,
                ),
            )
        finding = next(
            item for item in report.findings
            if item.rule_id == "SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE"
        )
        entity_signals = [x for x in finding.signals if x.startswith("entity_")]
        self.assertEqual(len(entity_signals), 1)
        self.assertTrue(any(x.startswith("lexical_cosine=") for x in finding.signals))

    def test_combined_volume_chapter_prefix_is_a_chapter_boundary(self):
        text = "卷五 第二十六章 风雪夜归人\n正文甲。\n卷五 第二十七章 山河故人\n正文乙。\n"
        with tempfile.TemporaryDirectory() as directory:
            report = inspect_source_structure(self._source(Path(directory), text))
        self.assertEqual([unit.unit_type for unit in report.units], ["chapter", "chapter"])
        self.assertEqual([unit.ordinal for unit in report.units], [26, 27])
        self.assertFalse(any(item.rule_id.startswith("ORDINAL_") for item in report.findings))
        self.assertIn("container_ordinal=5", report.headings[0].signals)

    def test_combined_prefixed_volume_and_chapter_is_supported(self):
        text = "第五卷 第二十六章 风雪夜归人\n正文。\n"
        with tempfile.TemporaryDirectory() as directory:
            report = inspect_source_structure(self._source(Path(directory), text))
        self.assertEqual(report.units[0].unit_type, "chapter")
        self.assertEqual(report.units[0].ordinal, 26)
        self.assertEqual(report.units[0].title, "风雪夜归人")

    def test_count_ignores_digits_inside_subject_name(self):
        result = self._count("阵列00共有3枚令牌。", "阵列00", 3)
        self.assertEqual(result.status, "accepted")
        self.assertNotIn("MULTIPLE_COUNT_VALUES", result.reason_codes)

    def test_count_ignores_numeral_inside_count_cue(self):
        result = self._count("令牌一共有3枚。", "令牌", 3)
        self.assertEqual(result.status, "accepted")

    def test_count_segments_do_not_mix_other_subject_assertions(self):
        result = self._count("阵列00共有3枚令牌，仓库共有4枚令牌。", "阵列00", 3)
        self.assertEqual(result.status, "accepted")

    def test_genuine_multiple_values_remain_review(self):
        result = self._count("阵列00共有3枚和4枚令牌。", "阵列00", 3)
        self.assertEqual(result.status, "review")
        self.assertIn("MULTIPLE_COUNT_VALUES", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
