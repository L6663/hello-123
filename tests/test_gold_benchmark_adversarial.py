from __future__ import annotations

from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from test_gold_benchmark import GoldBenchmarkFixture
from tkr.gold_benchmark import (
    POLICIES,
    BenchmarkError,
    evaluate_gold_benchmark,
    load_gold_cases,
    verify_benchmark_report,
)


class GoldBenchmarkAdversarialTests(GoldBenchmarkFixture):
    def test_builtin_policy_registry_and_nested_thresholds_are_immutable(self):
        with self.assertRaises(TypeError):
            POLICIES["custom"] = POLICIES["smoke"]
        with self.assertRaises(TypeError):
            POLICIES["release"].metric_floors["exact_case_accuracy"] = 0.0
        with self.assertRaises(TypeError):
            POLICIES["release"].min_refusal_by_decision["refused_unsupported"] = 0

    def test_spoofed_hard_negative_tags_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, gold, rows = self.make_benchmark(root)
            spoofed = deepcopy(rows)
            answered = next(row for row in spoofed if row["case_id"] == "A-COUNT")
            answered["tags"].append("temporal_scope")
            self.write_rows(gold, spoofed)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

            spoofed = deepcopy(rows)
            location_refusal = next(row for row in spoofed if row["case_id"] == "R-LEXICAL")
            location_refusal["tags"].append("absence_not_negative")
            self.write_rows(gold, spoofed)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

    def test_relation_direction_tag_requires_reverse_fact_in_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, rows = self.make_benchmark(root)
            spoofed = deepcopy(rows)
            direction = next(row for row in spoofed if row["case_id"] == "R-DIRECTION")
            direction["question"] = "王五击败了谁？"
            self.write_rows(gold, spoofed)
            report = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
        self.assertFalse(report.passed)
        self.assertEqual(report.metrics["hard_negative_validation_error_count"], 1)
        self.assertIn(
            "METRIC_HARD_NEGATIVE_VALIDATION_ERROR_COUNT_ABOVE_POLICY_CEILING",
            report.blockers,
        )
        self.assertEqual(report.coverage["hard_negative_tag_counts"]["relation_direction"], 0)
        self.assertEqual(
            report.coverage["declared_hard_negative_tag_counts"]["relation_direction"], 1
        )

    def test_each_hard_negative_family_requires_observable_index_evidence(self):
        attacks = (
            ("R-CONTESTED", "旅客有多少名？", ["numeric_prefix"], "numeric_prefix"),
            ("R-TEMPORAL", "旅客有多少名？", ["temporal_scope"], "temporal_scope"),
            ("R-TEMPORAL", "旅客有多少名？", ["contested_fact"], "contested_fact"),
            ("R-LEXICAL", "旅客有多少层？", ["lexical_distractor"], "lexical_distractor"),
            (
                "R-OPEN-2",
                "银河是谁发明的？",
                ["entity_only_no_predicate"],
                "entity_only_no_predicate",
            ),
            (
                "R-OPEN-1",
                "银河为何发光？",
                ["unsupported_open_predicate"],
                "unsupported_open_predicate",
            ),
            (
                "R-ABSENCE",
                "访客允许进入吗？",
                ["absence_not_negative"],
                "absence_not_negative",
            ),
        )
        for case_id, question, tags, failed_tag in attacks:
            with self.subTest(tag=failed_tag), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths, gold, rows = self.make_benchmark(root)
                spoofed = deepcopy(rows)
                target = next(row for row in spoofed if row["case_id"] == case_id)
                target["question"] = question
                target["tags"] = tags
                self.write_rows(gold, spoofed)
                report = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
                result = next(item for item in report.cases if item.case_id == case_id)
            self.assertFalse(report.passed)
            self.assertIn(
                f"HARD_NEGATIVE_EVIDENCE_NOT_ESTABLISHED:{failed_tag}",
                result.reason_codes,
            )
            self.assertLess(
                report.coverage["hard_negative_tag_counts"][failed_tag],
                report.coverage["declared_hard_negative_tag_counts"][failed_tag],
            )

    def test_numeric_prefix_requires_same_subject_and_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, rows = self.make_benchmark(root)
            spoofed = deepcopy(rows)
            target = next(row for row in spoofed if row["case_id"] == "R-CONTESTED")
            target["question"] = "守卫有多少名？"
            target["tags"] = ["numeric_prefix"]
            self.write_rows(gold, spoofed)
            report = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
            result = next(item for item in report.cases if item.case_id == "R-CONTESTED")
        self.assertIn(
            "HARD_NEGATIVE_EVIDENCE_NOT_ESTABLISHED:numeric_prefix",
            result.reason_codes,
        )

    def test_numeric_prefix_rejects_substring_subject_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, rows = self.make_benchmark(root)
            spoofed = deepcopy(rows)
            target = next(row for row in spoofed if row["case_id"] == "R-CONTESTED")
            target["question"] = "大来客有多少名？"
            target["tags"] = ["numeric_prefix"]
            self.write_rows(gold, spoofed)
            report = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
            result = next(item for item in report.cases if item.case_id == "R-CONTESTED")
        self.assertFalse(report.passed)
        self.assertIn(
            "HARD_NEGATIVE_EVIDENCE_NOT_ESTABLISHED:numeric_prefix",
            result.reason_codes,
        )
        self.assertEqual(report.coverage["hard_negative_tag_counts"]["numeric_prefix"], 0)

    def test_smoke_report_cannot_satisfy_required_release_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            smoke = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
            result = verify_benchmark_report(
                paths[4],
                gold,
                smoke.to_dict(),
                expected_profile="release",
            )
        self.assertFalse(result.accepted)
        self.assertIn("BENCHMARK_REQUIRED_PROFILE_MISMATCH", result.reason_codes)

    def test_exact_but_failed_release_report_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            failed_release = evaluate_gold_benchmark(paths[4], gold, profile="release")
            self.assertFalse(failed_release.passed)
            result = verify_benchmark_report(
                paths[4],
                gold,
                failed_release.to_dict(),
                expected_profile="release",
            )
        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "rejected")
        self.assertIn("BENCHMARK_POLICY_NOT_PASSED", result.reason_codes)

    def test_invalid_required_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            smoke = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
            result = verify_benchmark_report(
                paths[4],
                gold,
                smoke.to_dict(),
                expected_profile="custom-zero-threshold",
            )
        self.assertFalse(result.accepted)
        self.assertIn("BENCHMARK_REQUIRED_PROFILE_INVALID", result.reason_codes)

    def test_invalid_hash_and_duplicate_expectations_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, gold, rows = self.make_benchmark(root)
            invalid_hash = deepcopy(rows)
            invalid_hash[0]["expected_evidence_sha256"] = ["not-a-sha256"]
            self.write_rows(gold, invalid_hash)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

            duplicated = deepcopy(rows)
            duplicated[0]["expected_fact_ids"].append(duplicated[0]["expected_fact_ids"][0])
            self.write_rows(gold, duplicated)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

    def test_authority_and_extra_field_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            report = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
            forged = report.to_dict()
            forged["may_freeze"] = True
            forged["unreviewed_authority"] = True
            result = verify_benchmark_report(paths[4], gold, forged)
        self.assertFalse(result.accepted)
        self.assertIn("BENCHMARK_REPORT_FIELDS_UNEXPECTED", result.reason_codes)
        self.assertIn("BENCHMARK_FREEZE_AUTHORITY_MISMATCH", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
